from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from flask import Blueprint, jsonify, request

from backend import db


QUEUED_STATUS = "queued"
_USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_S3_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


@dataclass(frozen=True)
class ImportJob:
    import_id: str
    user_id: str
    status: str
    records_seen: int
    records_imported: int
    warnings_count: int
    error_message: str | None
    created_at: datetime | str | None
    started_at: datetime | str | None
    finished_at: datetime | str | None


class ImportRepository(Protocol):
    def create_import(
        self,
        *,
        user_external_id: str,
        s3_bucket: str,
        s3_key: str,
        s3_etag: str | None,
    ) -> ImportJob:
        ...

    def get_import(self, import_id: str) -> ImportJob | None:
        ...


class PostgresImportRepository:
    def create_import(
        self,
        *,
        user_external_id: str,
        s3_bucket: str,
        s3_key: str,
        s3_etag: str | None,
    ) -> ImportJob:
        connection = db.connect()
        try:
            user_id = self._find_or_create_user(connection, user_external_id)
            import_id = uuid.uuid4()
            row = connection.execute(
                """
                INSERT INTO imports (
                    id,
                    user_id,
                    s3_bucket,
                    s3_key,
                    s3_etag,
                    status
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING
                    id,
                    status,
                    records_seen,
                    records_imported,
                    warnings_count,
                    error_message,
                    created_at,
                    started_at,
                    finished_at
                """,
                (
                    import_id,
                    user_id,
                    s3_bucket,
                    s3_key,
                    s3_etag,
                    QUEUED_STATUS,
                ),
            ).fetchone()
            connection.commit()
            return _job_from_import_row(row, user_external_id=user_external_id)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_import(self, import_id: str) -> ImportJob | None:
        try:
            import_uuid = uuid.UUID(import_id)
        except ValueError:
            return None

        connection = db.connect()
        try:
            row = connection.execute(
                """
                SELECT
                    imports.id,
                    users.external_id,
                    imports.status,
                    imports.records_seen,
                    imports.records_imported,
                    imports.warnings_count,
                    imports.error_message,
                    imports.created_at,
                    imports.started_at,
                    imports.finished_at
                FROM imports
                JOIN users ON users.id = imports.user_id
                WHERE imports.id = %s
                """,
                (import_uuid,),
            ).fetchone()
            connection.commit()
            if row is None:
                return None
            return _job_from_status_row(row)
        finally:
            connection.close()

    def _find_or_create_user(self, connection, external_id: str):
        row = connection.execute(
            """
            WITH inserted AS (
                INSERT INTO users (id, external_id)
                VALUES (%s, %s)
                ON CONFLICT (external_id) DO NOTHING
                RETURNING id
            )
            SELECT id FROM inserted
            UNION ALL
            SELECT id FROM users WHERE external_id = %s
            LIMIT 1
            """,
            (uuid.uuid4(), external_id, external_id),
        ).fetchone()
        return row[0]


def create_imports_blueprint(
    repository: ImportRepository | None = None,
) -> Blueprint:
    repository = PostgresImportRepository() if repository is None else repository
    blueprint = Blueprint("imports_api", __name__)

    @blueprint.post("/api/imports")
    def create_import():
        payload = request.get_json(silent=True)
        validated = _validate_create_payload(payload)
        if isinstance(validated, dict) and "errors" in validated:
            return _validation_error_response(validated["errors"])

        try:
            job = repository.create_import(
                user_external_id=validated.user_id,
                s3_bucket=validated.s3_bucket,
                s3_key=validated.s3_key,
                s3_etag=validated.s3_etag,
            )
        except db.DatabaseConfigError as error:
            return _database_unavailable_response(error)

        return jsonify({"import_id": job.import_id, "status": job.status}), 201

    @blueprint.get("/api/imports/<import_id>")
    def get_import(import_id: str):
        try:
            job = repository.get_import(import_id)
        except db.DatabaseConfigError as error:
            return _database_unavailable_response(error)

        if job is None:
            return jsonify({"error": "import_not_found"}), 404
        return jsonify(_status_payload(job))

    return blueprint


@dataclass(frozen=True)
class _CreateImportPayload:
    user_id: str
    s3_bucket: str
    s3_key: str
    s3_etag: str | None


def _validate_create_payload(
    payload: object,
) -> _CreateImportPayload | dict[str, dict[str, str]]:
    if not isinstance(payload, dict):
        return {"errors": {"body": "must_be_json_object"}}

    errors: dict[str, str] = {}
    user_id = _required_string(payload, "user_id", errors)
    s3_bucket = _required_string(payload, "s3_bucket", errors)
    s3_key = _required_string(payload, "s3_key", errors)
    s3_etag = _optional_string(payload, "s3_etag", errors)

    if user_id is not None and not _USER_ID_RE.fullmatch(user_id):
        errors["user_id"] = "invalid_user_id"
    if s3_bucket is not None and not _valid_s3_bucket(s3_bucket):
        errors["s3_bucket"] = "invalid_bucket"
    if s3_key is not None and user_id is not None:
        s3_key_error = _s3_key_error(s3_key, user_id)
        if s3_key_error is not None:
            errors["s3_key"] = s3_key_error

    if errors:
        return {"errors": errors}
    return _CreateImportPayload(
        user_id=user_id or "",
        s3_bucket=s3_bucket or "",
        s3_key=s3_key or "",
        s3_etag=s3_etag,
    )


def _required_string(
    payload: dict[object, object],
    field: str,
    errors: dict[str, str],
) -> str | None:
    value = payload.get(field)
    if value is None:
        errors[field] = "required"
        return None
    if not isinstance(value, str):
        errors[field] = "must_be_string"
        return None
    stripped = value.strip()
    if not stripped:
        errors[field] = "required"
        return None
    return stripped


def _optional_string(
    payload: dict[object, object],
    field: str,
    errors: dict[str, str],
) -> str | None:
    if field not in payload or payload[field] is None:
        return None
    value = payload[field]
    if not isinstance(value, str):
        errors[field] = "must_be_string"
        return None
    return value.strip() or None


def _valid_s3_bucket(bucket: str) -> bool:
    if not _S3_BUCKET_RE.fullmatch(bucket):
        return False
    if ".." in bucket or ".-" in bucket or "-." in bucket:
        return False
    return True


def _s3_key_error(s3_key: str, user_id: str) -> str | None:
    if _is_unsafe_s3_key(s3_key):
        return "unsafe_key"
    expected_prefix = f"uploads/{user_id}/"
    if not s3_key.startswith(expected_prefix):
        return "must_match_user_upload_prefix"
    if not s3_key.endswith(".zip"):
        return "must_be_zip"
    return None


def _is_unsafe_s3_key(s3_key: str) -> bool:
    if s3_key.startswith("/") or "\\" in s3_key:
        return True
    if any(ord(character) < 32 for character in s3_key):
        return True
    parts = s3_key.split("/")
    return any(part in {"", ".", ".."} for part in parts)


def _validation_error_response(errors: dict[str, str]):
    return jsonify({"error": "invalid_payload", "fields": errors}), 400


def _database_unavailable_response(error: Exception):
    return (
        jsonify(
            {
                "error": "database_unavailable",
                "message": str(error),
            }
        ),
        503,
    )


def _status_payload(job: ImportJob) -> dict[str, object]:
    return {
        "import_id": job.import_id,
        "user_id": job.user_id,
        "status": job.status,
        "records_seen": job.records_seen,
        "records_imported": job.records_imported,
        "warnings_count": job.warnings_count,
        "error_message": job.error_message,
        "created_at": _serialize_timestamp(job.created_at),
        "started_at": _serialize_timestamp(job.started_at),
        "finished_at": _serialize_timestamp(job.finished_at),
    }


def _serialize_timestamp(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _job_from_import_row(row, *, user_external_id: str) -> ImportJob:
    return ImportJob(
        import_id=str(row[0]),
        user_id=user_external_id,
        status=row[1],
        records_seen=row[2],
        records_imported=row[3],
        warnings_count=row[4],
        error_message=row[5],
        created_at=row[6],
        started_at=row[7],
        finished_at=row[8],
    )


def _job_from_status_row(row) -> ImportJob:
    return ImportJob(
        import_id=str(row[0]),
        user_id=row[1],
        status=row[2],
        records_seen=row[3],
        records_imported=row[4],
        warnings_count=row[5],
        error_message=row[6],
        created_at=row[7],
        started_at=row[8],
        finished_at=row[9],
    )
