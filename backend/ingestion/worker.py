from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, ContextManager, Protocol
from uuid import uuid4
from zipfile import ZipFile

from backend.ingestion.dispatch import DispatchResult, dispatch_member_path
from backend.ingestion.fingerprints import event_fingerprint
from backend.ingestion.models import ParseResult, ParserCallable
from backend.ingestion.s3 import S3Client
from backend.ingestion.zip_safety import iter_safe_zip_members


IMPORT_STATUS_IDLE = "idle"
IMPORT_STATUS_COMPLETED = "completed"
IMPORT_STATUS_FAILED = "failed"
SOURCE_FILE_STATUS_RUNNING = "running"
SOURCE_FILE_STATUS_COMPLETED = "completed"
SOURCE_FILE_STATUS_FAILED = "failed"
DEFAULT_MAX_IMPORT_ZIP_BYTES = 1073741824


@dataclass(frozen=True)
class ImportJob:
    id: str
    user_id: str
    s3_bucket: str
    s3_key: str
    s3_etag: str | None = None


@dataclass
class ImportProcessingSummary:
    records_seen: int = 0
    records_imported: int = 0
    warnings_count: int = 0
    source_files: int = 0
    failed_source_file: FailedSourceFileWrite | None = None


@dataclass(frozen=True)
class WorkerRunResult:
    import_id: str | None
    status: str
    records_seen: int = 0
    records_imported: int = 0
    warnings_count: int = 0
    source_files: int = 0
    error_message: str | None = None


@dataclass(frozen=True)
class UsageEventWrite:
    id: str
    user_id: str
    import_id: str
    source_file_id: str
    platform: str
    product: str
    event_type: str
    occurred_at: datetime | None
    video_id: str | None
    channel_id: str | None
    title_hash: str | None
    search_query_hash: str | None
    raw_status: str | None
    event_fingerprint: str


@dataclass(frozen=True)
class SubscriptionWrite:
    id: str
    user_id: str
    import_id: str
    channel_id: str
    channel_url: str | None
    channel_title_hash: str | None
    source_path: str


@dataclass(frozen=True)
class ImportWarningWrite:
    id: str
    import_id: str
    source_file_id: str
    code: str
    count: int
    sample_hash: str | None


@dataclass(frozen=True)
class FailedSourceFileWrite:
    import_id: str
    path: str
    sha256: str
    parser_name: str
    records_seen: int
    warnings_count: int


class ImportRepository(Protocol):
    def claim_queued_import(self) -> ImportJob | None:
        ...

    def import_persistence_transaction(self) -> ContextManager[None]:
        ...

    def record_source_file(
        self,
        *,
        import_id: str,
        path: str,
        sha256: str,
        parser_name: str,
        status: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> str:
        ...

    def update_source_file_status(
        self,
        *,
        source_file_id: str,
        status: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        ...

    def insert_usage_event(self, event: UsageEventWrite) -> bool:
        ...

    def upsert_subscription(self, subscription: SubscriptionWrite) -> bool:
        ...

    def insert_import_warning(self, warning: ImportWarningWrite) -> None:
        ...

    def update_import_counts(
        self,
        *,
        import_id: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        ...

    def mark_import_completed(
        self,
        *,
        import_id: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        ...

    def mark_import_failed(
        self,
        *,
        import_id: str,
        error_message: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        ...


ParserLoader = Callable[[DispatchResult], ParserCallable]
DispatchMember = Callable[[str], DispatchResult]


class S3ZipImportWorker:
    def __init__(
        self,
        *,
        repository: ImportRepository,
        s3_client: S3Client,
        dispatch_member: DispatchMember = dispatch_member_path,
        parser_loader: ParserLoader | None = None,
        max_zip_bytes: int | None = None,
    ) -> None:
        self.repository = repository
        self.s3_client = s3_client
        self.dispatch_member = dispatch_member
        self.parser_loader = parser_loader or _load_parser
        self.max_zip_bytes = (
            _max_import_zip_bytes_from_environment()
            if max_zip_bytes is None
            else max_zip_bytes
        )
        if self.max_zip_bytes <= 0:
            raise ValueError("MAX_IMPORT_ZIP_BYTES must be greater than zero")

    def process_one(self) -> WorkerRunResult:
        job = self.repository.claim_queued_import()
        if job is None:
            return WorkerRunResult(import_id=None, status=IMPORT_STATUS_IDLE)

        summary = ImportProcessingSummary()
        try:
            self._process_claimed_job(job, summary)
        except Exception as error:
            error_message = _error_message(error)
            failure_summary = _failure_summary(summary)
            if summary.failed_source_file is not None:
                self._record_failed_source_file(summary.failed_source_file)
            self.repository.mark_import_failed(
                import_id=job.id,
                error_message=error_message,
                records_seen=failure_summary.records_seen,
                records_imported=failure_summary.records_imported,
                warnings_count=failure_summary.warnings_count,
            )
            return WorkerRunResult(
                import_id=job.id,
                status=IMPORT_STATUS_FAILED,
                records_seen=failure_summary.records_seen,
                records_imported=failure_summary.records_imported,
                warnings_count=failure_summary.warnings_count,
                source_files=failure_summary.source_files,
                error_message=error_message,
            )
        return WorkerRunResult(
            import_id=job.id,
            status=IMPORT_STATUS_COMPLETED,
            records_seen=summary.records_seen,
            records_imported=summary.records_imported,
            warnings_count=summary.warnings_count,
            source_files=summary.source_files,
        )

    def _process_claimed_job(
        self,
        job: ImportJob,
        summary: ImportProcessingSummary,
    ) -> None:
        self._assert_s3_object_within_size_limit(job)
        with TemporaryDirectory(prefix=f"import-{job.id}-") as tmpdir:
            zip_path = Path(tmpdir) / "takeout.zip"
            self.s3_client.download_zip(job.s3_bucket, job.s3_key, zip_path)

            with ZipFile(zip_path) as zip_file:
                safe_members = list(iter_safe_zip_members(zip_file))
                for member in safe_members:
                    dispatch = self.dispatch_member(member.source_path)
                    if dispatch.ignored:
                        continue

                    content = zip_file.read(member.zip_info)
                    content_sha256 = hashlib.sha256(content).hexdigest()
                    parser_name = dispatch.parser_name or "unknown"
                    parser = self.parser_loader(dispatch)
                    try:
                        parse_result = parser(
                            content,
                            source_path=member.source_path,
                        )
                    except Exception:
                        summary.failed_source_file = FailedSourceFileWrite(
                            import_id=job.id,
                            path=member.source_path,
                            sha256=content_sha256,
                            parser_name=parser_name,
                            records_seen=0,
                            warnings_count=0,
                        )
                        raise

                    file_warnings_count = len(parse_result.warnings)
                    try:
                        with self.repository.import_persistence_transaction():
                            next_records_seen = (
                                summary.records_seen + parse_result.records_seen
                            )
                            source_file_id = self.repository.record_source_file(
                                import_id=job.id,
                                path=member.source_path,
                                sha256=content_sha256,
                                parser_name=parser_name,
                                status=SOURCE_FILE_STATUS_RUNNING,
                                records_seen=parse_result.records_seen,
                                records_imported=0,
                                warnings_count=file_warnings_count,
                            )
                            file_records_imported = self._persist_parse_result(
                                job=job,
                                source_file_id=source_file_id,
                                source_path=member.source_path,
                                parse_result=parse_result,
                            )
                            next_records_imported = (
                                summary.records_imported + file_records_imported
                            )
                            next_warnings_count = (
                                summary.warnings_count + file_warnings_count
                            )

                            self.repository.update_source_file_status(
                                source_file_id=source_file_id,
                                status=SOURCE_FILE_STATUS_COMPLETED,
                                records_seen=parse_result.records_seen,
                                records_imported=file_records_imported,
                                warnings_count=file_warnings_count,
                            )

                            self.repository.update_import_counts(
                                import_id=job.id,
                                records_seen=next_records_seen,
                                records_imported=next_records_imported,
                                warnings_count=next_warnings_count,
                            )
                    except Exception:
                        summary.failed_source_file = FailedSourceFileWrite(
                            import_id=job.id,
                            path=member.source_path,
                            sha256=content_sha256,
                            parser_name=parser_name,
                            records_seen=parse_result.records_seen,
                            warnings_count=file_warnings_count,
                        )
                        raise

                    summary.source_files += 1
                    summary.records_seen = next_records_seen
                    summary.records_imported = next_records_imported
                    summary.warnings_count = next_warnings_count

            self.repository.mark_import_completed(
                import_id=job.id,
                records_seen=summary.records_seen,
                records_imported=summary.records_imported,
                warnings_count=summary.warnings_count,
            )

    def _assert_s3_object_within_size_limit(self, job: ImportJob) -> None:
        metadata = self.s3_client.head_object(job.s3_bucket, job.s3_key)
        if metadata.content_length > self.max_zip_bytes:
            raise ValueError(
                "S3 object size "
                f"{metadata.content_length} bytes exceeds "
                f"MAX_IMPORT_ZIP_BYTES={self.max_zip_bytes}"
            )

    def _record_failed_source_file(
        self,
        failed_source_file: FailedSourceFileWrite,
    ) -> None:
        self.repository.record_source_file(
            import_id=failed_source_file.import_id,
            path=failed_source_file.path,
            sha256=failed_source_file.sha256,
            parser_name=failed_source_file.parser_name,
            status=SOURCE_FILE_STATUS_FAILED,
            records_seen=failed_source_file.records_seen,
            records_imported=0,
            warnings_count=failed_source_file.warnings_count,
        )

    def _persist_parse_result(
        self,
        *,
        job: ImportJob,
        source_file_id: str,
        source_path: str,
        parse_result: ParseResult,
    ) -> int:
        records_imported = 0
        for event in parse_result.events:
            inserted = self.repository.insert_usage_event(
                UsageEventWrite(
                    id=str(uuid4()),
                    user_id=job.user_id,
                    import_id=job.id,
                    source_file_id=source_file_id,
                    platform="youtube",
                    product=event.product,
                    event_type=event.event_type,
                    occurred_at=event.occurred_at,
                    video_id=event.video_id,
                    channel_id=event.channel_id,
                    title_hash=_privacy_hash(event.title),
                    search_query_hash=_privacy_hash(event.search_query),
                    raw_status=event.raw_status,
                    event_fingerprint=event_fingerprint(
                        event,
                        user_id=job.user_id,
                        source_path=source_path,
                    ),
                )
            )
            if inserted:
                records_imported += 1

        for subscription in parse_result.subscriptions:
            upserted = self.repository.upsert_subscription(
                SubscriptionWrite(
                    id=str(uuid4()),
                    user_id=job.user_id,
                    import_id=job.id,
                    channel_id=subscription.channel_id,
                    channel_url=subscription.channel_url,
                    channel_title_hash=_privacy_hash(subscription.channel_title),
                    source_path=source_path,
                )
            )
            if upserted:
                records_imported += 1

        for (code, sample_hash), count in _warning_counts(parse_result).items():
            self.repository.insert_import_warning(
                ImportWarningWrite(
                    id=str(uuid4()),
                    import_id=job.id,
                    source_file_id=source_file_id,
                    code=code,
                    count=count,
                    sample_hash=sample_hash,
                )
            )

        return records_imported


class PostgresImportRepository:
    def __init__(self, connection) -> None:
        self.connection = connection
        self._transaction_depth = 0

    @contextmanager
    def import_persistence_transaction(self):
        outermost = self._transaction_depth == 0
        self._transaction_depth += 1
        try:
            yield
        except Exception:
            if outermost:
                self.connection.rollback()
            raise
        else:
            if outermost:
                self.connection.commit()
        finally:
            self._transaction_depth -= 1

    def claim_queued_import(self) -> ImportJob | None:
        try:
            row = self.connection.execute(
                """
                SELECT id, user_id, s3_bucket, s3_key, s3_etag
                FROM imports
                WHERE status = 'queued'
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                self.connection.commit()
                return None

            import_id = row[0]
            self.connection.execute(
                """
                UPDATE imports
                SET status = 'running',
                    started_at = now(),
                    finished_at = NULL,
                    error_message = NULL
                WHERE id = %s
                """,
                (import_id,),
            )
            self.connection.commit()
            return ImportJob(
                id=str(row[0]),
                user_id=str(row[1]),
                s3_bucket=row[2],
                s3_key=row[3],
                s3_etag=row[4],
            )
        except Exception:
            self.connection.rollback()
            raise

    def record_source_file(
        self,
        *,
        import_id: str,
        path: str,
        sha256: str,
        parser_name: str,
        status: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> str:
        source_file_id = uuid4()
        try:
            row = self.connection.execute(
                """
                INSERT INTO source_files (
                    id,
                    import_id,
                    path,
                    sha256,
                    parser_name,
                    status,
                    records_seen,
                    records_imported,
                    warnings_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (import_id, path)
                DO UPDATE SET
                    sha256 = EXCLUDED.sha256,
                    parser_name = EXCLUDED.parser_name,
                    status = EXCLUDED.status,
                    records_seen = EXCLUDED.records_seen,
                    records_imported = EXCLUDED.records_imported,
                    warnings_count = EXCLUDED.warnings_count
                RETURNING id
                """,
                (
                    source_file_id,
                    import_id,
                    path,
                    sha256,
                    parser_name,
                    status,
                    records_seen,
                    records_imported,
                    warnings_count,
                ),
            ).fetchone()
            self._commit_unless_in_transaction()
            return str(row[0])
        except Exception:
            self._rollback_unless_in_transaction()
            raise

    def update_source_file_status(
        self,
        *,
        source_file_id: str,
        status: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        try:
            self.connection.execute(
                """
                UPDATE source_files
                SET status = %s,
                    records_seen = %s,
                    records_imported = %s,
                    warnings_count = %s
                WHERE id = %s
                """,
                (
                    status,
                    records_seen,
                    records_imported,
                    warnings_count,
                    source_file_id,
                ),
            )
            self._commit_unless_in_transaction()
        except Exception:
            self._rollback_unless_in_transaction()
            raise

    def insert_usage_event(self, event: UsageEventWrite) -> bool:
        try:
            row = self.connection.execute(
                """
                INSERT INTO usage_events (
                    id,
                    user_id,
                    import_id,
                    source_file_id,
                    platform,
                    product,
                    event_type,
                    occurred_at,
                    video_id,
                    channel_id,
                    title_hash,
                    search_query_hash,
                    raw_status,
                    event_fingerprint
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, event_fingerprint) DO NOTHING
                RETURNING id
                """,
                (
                    event.id,
                    event.user_id,
                    event.import_id,
                    event.source_file_id,
                    event.platform,
                    event.product,
                    event.event_type,
                    event.occurred_at,
                    event.video_id,
                    event.channel_id,
                    event.title_hash,
                    event.search_query_hash,
                    event.raw_status,
                    event.event_fingerprint,
                ),
            ).fetchone()
            self._commit_unless_in_transaction()
            return row is not None
        except Exception:
            self._rollback_unless_in_transaction()
            raise

    def upsert_subscription(self, subscription: SubscriptionWrite) -> bool:
        try:
            row = self.connection.execute(
                """
                INSERT INTO subscriptions (
                    id,
                    user_id,
                    import_id,
                    channel_id,
                    channel_url,
                    channel_title_hash,
                    source_path
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, channel_id)
                DO UPDATE SET
                    import_id = EXCLUDED.import_id,
                    channel_url = EXCLUDED.channel_url,
                    channel_title_hash = EXCLUDED.channel_title_hash,
                    source_path = EXCLUDED.source_path
                RETURNING id
                """,
                (
                    subscription.id,
                    subscription.user_id,
                    subscription.import_id,
                    subscription.channel_id,
                    subscription.channel_url,
                    subscription.channel_title_hash,
                    subscription.source_path,
                ),
            ).fetchone()
            self._commit_unless_in_transaction()
            return row is not None
        except Exception:
            self._rollback_unless_in_transaction()
            raise

    def insert_import_warning(self, warning: ImportWarningWrite) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO import_warnings (
                    id,
                    import_id,
                    source_file_id,
                    code,
                    count,
                    sample_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    warning.id,
                    warning.import_id,
                    warning.source_file_id,
                    warning.code,
                    warning.count,
                    warning.sample_hash,
                ),
            )
            self._commit_unless_in_transaction()
        except Exception:
            self._rollback_unless_in_transaction()
            raise

    def update_import_counts(
        self,
        *,
        import_id: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        self._update_import_counts(
            import_id=import_id,
            records_seen=records_seen,
            records_imported=records_imported,
            warnings_count=warnings_count,
        )

    def mark_import_completed(
        self,
        *,
        import_id: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        try:
            self.connection.execute(
                """
                UPDATE imports
                SET status = 'completed',
                    finished_at = now(),
                    records_seen = %s,
                    records_imported = %s,
                    warnings_count = %s,
                    error_message = NULL
                WHERE id = %s
                """,
                (records_seen, records_imported, warnings_count, import_id),
            )
            self._commit_unless_in_transaction()
        except Exception:
            self._rollback_unless_in_transaction()
            raise

    def mark_import_failed(
        self,
        *,
        import_id: str,
        error_message: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        try:
            self.connection.execute(
                """
                UPDATE imports
                SET status = 'failed',
                    finished_at = now(),
                    records_seen = %s,
                    records_imported = %s,
                    warnings_count = %s,
                    error_message = %s
                WHERE id = %s
                """,
                (
                    records_seen,
                    records_imported,
                    warnings_count,
                    error_message[:1000],
                    import_id,
                ),
            )
            self._commit_unless_in_transaction()
        except Exception:
            self._rollback_unless_in_transaction()
            raise

    def _update_import_counts(
        self,
        *,
        import_id: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        try:
            self.connection.execute(
                """
                UPDATE imports
                SET records_seen = %s,
                    records_imported = %s,
                    warnings_count = %s
                WHERE id = %s
                """,
                (records_seen, records_imported, warnings_count, import_id),
            )
            self._commit_unless_in_transaction()
        except Exception:
            self._rollback_unless_in_transaction()
            raise

    def _commit_unless_in_transaction(self) -> None:
        if self._transaction_depth == 0:
            self.connection.commit()

    def _rollback_unless_in_transaction(self) -> None:
        if self._transaction_depth == 0:
            self.connection.rollback()


def _load_parser(dispatch: DispatchResult) -> ParserCallable:
    return dispatch.load_parser()


def _failure_summary(summary: ImportProcessingSummary) -> ImportProcessingSummary:
    if summary.failed_source_file is None:
        return ImportProcessingSummary(
            records_seen=summary.records_seen,
            records_imported=summary.records_imported,
            warnings_count=summary.warnings_count,
            source_files=summary.source_files,
        )
    return ImportProcessingSummary(
        records_seen=summary.records_seen,
        records_imported=summary.records_imported,
        warnings_count=summary.warnings_count,
        source_files=summary.source_files + 1,
        failed_source_file=summary.failed_source_file,
    )


def _privacy_hash(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _warning_counts(parse_result: ParseResult) -> Counter[tuple[str, str | None]]:
    return Counter(
        (warning.code, _privacy_hash(warning.sample))
        for warning in parse_result.warnings
    )


def _error_message(error: Exception) -> str:
    message = str(error).strip()
    if message:
        return message[:1000]
    return error.__class__.__name__


def _max_import_zip_bytes_from_environment() -> int:
    raw_value = os.environ.get("MAX_IMPORT_ZIP_BYTES", "").strip()
    if not raw_value:
        return DEFAULT_MAX_IMPORT_ZIP_BYTES
    try:
        return int(raw_value)
    except ValueError as error:
        raise ValueError("MAX_IMPORT_ZIP_BYTES must be an integer") from error
