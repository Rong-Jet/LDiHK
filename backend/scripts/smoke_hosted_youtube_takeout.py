#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import uuid
from zipfile import ZIP_DEFLATED, ZipFile

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SMOKE_VIDEO_ID = "dQw4w9WgXcQ"
SMOKE_CHANNEL_ID = "UCuAXFkgsw1L7xaCfnd5JJOw"
DEFAULT_IMPORT_TIMEOUT_SECONDS = 180.0
DEFAULT_ENRICHMENT_TIMEOUT_SECONDS = 240.0
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0


class SmokeFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: object


class JsonHttpClient(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        bearer_token: str | None = None,
    ) -> HttpResponse:
        ...


class S3Uploader(Protocol):
    def upload_zip(self, bucket: str, key: str, body: bytes) -> None:
        ...


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
SleepFn = Callable[[float], None]
EmitFn = Callable[[str], None]


@dataclass(frozen=True)
class HostedSmokeConfig:
    base_url: str
    ldihk_id: str
    s3_bucket: str
    s3_key: str | None = None
    wrong_ldihk_id: str | None = None
    fixture_zip_path: Path | None = None
    upload_fixture: bool = False
    run_migrations: bool = False
    run_import_worker_once: bool = False
    run_enrichment_worker_once: bool = False
    expected_event_count: int = 1
    expected_watch_count: int = 1
    require_api_duration: bool = True
    import_timeout_seconds: float = DEFAULT_IMPORT_TIMEOUT_SECONDS
    enrichment_timeout_seconds: float = DEFAULT_ENRICHMENT_TIMEOUT_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS

    def resolved_s3_key(self) -> str:
        if self.s3_key:
            return self.s3_key
        return f"uploads/{self.ldihk_id}/hosted-smoke-youtube-takeout.zip"

    def resolved_wrong_ldihk_id(self) -> str:
        if self.wrong_ldihk_id:
            return self.wrong_ldihk_id
        return f"{self.ldihk_id}-wrong"


@dataclass
class HostedSmokeReport:
    base_url: str
    ldihk_id: str
    s3_bucket: str
    s3_key: str
    imports: list[dict[str, object]] = field(default_factory=list)
    event_count_rows: list[dict[str, object]] = field(default_factory=list)
    event_count_total: int = 0
    event_count_after_rerun: int = 0
    estimated_watch_seconds: int = 0
    duration_quality: dict[str, int] = field(default_factory=dict)
    uploaded_fixture_bytes: int | None = None
    support_commands: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "base_url": self.base_url,
            "ldihk_id": self.ldihk_id,
            "s3_bucket": self.s3_bucket,
            "s3_key": self.s3_key,
            "imports": self.imports,
            "event_count_rows": self.event_count_rows,
            "event_count_total": self.event_count_total,
            "event_count_after_rerun": self.event_count_after_rerun,
            "estimated_watch_seconds": self.estimated_watch_seconds,
            "duration_quality": self.duration_quality,
            "uploaded_fixture_bytes": self.uploaded_fixture_bytes,
            "support_commands": self.support_commands,
        }


class UrllibJsonHttpClient:
    def __init__(self, base_url: str, *, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: object | None = None,
        bearer_token: str | None = None,
    ) -> HttpResponse:
        url = urljoin(self.base_url, path.lstrip("/"))
        headers = {"Accept": "application/json"}
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if bearer_token is not None:
            headers["Authorization"] = f"Bearer {bearer_token}"

        request = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = _decode_response_body(response.read())
                return HttpResponse(status_code=response.status, body=body)
        except HTTPError as error:
            return HttpResponse(
                status_code=error.code,
                body=_decode_response_body(error.read()),
            )
        except URLError as error:
            raise SmokeFailure(
                f"{method.upper()} {path} request failed: {error.reason}"
            ) from error


class Boto3S3Uploader:
    def __init__(self, client=None) -> None:
        if client is None:
            try:
                import boto3
            except ModuleNotFoundError as error:  # pragma: no cover - env-dependent
                raise RuntimeError(
                    "boto3 is required for --upload-fixture; install dependencies "
                    "or provide an existing --s3-key"
                ) from error
            client = boto3.client("s3")
        self._client = client

    def upload_zip(self, bucket: str, key: str, body: bytes) -> None:
        self._client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/zip",
        )


def run_hosted_smoke(
    config: HostedSmokeConfig,
    *,
    http_client: JsonHttpClient | None = None,
    s3_uploader: S3Uploader | None = None,
    command_runner: CommandRunner | None = None,
    sleep_fn: SleepFn = time.sleep,
    emit: EmitFn | None = print,
) -> HostedSmokeReport:
    _validate_config(config)
    s3_key = config.resolved_s3_key()
    http_client = http_client or UrllibJsonHttpClient(
        config.base_url,
        timeout_seconds=config.http_timeout_seconds,
    )
    command_runner = command_runner or _run_subprocess
    report = HostedSmokeReport(
        base_url=config.base_url.rstrip("/"),
        ldihk_id=config.ldihk_id,
        s3_bucket=config.s3_bucket,
        s3_key=s3_key,
    )

    _check_health(http_client)
    _emit(emit, "health ok")

    if config.run_migrations:
        _run_support_command(
            "migrations",
            [sys.executable, str(ROOT / "backend/scripts/run_migrations.py")],
            command_runner,
            report,
        )
        _emit(emit, "migrations ok")

    if config.upload_fixture:
        body = _fixture_zip_bytes(config.fixture_zip_path)
        try:
            uploader = s3_uploader or Boto3S3Uploader()
            uploader.upload_zip(config.s3_bucket, s3_key, body)
        except Exception as error:
            raise SmokeFailure(
                f"S3 upload failed for s3://{config.s3_bucket}/{s3_key}: {error}"
            ) from error
        report.uploaded_fixture_bytes = len(body)
        _emit(
            emit,
            f"uploaded fixture: s3://{config.s3_bucket}/{s3_key} "
            f"({len(body)} bytes)",
        )

    first_import = _create_import(http_client, config, s3_key)
    report.imports.append({"import_id": first_import, "phase": "initial"})
    _emit(emit, f"initial import queued: {first_import}")

    _assert_wrong_bearer_denied(http_client, config, first_import)
    _emit(emit, "wrong bearer denied import status")

    if config.run_import_worker_once:
        _run_support_command(
            "import worker",
            [sys.executable, str(ROOT / "backend/scripts/run_worker.py"), "--once"],
            command_runner,
            report,
        )
        _emit(emit, "import worker once ok")

    first_status = _wait_for_import(
        http_client,
        config,
        first_import,
        sleep_fn=sleep_fn,
    )
    report.imports[0].update(first_status)
    _emit(emit, _format_import_status("initial import completed", first_status))

    event_payload = _query_event_counts(http_client, config)
    report.event_count_rows = _rows(event_payload)
    report.event_count_total = _sum_metric(report.event_count_rows, "event_count")
    if report.event_count_total < config.expected_event_count:
        raise SmokeFailure(
            "POST /api/query event_count returned too few rows: "
            f"expected at least {config.expected_event_count}, "
            f"got {report.event_count_total}; rows={report.event_count_rows}"
        )
    _emit(emit, f"event counts ok: total_event_count={report.event_count_total}")

    if config.run_enrichment_worker_once:
        _run_support_command(
            "enrichment worker",
            [
                sys.executable,
                str(ROOT / "backend/scripts/run_enrichment_worker.py"),
                "--once",
            ],
            command_runner,
            report,
        )
        _emit(emit, "enrichment worker once ok")

    duration_payload = _wait_for_enrichment(
        http_client,
        config,
        sleep_fn=sleep_fn,
    )
    duration_rows = _rows(duration_payload)
    report.estimated_watch_seconds = _sum_metric(
        duration_rows,
        "estimated_watch_seconds",
    )
    report.duration_quality = _quality(duration_payload)
    _emit(
        emit,
        "duration query ok: "
        f"estimated_watch_seconds={report.estimated_watch_seconds}, "
        f"quality={report.duration_quality}",
    )

    second_import = _create_import(http_client, config, s3_key)
    report.imports.append({"import_id": second_import, "phase": "rerun"})
    _emit(emit, f"rerun import queued: {second_import}")

    if config.run_import_worker_once:
        _run_support_command(
            "import worker",
            [sys.executable, str(ROOT / "backend/scripts/run_worker.py"), "--once"],
            command_runner,
            report,
        )

    second_status = _wait_for_import(
        http_client,
        config,
        second_import,
        sleep_fn=sleep_fn,
    )
    report.imports[1].update(second_status)
    _emit(emit, _format_import_status("rerun import completed", second_status))

    rerun_payload = _query_event_counts(http_client, config)
    rerun_rows = _rows(rerun_payload)
    report.event_count_after_rerun = _sum_metric(rerun_rows, "event_count")
    if report.event_count_after_rerun != report.event_count_total:
        raise SmokeFailure(
            "Import rerun changed analytics event count: "
            f"before={report.event_count_total}, "
            f"after={report.event_count_after_rerun}; rows={rerun_rows}"
        )
    _emit(
        emit,
        "dedupe ok: "
        f"event_count_after_rerun={report.event_count_after_rerun}",
    )
    return report


def build_smoke_fixture_zip() -> bytes:
    buffer = io.BytesIO()
    records = [
        {
            "header": "YouTube",
            "title": "Watched hosted smoke fixture video",
            "titleUrl": f"https://www.youtube.com/watch?v={SMOKE_VIDEO_ID}",
            "time": "2026-06-06T08:53:12Z",
            "subtitles": [
                {
                    "name": "Hosted smoke fixture channel",
                    "url": f"https://www.youtube.com/channel/{SMOKE_CHANNEL_ID}",
                }
            ],
        }
    ]
    with ZipFile(buffer, "w", ZIP_DEFLATED) as zip_file:
        zip_file.writestr(
            "Takeout/YouTube and YouTube Music/history/watch-history.json",
            json.dumps(records, separators=(",", ":")).encode("utf-8"),
        )
    return buffer.getvalue()


def _validate_config(config: HostedSmokeConfig) -> None:
    if not config.base_url.strip():
        raise SmokeFailure("BACKEND_BASE_URL or --base-url is required")
    if not config.ldihk_id.strip():
        raise SmokeFailure("SMOKE_LDIHK_ID or --ldihk-id is required")
    if not config.s3_bucket.strip():
        raise SmokeFailure("S3_BUCKET or --s3-bucket is required")
    if config.expected_event_count < 1:
        raise SmokeFailure("--expected-event-count must be positive")
    if config.expected_watch_count < 1:
        raise SmokeFailure("--expected-watch-count must be positive")
    if config.import_timeout_seconds <= 0:
        raise SmokeFailure("--import-timeout-seconds must be positive")
    if config.enrichment_timeout_seconds <= 0:
        raise SmokeFailure("--enrichment-timeout-seconds must be positive")
    if config.poll_interval_seconds < 0:
        raise SmokeFailure("--poll-interval-seconds cannot be negative")


def _check_health(http_client: JsonHttpClient) -> None:
    response = http_client.request("GET", "/health")
    if response.status_code != 200:
        raise SmokeFailure(
            f"GET /health returned HTTP {response.status_code}: {response.body}"
        )
    body = _json_object(response.body, "GET /health")
    if body.get("status") != "ok":
        raise SmokeFailure(f"GET /health returned unexpected body: {body}")


def _create_import(
    http_client: JsonHttpClient,
    config: HostedSmokeConfig,
    s3_key: str,
) -> str:
    response = http_client.request(
        "POST",
        "/api/imports",
        json_body={
            "s3_bucket": config.s3_bucket,
            "s3_key": s3_key,
        },
        bearer_token=config.ldihk_id,
    )
    if response.status_code != 201:
        raise SmokeFailure(
            f"POST /api/imports returned HTTP {response.status_code}: "
            f"{response.body}"
        )
    body = _json_object(response.body, "POST /api/imports")
    import_id = body.get("import_id")
    if not isinstance(import_id, str) or not import_id:
        raise SmokeFailure(f"POST /api/imports did not return import_id: {body}")
    return import_id


def _assert_wrong_bearer_denied(
    http_client: JsonHttpClient,
    config: HostedSmokeConfig,
    import_id: str,
) -> None:
    wrong_token = config.resolved_wrong_ldihk_id()
    response = http_client.request(
        "GET",
        f"/api/imports/{import_id}",
        bearer_token=wrong_token,
    )
    if response.status_code != 404:
        raise SmokeFailure(
            "Wrong bearer could read another import status: "
            f"GET /api/imports/{import_id} returned HTTP "
            f"{response.status_code}: {response.body}"
        )


def _wait_for_import(
    http_client: JsonHttpClient,
    config: HostedSmokeConfig,
    import_id: str,
    *,
    sleep_fn: SleepFn,
) -> dict[str, object]:
    deadline = time.monotonic() + config.import_timeout_seconds
    last_body: object = None
    while True:
        response = http_client.request(
            "GET",
            f"/api/imports/{import_id}",
            bearer_token=config.ldihk_id,
        )
        if response.status_code != 200:
            raise SmokeFailure(
                f"GET /api/imports/{import_id} returned HTTP "
                f"{response.status_code}: {response.body}"
            )
        body = _json_object(response.body, f"GET /api/imports/{import_id}")
        last_body = body
        status = body.get("status")
        if status == "completed":
            return body
        if status == "failed":
            raise SmokeFailure(
                f"Import {import_id} failed: "
                f"{body.get('error_message') or body}"
            )
        if time.monotonic() >= deadline:
            raise SmokeFailure(
                f"Timed out waiting for import {import_id}; last status={last_body}"
            )
        sleep_fn(config.poll_interval_seconds)


def _query_event_counts(
    http_client: JsonHttpClient,
    config: HostedSmokeConfig,
) -> dict[str, object]:
    return _query(
        http_client,
        config,
        {
            "dataset": "youtube_usage",
            "metrics": ["event_count"],
            "dimensions": ["event_type"],
            "filters": {},
            "options": {
                "limit": 25,
                "sort_by": "event_count",
                "sort_direction": "desc",
            },
        },
        label="event_count",
    )


def _wait_for_enrichment(
    http_client: JsonHttpClient,
    config: HostedSmokeConfig,
    *,
    sleep_fn: SleepFn,
) -> dict[str, object]:
    deadline = time.monotonic() + config.enrichment_timeout_seconds
    while True:
        payload = _query(
            http_client,
            config,
            {
                "dataset": "youtube_usage",
                "metrics": ["estimated_watch_seconds"],
                "dimensions": [],
                "filters": {"event_type": "watch"},
                "options": {"limit": 1},
            },
            label="estimated_watch_seconds",
        )
        quality = _quality(payload)
        rows = _rows(payload)
        estimated_seconds = _sum_metric(rows, "estimated_watch_seconds")
        if quality.get("events_counted", 0) >= config.expected_watch_count:
            if not config.require_api_duration:
                if estimated_seconds > 0:
                    return payload
            elif (
                quality.get("events_with_api_duration", 0)
                >= config.expected_watch_count
            ):
                return payload

        if time.monotonic() >= deadline:
            raise SmokeFailure(
                "Timed out waiting for duration enrichment; "
                f"require_api_duration={config.require_api_duration}, "
                f"last_quality={quality}, rows={rows}"
            )
        sleep_fn(config.poll_interval_seconds)


def _query(
    http_client: JsonHttpClient,
    config: HostedSmokeConfig,
    payload: Mapping[str, object],
    *,
    label: str,
) -> dict[str, object]:
    response = http_client.request(
        "POST",
        "/api/query",
        json_body=dict(payload),
        bearer_token=config.ldihk_id,
    )
    if response.status_code != 200:
        raise SmokeFailure(
            f"POST /api/query ({label}) returned HTTP "
            f"{response.status_code}: {response.body}"
        )
    return _json_object(response.body, f"POST /api/query ({label})")


def _fixture_zip_bytes(fixture_zip_path: Path | None) -> bytes:
    if fixture_zip_path is None:
        return build_smoke_fixture_zip()
    return fixture_zip_path.read_bytes()


def _run_support_command(
    label: str,
    command: Sequence[str],
    command_runner: CommandRunner,
    report: HostedSmokeReport,
) -> None:
    completed = command_runner(command)
    report.support_commands.append(label)
    if completed.returncode != 0:
        output = (completed.stderr or completed.stdout or "").strip()
        if not output:
            output = f"exit code {completed.returncode}"
        raise SmokeFailure(f"{label} command failed: {output}")


def _run_subprocess(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _decode_response_body(raw_body: bytes) -> object:
    if not raw_body:
        return None
    text = raw_body.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _json_object(body: object, label: str) -> dict[str, object]:
    if isinstance(body, dict):
        return dict(body)
    raise SmokeFailure(f"{label} did not return a JSON object: {body}")


def _rows(payload: Mapping[str, object]) -> list[dict[str, object]]:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise SmokeFailure(f"Query response missing rows: {payload}")
    normalized: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise SmokeFailure(f"Query response row is not an object: {row}")
        normalized.append(dict(row))
    return normalized


def _quality(payload: Mapping[str, object]) -> dict[str, int]:
    quality = payload.get("quality")
    if not isinstance(quality, dict):
        raise SmokeFailure(f"Query response missing quality: {payload}")
    return {
        str(key): int(value or 0)
        for key, value in quality.items()
        if isinstance(value, (int, float))
    }


def _sum_metric(rows: list[dict[str, object]], metric: str) -> int:
    total = 0
    for row in rows:
        value = row.get(metric)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        total += int(value)
    return total


def _format_import_status(prefix: str, status: Mapping[str, object]) -> str:
    return (
        f"{prefix}: import_id={status.get('import_id')}, "
        f"records_imported={status.get('records_imported')}, "
        f"records_seen={status.get('records_seen')}, "
        f"warnings_count={status.get('warnings_count')}"
    )


def _emit(emit: EmitFn | None, message: str) -> None:
    if emit is not None:
        emit(f"[smoke] {message}")


def _env_float(name: str, default: float) -> float:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    return float(raw_value)


def _env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    return int(raw_value)


def _parse_args(argv: Sequence[str]) -> HostedSmokeConfig:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Run a hosted end-to-end YouTube Takeout backend smoke test."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BACKEND_BASE_URL", ""),
        help="Hosted backend base URL. Defaults to BACKEND_BASE_URL.",
    )
    parser.add_argument(
        "--ldihk-id",
        default=os.environ.get("SMOKE_LDIHK_ID", f"smoke-{uuid.uuid4().hex[:12]}"),
        help="Bearer identity to use. Defaults to SMOKE_LDIHK_ID or a unique id.",
    )
    parser.add_argument(
        "--wrong-ldihk-id",
        default=os.environ.get("SMOKE_WRONG_LDIHK_ID"),
        help="Different bearer identity for the ownership negative check.",
    )
    parser.add_argument(
        "--s3-bucket",
        default=os.environ.get("S3_BUCKET", ""),
        help="S3 bucket containing the smoke ZIP. Defaults to S3_BUCKET.",
    )
    parser.add_argument(
        "--s3-key",
        default=os.environ.get("SMOKE_S3_KEY"),
        help=(
            "S3 key for the smoke ZIP. Defaults to "
            "uploads/<ldihk-id>/hosted-smoke-youtube-takeout.zip."
        ),
    )
    parser.add_argument(
        "--fixture-zip",
        type=Path,
        help="Optional ZIP to upload instead of the built-in tiny fixture.",
    )
    parser.add_argument(
        "--upload-fixture",
        action="store_true",
        help="Upload the built-in or provided fixture ZIP to S3 before queueing.",
    )
    parser.add_argument(
        "--run-migrations",
        action="store_true",
        help="Run backend/scripts/run_migrations.py before the smoke flow.",
    )
    parser.add_argument(
        "--run-import-worker-once",
        action="store_true",
        help="Run backend/scripts/run_worker.py --once after each queued import.",
    )
    parser.add_argument(
        "--run-enrichment-worker-once",
        action="store_true",
        help="Run backend/scripts/run_enrichment_worker.py --once after import.",
    )
    parser.add_argument(
        "--accept-duration-fallback",
        action="store_true",
        help=(
            "Pass if estimated_watch_seconds is positive even when the query "
            "does not show API-backed duration."
        ),
    )
    parser.add_argument(
        "--expected-event-count",
        type=int,
        default=_env_int("SMOKE_EXPECTED_EVENT_COUNT", 1),
    )
    parser.add_argument(
        "--expected-watch-count",
        type=int,
        default=_env_int("SMOKE_EXPECTED_WATCH_COUNT", 1),
    )
    parser.add_argument(
        "--import-timeout-seconds",
        type=float,
        default=_env_float(
            "SMOKE_IMPORT_TIMEOUT_SECONDS",
            DEFAULT_IMPORT_TIMEOUT_SECONDS,
        ),
    )
    parser.add_argument(
        "--enrichment-timeout-seconds",
        type=float,
        default=_env_float(
            "SMOKE_ENRICHMENT_TIMEOUT_SECONDS",
            DEFAULT_ENRICHMENT_TIMEOUT_SECONDS,
        ),
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=_env_float(
            "SMOKE_POLL_INTERVAL_SECONDS",
            DEFAULT_POLL_INTERVAL_SECONDS,
        ),
    )
    parser.add_argument(
        "--http-timeout-seconds",
        type=float,
        default=_env_float(
            "SMOKE_HTTP_TIMEOUT_SECONDS",
            DEFAULT_HTTP_TIMEOUT_SECONDS,
        ),
    )
    args = parser.parse_args(argv)
    return HostedSmokeConfig(
        base_url=args.base_url,
        ldihk_id=args.ldihk_id,
        s3_bucket=args.s3_bucket,
        s3_key=args.s3_key,
        wrong_ldihk_id=args.wrong_ldihk_id,
        fixture_zip_path=args.fixture_zip,
        upload_fixture=args.upload_fixture,
        run_migrations=args.run_migrations,
        run_import_worker_once=args.run_import_worker_once,
        run_enrichment_worker_once=args.run_enrichment_worker_once,
        expected_event_count=args.expected_event_count,
        expected_watch_count=args.expected_watch_count,
        require_api_duration=not args.accept_duration_fallback,
        import_timeout_seconds=args.import_timeout_seconds,
        enrichment_timeout_seconds=args.enrichment_timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
        http_timeout_seconds=args.http_timeout_seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        report = run_hosted_smoke(_parse_args(argv))
    except SmokeFailure as error:
        print(f"[smoke] failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "passed", **report.to_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
