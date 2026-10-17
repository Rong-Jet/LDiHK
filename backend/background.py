"""Background job loops for the import and enrichment workers.

The same loops back the standalone worker scripts and, on free hosting, the
in-process worker threads started by the web app when
``RUN_WORKERS_IN_PROCESS=true``.

In-process loops only touch the database while users are active: a free
Neon project gets 100 compute hours a month, and polling every few seconds
around the clock would keep it awake for all ~744 hours. API requests call
``WorkerSignal.notify()``, which wakes the loops and keeps them polling for
``WORKER_ACTIVE_WINDOW_SECONDS`` afterwards.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import logging
import os
import threading
import time
from typing import Callable, Mapping

LOGGER = logging.getLogger(__name__)

RUN_WORKERS_IN_PROCESS_ENV = "RUN_WORKERS_IN_PROCESS"
RUN_MIGRATIONS_ON_START_ENV = "RUN_MIGRATIONS_ON_START"
WORKER_ACTIVE_WINDOW_ENV = "WORKER_ACTIVE_WINDOW_SECONDS"
WORKER_POLL_INTERVAL_ENV = "WORKER_POLL_INTERVAL_SECONDS"
# Short on purpose: Neon stays awake ~5 minutes after the last query, so each
# minute here costs compute hours. Imports keep the loops active anyway: the
# frontend polls import status every few seconds, and a finished import wakes
# the enrichment loop directly.
DEFAULT_ACTIVE_WINDOW_SECONDS = 120.0
DEFAULT_POLL_INTERVAL_SECONDS = 30.0
MAX_ERROR_BACKOFF_SECONDS = 300.0

RunOnce = Callable[[], bool]


class WorkerSignal:
    """Records recent user traffic and wakes the loops waiting on it."""

    def __init__(
        self,
        *,
        active_window_seconds: float = DEFAULT_ACTIVE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.active_window_seconds = active_window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._last_activity = clock()
        self._events: list[threading.Event] = []

    def register(self) -> threading.Event:
        event = threading.Event()
        with self._lock:
            self._events.append(event)
        return event

    def notify(self) -> None:
        with self._lock:
            self._last_activity = self._clock()
            events = list(self._events)
        for event in events:
            event.set()

    def is_active(self) -> bool:
        with self._lock:
            return self._clock() - self._last_activity < self.active_window_seconds


class WorkerLoop:
    """Calls ``run_once`` until idle, then waits for a wake-up or the poll interval.

    ``run_once`` returns True when it processed something. Exceptions are
    logged and retried with exponential backoff, so a database outage or a
    bad job never kills the thread.
    """

    def __init__(
        self,
        name: str,
        run_once: RunOnce,
        *,
        signal: WorkerSignal,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.name = name
        self.run_once = run_once
        self.signal = signal
        self.poll_interval_seconds = poll_interval_seconds
        self.stop_event = stop_event or threading.Event()
        self._wake = signal.register()

    def run(self) -> None:
        failures = 0
        while not self.stop_event.is_set():
            if not self.signal.is_active():
                self._sleep(self.poll_interval_seconds)
                continue
            try:
                did_work = self.run_once()
            except Exception:
                failures += 1
                delay = min(MAX_ERROR_BACKOFF_SECONDS, 5.0 * 2 ** (failures - 1))
                LOGGER.exception(
                    "%s worker failed (attempt %s); retrying in %.0f s",
                    self.name,
                    failures,
                    delay,
                )
                self._sleep(delay)
                continue
            failures = 0
            if not did_work:
                self._sleep(self.poll_interval_seconds)

    def stop(self) -> None:
        self.stop_event.set()
        self._wake.set()

    def _sleep(self, seconds: float) -> None:
        self._wake.wait(timeout=seconds)
        self._wake.clear()


def make_import_run_once(
    *,
    database_url: str | None = None,
    signal: WorkerSignal | None = None,
) -> RunOnce:
    """One import-queue poll: claim and process at most one import."""
    from backend.db import connect
    from backend.ingestion.s3 import Boto3S3Client
    from backend.ingestion.worker import (
        IMPORT_STATUS_COMPLETED,
        IMPORT_STATUS_IDLE,
        PostgresImportRepository,
        S3ZipImportWorker,
        heartbeat_import,
    )

    s3_client_holder: list[Boto3S3Client] = []

    def heartbeat(import_id: str) -> None:
        with closing(connect(database_url)) as connection:
            heartbeat_import(connection, import_id)

    def run_once() -> bool:
        if not s3_client_holder:
            s3_client_holder.append(Boto3S3Client())
        with closing(connect(database_url)) as connection:
            worker = S3ZipImportWorker(
                repository=PostgresImportRepository(connection),
                s3_client=s3_client_holder[0],
                heartbeat=heartbeat,
            )
            result = worker.process_one()
            if result.status == IMPORT_STATUS_IDLE:
                _sweep_unused_uploads(connection, s3_client_holder[0])
        if result.status == IMPORT_STATUS_IDLE:
            return False
        LOGGER.info(
            "Import %s %s: %s/%s records, %s warnings%s",
            result.import_id,
            result.status,
            result.records_imported,
            result.records_seen,
            result.warnings_count,
            f" ({result.error_message})" if result.error_message else "",
        )
        if result.status == IMPORT_STATUS_COMPLETED and signal is not None:
            # Wake the enrichment loop for the job this import just queued.
            signal.notify()
        return True

    return run_once


def make_enrichment_run_once(
    *,
    database_url: str | None = None,
    repair: bool = False,
    environ: Mapping[str, str] = os.environ,
) -> RunOnce:
    """One enrichment poll: process one queued job (or one repair batch)."""
    from backend.db import connect
    from backend.enrichment.durations import (
        DEFAULT_MAX_DURATION_SECONDS,
        ENRICHMENT_WORKER_STATUS_FAILED,
        ENRICHMENT_WORKER_STATUS_IDLE,
        PostgresEnrichmentRepository,
        YoutubeDurationEnrichmentWorker,
    )
    from backend.enrichment.youtube_api import (
        MAX_VIDEO_IDS_PER_REQUEST,
        YouTubeDataApiClient,
    )

    client = YouTubeDataApiClient.from_env()
    batch_size = _env_int(environ, "ENRICHMENT_BATCH_SIZE", MAX_VIDEO_IDS_PER_REQUEST)
    max_duration_seconds = _env_int(
        environ, "YOUTUBE_MAX_DURATION_SECONDS", DEFAULT_MAX_DURATION_SECONDS
    )
    retry_base_seconds = _env_int(environ, "ENRICHMENT_RETRY_BASE_SECONDS", 300)

    def run_once() -> bool:
        with closing(connect(database_url)) as connection:
            worker = YoutubeDurationEnrichmentWorker(
                repository=PostgresEnrichmentRepository(connection),
                client=client,
                max_duration_seconds=max_duration_seconds,
                batch_size=batch_size,
                retry_base_seconds=retry_base_seconds,
            )
            result = worker.repair_once() if repair else worker.process_one()
        if result.status == ENRICHMENT_WORKER_STATUS_IDLE:
            return False
        summary = result.summary
        if summary is None:
            LOGGER.info(
                "Enrichment job %s %s: %s",
                result.job_id,
                result.status,
                result.error_message,
            )
        else:
            LOGGER.info(
                "Enrichment %s %s: %s available, %s unavailable, %s failed, "
                "%s API calls",
                result.job_id or "repair batch",
                result.status,
                summary.successful_video_count,
                summary.unavailable_video_count,
                summary.failed_video_count,
                summary.api_call_count,
            )
        # A repair batch where every lookup failed means "back off": report
        # idle so the loop waits a poll interval instead of retrying at once.
        return not (repair and result.status == ENRICHMENT_WORKER_STATUS_FAILED)

    return run_once


@dataclass
class InProcessWorkers:
    signal: WorkerSignal
    loops: list[WorkerLoop]
    threads: list[threading.Thread]

    def stop(self) -> None:
        for loop in self.loops:
            loop.stop()


_started_workers: InProcessWorkers | None = None
_start_lock = threading.Lock()


def in_process_workers_enabled(environ: Mapping[str, str] = os.environ) -> bool:
    return _truthy(environ.get(RUN_WORKERS_IN_PROCESS_ENV))


def start_in_process_workers(
    environ: Mapping[str, str] = os.environ,
) -> InProcessWorkers | None:
    """Start the worker threads once per process, if enabled by env."""
    global _started_workers
    if not in_process_workers_enabled(environ):
        return None
    with _start_lock:
        if _started_workers is not None:
            return _started_workers

        # The free Render plan has no pre-deploy step, so the process that runs
        # the workers brings the schema up to date before they start.
        if _truthy(environ.get(RUN_MIGRATIONS_ON_START_ENV, "true")):
            _run_startup_migrations()

        signal = WorkerSignal(
            active_window_seconds=_env_float(
                environ, WORKER_ACTIVE_WINDOW_ENV, DEFAULT_ACTIVE_WINDOW_SECONDS
            )
        )
        poll_interval = _env_float(
            environ, WORKER_POLL_INTERVAL_ENV, DEFAULT_POLL_INTERVAL_SECONDS
        )
        loops = [
            WorkerLoop(
                "import",
                make_import_run_once(signal=signal),
                signal=signal,
                poll_interval_seconds=poll_interval,
            )
        ]
        if environ.get("YOUTUBE_API_KEY", "").strip():
            loops.append(
                WorkerLoop(
                    "enrichment",
                    make_enrichment_run_once(environ=environ),
                    signal=signal,
                    poll_interval_seconds=poll_interval,
                )
            )
        else:
            LOGGER.warning(
                "YOUTUBE_API_KEY is not set; duration enrichment is disabled "
                "and watch time falls back to estimates"
            )

        threads = [
            threading.Thread(target=loop.run, name=f"{loop.name}-worker", daemon=True)
            for loop in loops
        ]
        for thread in threads:
            thread.start()
        LOGGER.info(
            "Started in-process workers: %s",
            ", ".join(loop.name for loop in loops),
        )
        _started_workers = InProcessWorkers(signal=signal, loops=loops, threads=threads)
        return _started_workers


def _run_startup_migrations() -> None:
    from backend import db

    try:
        applied = db.run_migrations()
    except Exception:
        LOGGER.exception("Startup migrations failed; the API answers 503 until the database is ready")
        return
    if applied:
        LOGGER.info("Applied migrations: %s", ", ".join(m.version for m in applied))


def _sweep_unused_uploads(connection, s3_client) -> None:
    """Delete archives of upload URLs that expired unused (see backend/uploads.py)."""
    from backend.uploads import sweep_unused_uploads

    try:
        sweep_unused_uploads(connection, s3_client.raw)
    except Exception:
        LOGGER.warning("Upload cleanup failed", exc_info=True)
        try:
            connection.rollback()
        except Exception:
            pass


def enrichment_available(environ: Mapping[str, str] = os.environ) -> bool:
    """Whether queued duration-enrichment jobs will ever be processed.

    With in-process workers (free hosting) the enrichment thread only starts
    when YOUTUBE_API_KEY is set, so without it jobs would stay queued forever.
    Separate worker deployments are assumed to have their own key.
    """
    if not in_process_workers_enabled(environ):
        return True
    return bool(environ.get("YOUTUBE_API_KEY", "").strip())


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw_value = environ.get(name, "").strip()
    return int(raw_value) if raw_value else default


def _env_float(environ: Mapping[str, str], name: str, default: float) -> float:
    raw_value = environ.get(name, "").strip()
    return float(raw_value) if raw_value else default
