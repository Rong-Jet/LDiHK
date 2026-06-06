from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from backend.ingestion.dispatch import DispatchResult
from backend.ingestion.fingerprints import event_fingerprint
from backend.ingestion.models import (
    ParseResult,
    ParseWarning,
    ParsedEvent,
    ParsedSubscription,
)
from backend.ingestion.s3 import S3ObjectMetadata
from backend.ingestion.worker import (
    IMPORT_STATUS_COMPLETED,
    IMPORT_STATUS_FAILED,
    ImportWarningWrite,
    ImportJob,
    PostgresImportRepository,
    S3ZipImportWorker,
    SOURCE_FILE_STATUS_COMPLETED,
    SOURCE_FILE_STATUS_FAILED,
    SubscriptionWrite,
    UsageEventWrite,
)


@dataclass
class FakeSourceFile:
    id: str
    import_id: str
    path: str
    sha256: str
    parser_name: str
    status: str
    records_seen: int
    records_imported: int
    warnings_count: int


class FakeImportRepository:
    def __init__(
        self,
        job: ImportJob | None,
        *,
        event_insert_results: list[bool] | None = None,
        subscription_upsert_results: list[bool] | None = None,
        fail_on_import_warning: bool = False,
    ) -> None:
        self.job = job
        self.status = "queued" if job is not None else None
        self.status_history: list[str] = []
        self.source_files: list[FakeSourceFile] = []
        self.usage_events: list[UsageEventWrite] = []
        self.subscriptions: list[SubscriptionWrite] = []
        self.import_warnings: list[ImportWarningWrite] = []
        self.event_insert_results = event_insert_results or []
        self.subscription_upsert_results = subscription_upsert_results or []
        self.fail_on_import_warning = fail_on_import_warning
        self.records_seen = 0
        self.records_imported = 0
        self.warnings_count = 0
        self.count_history: list[tuple[int, int, int]] = []
        self.error_message: str | None = None

    def claim_queued_import(self) -> ImportJob | None:
        if self.job is None or self.status != "queued":
            return None
        self.status = "running"
        self.status_history.append("running")
        return self.job

    @contextmanager
    def import_persistence_transaction(self):
        snapshot = deepcopy(
            (
                self.status,
                self.status_history,
                self.source_files,
                self.usage_events,
                self.subscriptions,
                self.import_warnings,
                self.event_insert_results,
                self.subscription_upsert_results,
                self.records_seen,
                self.records_imported,
                self.warnings_count,
            )
        )
        try:
            yield
        except Exception:
            (
                self.status,
                self.status_history,
                self.source_files,
                self.usage_events,
                self.subscriptions,
                self.import_warnings,
                self.event_insert_results,
                self.subscription_upsert_results,
                self.records_seen,
                self.records_imported,
                self.warnings_count,
            ) = snapshot
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
        source_file_id = f"source-{len(self.source_files) + 1}"
        self.source_files.append(
            FakeSourceFile(
                id=source_file_id,
                import_id=import_id,
                path=path,
                sha256=sha256,
                parser_name=parser_name,
                status=status,
                records_seen=records_seen,
                records_imported=records_imported,
                warnings_count=warnings_count,
            )
        )
        return source_file_id

    def update_source_file_status(
        self,
        *,
        source_file_id: str,
        status: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        for source_file in self.source_files:
            if source_file.id == source_file_id:
                source_file.status = status
                source_file.records_seen = records_seen
                source_file.records_imported = records_imported
                source_file.warnings_count = warnings_count
                return
        raise AssertionError(f"unknown source file id: {source_file_id}")

    def insert_usage_event(self, event: UsageEventWrite) -> bool:
        self.usage_events.append(event)
        if self.event_insert_results:
            return self.event_insert_results.pop(0)
        return True

    def upsert_subscription(self, subscription: SubscriptionWrite) -> bool:
        self.subscriptions.append(subscription)
        if self.subscription_upsert_results:
            return self.subscription_upsert_results.pop(0)
        return True

    def insert_import_warning(self, warning: ImportWarningWrite) -> None:
        if self.fail_on_import_warning:
            raise RuntimeError("warning insert failed")
        self.import_warnings.append(warning)

    def update_import_counts(
        self,
        *,
        import_id: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        self.records_seen = records_seen
        self.records_imported = records_imported
        self.warnings_count = warnings_count
        self.count_history.append((records_seen, records_imported, warnings_count))

    def mark_import_completed(
        self,
        *,
        import_id: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        self.status = "completed"
        self.status_history.append("completed")
        self.records_seen = records_seen
        self.records_imported = records_imported
        self.warnings_count = warnings_count

    def mark_import_failed(
        self,
        *,
        import_id: str,
        error_message: str,
        records_seen: int,
        records_imported: int,
        warnings_count: int,
    ) -> None:
        self.status = "failed"
        self.status_history.append("failed")
        self.error_message = error_message
        self.records_seen = records_seen
        self.records_imported = records_imported
        self.warnings_count = warnings_count


class FakeS3Client:
    def __init__(self, zip_path: Path, *, object_size: int | None = None) -> None:
        self.zip_path = zip_path
        self.object_size = (
            zip_path.stat().st_size if object_size is None else object_size
        )
        self.heads: list[tuple[str, str]] = []
        self.downloads: list[tuple[str, str, Path]] = []

    def head_object(self, bucket: str, key: str) -> S3ObjectMetadata:
        self.heads.append((bucket, key))
        return S3ObjectMetadata(content_length=self.object_size)

    def download_zip(self, bucket: str, key: str, destination: Path) -> None:
        self.downloads.append((bucket, key, destination))
        destination.write_bytes(self.zip_path.read_bytes())


class S3ZipWorkerTests(unittest.TestCase):
    def test_processes_one_queued_import_to_completed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_zip = Path(tmpdir) / "takeout.zip"
            write_zip(
                source_zip,
                {
                    "Takeout/YouTube and YouTube Music/history/watch-history.html": b"one\ntwo",
                    "Takeout/ignored.txt": b"ignore me",
                },
            )
            job = ImportJob(
                id="import-1",
                user_id="user-1",
                s3_bucket="existing-bucket",
                s3_key="uploads/user-1/takeout.zip",
                s3_etag="etag-1",
            )
            repository = FakeImportRepository(job)
            s3_client = FakeS3Client(source_zip)
            worker = S3ZipImportWorker(
                repository=repository,
                s3_client=s3_client,
                dispatch_member=fake_dispatch_member,
                parser_loader=lambda dispatch: successful_parser,
            )

            result = worker.process_one()

        self.assertEqual(result.status, IMPORT_STATUS_COMPLETED)
        self.assertEqual(repository.status_history, ["running", "completed"])
        self.assertEqual(
            s3_client.heads,
            [("existing-bucket", "uploads/user-1/takeout.zip")],
        )
        self.assertEqual(
            s3_client.downloads[0][:2],
            ("existing-bucket", "uploads/user-1/takeout.zip"),
        )
        downloaded_path = s3_client.downloads[0][2]
        self.assertFalse(downloaded_path.exists())
        self.assertEqual(repository.records_seen, 2)
        self.assertEqual(repository.records_imported, 1)
        self.assertEqual(repository.warnings_count, 1)
        self.assertEqual(len(repository.source_files), 1)
        source_file = repository.source_files[0]
        self.assertEqual(
            source_file.path,
            "Takeout/YouTube and YouTube Music/history/watch-history.html",
        )
        self.assertEqual(source_file.parser_name, "fake_watch_history")
        self.assertEqual(source_file.status, SOURCE_FILE_STATUS_COMPLETED)
        self.assertEqual(source_file.sha256, hashlib.sha256(b"one\ntwo").hexdigest())
        self.assertEqual(source_file.records_imported, 1)

    def test_persists_parser_output_with_hashed_private_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_zip = Path(tmpdir) / "takeout.zip"
            source_path = "watch-history.html"
            write_zip(source_zip, {source_path: b"history"})
            job = ImportJob(
                id="import-4",
                user_id="user-1",
                s3_bucket="bucket",
                s3_key="uploads/user-1/takeout.zip",
            )
            repository = FakeImportRepository(job)
            worker = S3ZipImportWorker(
                repository=repository,
                s3_client=FakeS3Client(source_zip),
                dispatch_member=fake_dispatch_member,
                parser_loader=lambda dispatch: parser_with_private_fields,
            )

            result = worker.process_one()

        expected_event = private_event()
        self.assertEqual(result.status, IMPORT_STATUS_COMPLETED)
        self.assertEqual(repository.records_imported, 2)
        self.assertEqual(len(repository.usage_events), 1)
        self.assertEqual(len(repository.subscriptions), 1)
        self.assertEqual(len(repository.import_warnings), 1)

        usage_event = repository.usage_events[0]
        self.assertEqual(usage_event.user_id, "user-1")
        self.assertEqual(usage_event.import_id, "import-4")
        self.assertEqual(usage_event.source_file_id, "source-1")
        self.assertEqual(usage_event.platform, "youtube")
        self.assertEqual(usage_event.product, "youtube")
        self.assertEqual(usage_event.event_type, "watch")
        self.assertEqual(usage_event.video_id, "video-1")
        self.assertEqual(usage_event.channel_id, "channel-1")
        self.assertEqual(usage_event.raw_status, "ok")
        self.assertEqual(usage_event.title_hash, privacy_hash("Private Title"))
        self.assertEqual(usage_event.search_query_hash, privacy_hash("Private Query"))
        self.assertEqual(
            usage_event.event_fingerprint,
            event_fingerprint(
                expected_event,
                user_id="user-1",
                source_path=source_path,
            ),
        )

        subscription = repository.subscriptions[0]
        self.assertEqual(subscription.user_id, "user-1")
        self.assertEqual(subscription.import_id, "import-4")
        self.assertEqual(subscription.channel_id, "channel-1")
        self.assertEqual(
            subscription.channel_url,
            "https://youtube.com/channel/channel-1",
        )
        self.assertEqual(
            subscription.channel_title_hash,
            privacy_hash("Private Channel"),
        )
        self.assertEqual(subscription.source_path, source_path)

        warning = repository.import_warnings[0]
        self.assertEqual(warning.import_id, "import-4")
        self.assertEqual(warning.source_file_id, "source-1")
        self.assertEqual(warning.code, "private_warning")
        self.assertEqual(warning.count, 1)
        self.assertEqual(warning.sample_hash, privacy_hash("Private warning sample"))

        serialized_writes = repr(
            (
                repository.usage_events,
                repository.subscriptions,
                repository.import_warnings,
            )
        )
        self.assertNotIn("Private Title", serialized_writes)
        self.assertNotIn("Private Query", serialized_writes)
        self.assertNotIn("Private Channel", serialized_writes)
        self.assertNotIn("Private warning sample", serialized_writes)

    def test_imported_counts_use_actual_persistence_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_zip = Path(tmpdir) / "takeout.zip"
            write_zip(source_zip, {"watch-history.html": b"history"})
            repository = FakeImportRepository(
                ImportJob(
                    id="import-5",
                    user_id="user-1",
                    s3_bucket="bucket",
                    s3_key="uploads/user-1/takeout.zip",
                ),
                event_insert_results=[False],
                subscription_upsert_results=[True],
            )
            worker = S3ZipImportWorker(
                repository=repository,
                s3_client=FakeS3Client(source_zip),
                dispatch_member=fake_dispatch_member,
                parser_loader=lambda dispatch: parser_with_private_fields,
            )

            result = worker.process_one()

        self.assertEqual(result.records_imported, 1)
        self.assertEqual(repository.records_imported, 1)
        self.assertEqual(repository.source_files[0].records_imported, 1)

    def test_duplicate_event_fingerprints_do_not_increase_imported_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_zip = Path(tmpdir) / "takeout.zip"
            write_zip(source_zip, {"watch-history.html": b"history"})
            repository = FakeImportRepository(
                ImportJob(
                    id="import-duplicate",
                    user_id="user-1",
                    s3_bucket="bucket",
                    s3_key="uploads/user-1/takeout.zip",
                ),
                event_insert_results=[False],
            )
            worker = S3ZipImportWorker(
                repository=repository,
                s3_client=FakeS3Client(source_zip),
                dispatch_member=fake_dispatch_member,
                parser_loader=lambda dispatch: successful_parser,
            )

            result = worker.process_one()

        self.assertEqual(result.status, IMPORT_STATUS_COMPLETED)
        self.assertEqual(repository.records_seen, 2)
        self.assertEqual(repository.records_imported, 0)
        self.assertEqual(repository.source_files[0].records_imported, 0)

    def test_later_write_failure_rolls_back_partial_parser_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_zip = Path(tmpdir) / "takeout.zip"
            write_zip(source_zip, {"watch-history.html": b"history"})
            repository = FakeImportRepository(
                ImportJob(
                    id="import-7",
                    user_id="user-1",
                    s3_bucket="bucket",
                    s3_key="uploads/user-1/takeout.zip",
                ),
                fail_on_import_warning=True,
            )
            worker = S3ZipImportWorker(
                repository=repository,
                s3_client=FakeS3Client(source_zip),
                dispatch_member=fake_dispatch_member,
                parser_loader=lambda dispatch: parser_with_private_fields,
            )

            result = worker.process_one()

        self.assertEqual(result.status, IMPORT_STATUS_FAILED)
        self.assertIn("warning insert failed", repository.error_message)
        self.assertEqual(repository.usage_events, [])
        self.assertEqual(repository.subscriptions, [])
        self.assertEqual(repository.import_warnings, [])
        self.assertEqual(repository.records_imported, 0)
        self.assertEqual(len(repository.source_files), 1)
        self.assertEqual(repository.source_files[0].status, SOURCE_FILE_STATUS_FAILED)
        self.assertEqual(repository.source_files[0].path, "watch-history.html")

    def test_rejects_s3_object_larger_than_configured_limit_before_download(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_zip = Path(tmpdir) / "takeout.zip"
            write_zip(source_zip, {"watch-history.html": b"history"})
            repository = FakeImportRepository(
                ImportJob(
                    id="import-oversized",
                    user_id="user-1",
                    s3_bucket="bucket",
                    s3_key="uploads/user-1/takeout.zip",
                )
            )
            s3_client = FakeS3Client(source_zip, object_size=11)
            worker = S3ZipImportWorker(
                repository=repository,
                s3_client=s3_client,
                dispatch_member=fake_dispatch_member,
                parser_loader=lambda dispatch: successful_parser,
                max_zip_bytes=10,
            )

            result = worker.process_one()

        self.assertEqual(result.status, IMPORT_STATUS_FAILED)
        self.assertEqual(repository.status_history, ["running", "failed"])
        self.assertIn("exceeds MAX_IMPORT_ZIP_BYTES", repository.error_message)
        self.assertEqual(s3_client.heads, [("bucket", "uploads/user-1/takeout.zip")])
        self.assertEqual(s3_client.downloads, [])
        self.assertEqual(repository.source_files, [])

    def test_later_source_file_failure_preserves_prior_source_file_commit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_zip = Path(tmpdir) / "takeout.zip"
            write_zip(
                source_zip,
                {
                    "first/watch-history.html": b"first",
                    "second/watch-history.html": b"second",
                },
            )
            repository = FakeImportRepository(
                ImportJob(
                    id="import-8",
                    user_id="user-1",
                    s3_bucket="bucket",
                    s3_key="uploads/user-1/takeout.zip",
                )
            )
            worker = S3ZipImportWorker(
                repository=repository,
                s3_client=FakeS3Client(source_zip),
                dispatch_member=fake_dispatch_member,
                parser_loader=lambda dispatch: fail_second_source_parser,
            )

            result = worker.process_one()

        self.assertEqual(result.status, IMPORT_STATUS_FAILED)
        self.assertIn("second source failed", repository.error_message)
        self.assertEqual(len(repository.usage_events), 1)
        self.assertEqual(len(repository.subscriptions), 1)
        self.assertEqual(len(repository.import_warnings), 1)
        self.assertEqual(repository.records_seen, 3)
        self.assertEqual(repository.records_imported, 2)
        self.assertEqual(repository.warnings_count, 1)
        self.assertEqual(repository.count_history, [(3, 2, 1)])
        self.assertEqual(len(repository.source_files), 2)
        self.assertEqual(repository.source_files[0].path, "first/watch-history.html")
        self.assertEqual(repository.source_files[0].status, SOURCE_FILE_STATUS_COMPLETED)
        self.assertEqual(repository.source_files[1].path, "second/watch-history.html")
        self.assertEqual(repository.source_files[1].status, SOURCE_FILE_STATUS_FAILED)

    def test_parser_warnings_are_aggregated_by_code_and_sample_hash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_zip = Path(tmpdir) / "takeout.zip"
            write_zip(source_zip, {"watch-history.html": b"history"})
            repository = FakeImportRepository(
                ImportJob(
                    id="import-6",
                    user_id="user-1",
                    s3_bucket="bucket",
                    s3_key="uploads/user-1/takeout.zip",
                )
            )
            worker = S3ZipImportWorker(
                repository=repository,
                s3_client=FakeS3Client(source_zip),
                dispatch_member=fake_dispatch_member,
                parser_loader=lambda dispatch: parser_with_duplicate_warnings,
            )

            result = worker.process_one()

        self.assertEqual(result.warnings_count, 2)
        self.assertEqual(len(repository.import_warnings), 1)
        self.assertEqual(repository.import_warnings[0].code, "duplicate_warning")
        self.assertEqual(repository.import_warnings[0].count, 2)
        self.assertEqual(
            repository.import_warnings[0].sample_hash,
            privacy_hash("same private sample"),
        )

    def test_rejects_zip_path_traversal_and_marks_import_failed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_zip = Path(tmpdir) / "takeout.zip"
            write_zip(source_zip, {"../evil.txt": b"evil"})
            repository = FakeImportRepository(
                ImportJob(
                    id="import-2",
                    user_id="user-1",
                    s3_bucket="bucket",
                    s3_key="uploads/user-1/takeout.zip",
                )
            )
            worker = S3ZipImportWorker(
                repository=repository,
                s3_client=FakeS3Client(source_zip),
                dispatch_member=fake_dispatch_member,
                parser_loader=lambda dispatch: successful_parser,
            )

            result = worker.process_one()

        self.assertEqual(result.status, IMPORT_STATUS_FAILED)
        self.assertEqual(repository.status_history, ["running", "failed"])
        self.assertIn("traversal", repository.error_message)
        self.assertEqual(repository.source_files, [])

    def test_rejects_late_zip_path_traversal_before_persisting_safe_members(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_zip = Path(tmpdir) / "takeout.zip"
            write_zip(
                source_zip,
                {
                    "watch-history.html": b"history",
                    "../evil.txt": b"evil",
                },
            )
            repository = FakeImportRepository(
                ImportJob(
                    id="import-late-traversal",
                    user_id="user-1",
                    s3_bucket="bucket",
                    s3_key="uploads/user-1/takeout.zip",
                )
            )
            worker = S3ZipImportWorker(
                repository=repository,
                s3_client=FakeS3Client(source_zip),
                dispatch_member=fake_dispatch_member,
                parser_loader=lambda dispatch: successful_parser,
            )

            result = worker.process_one()

        self.assertEqual(result.status, IMPORT_STATUS_FAILED)
        self.assertIn("traversal", repository.error_message)
        self.assertEqual(repository.source_files, [])
        self.assertEqual(repository.usage_events, [])
        self.assertEqual(repository.records_imported, 0)

    def test_parser_errors_mark_import_and_source_file_failed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_zip = Path(tmpdir) / "takeout.zip"
            write_zip(source_zip, {"watch-history.html": b"history"})
            repository = FakeImportRepository(
                ImportJob(
                    id="import-3",
                    user_id="user-1",
                    s3_bucket="bucket",
                    s3_key="uploads/user-1/takeout.zip",
                )
            )
            worker = S3ZipImportWorker(
                repository=repository,
                s3_client=FakeS3Client(source_zip),
                dispatch_member=fake_dispatch_member,
                parser_loader=lambda dispatch: failing_parser,
            )

            result = worker.process_one()

        self.assertEqual(result.status, IMPORT_STATUS_FAILED)
        self.assertIn("parser failed", repository.error_message)
        self.assertEqual(len(repository.source_files), 1)
        self.assertEqual(repository.source_files[0].status, SOURCE_FILE_STATUS_FAILED)


class PostgresImportRepositoryTransactionTests(unittest.TestCase):
    def test_persistence_writes_commit_once_at_import_transaction_boundary(self):
        connection = CommitCountingConnection()
        repository = PostgresImportRepository(connection)

        with repository.import_persistence_transaction():
            repository.insert_usage_event(fake_usage_event_write())
            repository.upsert_subscription(fake_subscription_write())
            repository.insert_import_warning(fake_import_warning_write())
            repository.mark_import_completed(
                import_id="import-1",
                records_seen=3,
                records_imported=2,
                warnings_count=1,
            )
            self.assertEqual(connection.commits, 0)

        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)

    def test_import_transaction_rolls_back_uncommitted_persistence_writes(self):
        connection = CommitCountingConnection()
        repository = PostgresImportRepository(connection)

        with self.assertRaises(RuntimeError):
            with repository.import_persistence_transaction():
                repository.insert_usage_event(fake_usage_event_write())
                raise RuntimeError("later source failed")

        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)


class CommitCountingConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.statements: list[str] = []

    def execute(self, sql: str, params=None):
        self.statements.append(sql)
        return FakeCursor(("row-1",))

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeCursor:
    def __init__(self, row: tuple[str]) -> None:
        self.row = row

    def fetchone(self):
        return self.row


def fake_dispatch_member(source_path: str) -> DispatchResult:
    if source_path.endswith("watch-history.html"):
        return DispatchResult(
            source_path=source_path,
            parser_name="fake_watch_history",
            callable_path="fake:parse",
            ignored=False,
        )
    return DispatchResult(
        source_path=source_path,
        parser_name=None,
        callable_path=None,
        ignored=True,
        reason="no_parser",
    )


def successful_parser(content: bytes, *, source_path: str) -> ParseResult:
    return ParseResult(
        events=[
            ParsedEvent(
                event_type="watched",
                product="youtube",
                occurred_at=None,
            )
        ],
        subscriptions=[],
        warnings=[ParseWarning(code="sample_warning")],
        records_seen=2,
    )


def parser_with_private_fields(content: bytes, *, source_path: str) -> ParseResult:
    return ParseResult(
        events=[private_event()],
        subscriptions=[
            ParsedSubscription(
                channel_id="channel-1",
                channel_url="https://youtube.com/channel/channel-1",
                channel_title="Private Channel",
            )
        ],
        warnings=[ParseWarning(code="private_warning", sample="Private warning sample")],
        records_seen=3,
    )


def parser_with_duplicate_warnings(content: bytes, *, source_path: str) -> ParseResult:
    return ParseResult(
        events=[],
        subscriptions=[],
        warnings=[
            ParseWarning(code="duplicate_warning", sample="same private sample"),
            ParseWarning(code="duplicate_warning", sample="same private sample"),
        ],
        records_seen=2,
    )


def fail_second_source_parser(content: bytes, *, source_path: str) -> ParseResult:
    if source_path.startswith("second/"):
        raise RuntimeError("second source failed")
    return parser_with_private_fields(content, source_path=source_path)


def private_event() -> ParsedEvent:
    return ParsedEvent(
        event_type="watch",
        product="youtube",
        occurred_at=datetime(2026, 6, 6, 8, 53, tzinfo=timezone.utc),
        video_id="video-1",
        channel_id="channel-1",
        title="Private Title",
        search_query="Private Query",
        raw_status="ok",
    )


def failing_parser(content: bytes, *, source_path: str) -> ParseResult:
    raise RuntimeError("parser failed")


def fake_usage_event_write() -> UsageEventWrite:
    return UsageEventWrite(
        id="event-1",
        user_id="user-1",
        import_id="import-1",
        source_file_id="source-1",
        platform="youtube",
        product="youtube",
        event_type="watch",
        occurred_at=None,
        video_id=None,
        channel_id=None,
        title_hash=None,
        search_query_hash=None,
        raw_status=None,
        event_fingerprint="fingerprint-1",
    )


def fake_subscription_write() -> SubscriptionWrite:
    return SubscriptionWrite(
        id="subscription-1",
        user_id="user-1",
        import_id="import-1",
        channel_id="channel-1",
        channel_url=None,
        channel_title_hash=None,
        source_path="watch-history.html",
    )


def fake_import_warning_write() -> ImportWarningWrite:
    return ImportWarningWrite(
        id="warning-1",
        import_id="import-1",
        source_file_id="source-1",
        code="warning",
        count=1,
        sample_hash=None,
    )


def privacy_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_zip(zip_path: Path, files: dict[str, bytes]) -> None:
    with ZipFile(zip_path, "w") as zip_file:
        for path, content in files.items():
            zip_file.writestr(path, content)


if __name__ == "__main__":
    unittest.main()
