"""Upload URLs within a hard budget that keeps storage inside its free tier.

Cloudflare R2 has no spending cap, so the backend is the only place that
issues upload URLs, and it refuses to issue more than the budgets allow. Each
URL is presigned for one exact size, starts an upload only within
UPLOAD_URL_TTL_SECONDS, and carries ``If-None-Match: *``: it can create its
object once and never overwrite or upload it again. Archives are deleted as
soon as their import ends (deletes are free on R2), and URLs that were never
used are cleaned up after they expire.

R2's free tier per month: 10 GB-month of storage (the average of each day's
peak), 1 million Class A operations (uploads, listings), 10 million Class B
operations (reads). The defaults stay far below it:

- UPLOAD_MAX_STORED_BYTES (2 GiB): archives that may exist at the same time.
- UPLOAD_MAX_PER_MONTH (10,000): upload URLs per calendar month (UTC).
- UPLOAD_URL_TTL_SECONDS (120): how long a URL can start an upload.
- UPLOADS_ENABLED=false: issue no upload URLs at all.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping

from flask import Blueprint, jsonify, request

from backend import db
from backend.http_boundary import (
    PublicBoundaryError,
    identity_field_error_response,
    identity_field_errors,
    public_boundary_error_response,
    require_bearer_identity,
)

LOGGER = logging.getLogger(__name__)

# Serialises budget checks across threads and processes (see db.py for the
# migration lock, which uses a neighbouring constant).
UPLOAD_BUDGET_LOCK_ID = 7_416_200_422
DEFAULT_MAX_STORED_BYTES = 2 * 1024**3
DEFAULT_MAX_PER_MONTH = 10_000
DEFAULT_URL_TTL_SECONDS = 120
DEFAULT_MAX_ZIP_BYTES = 200 * 1024 * 1024
CONTENT_TYPE = "application/zip"
# An upload may still be in flight after its URL expired (the browser gives up
# after 30 minutes), so unused URLs are only cleaned up after this.
UNUSED_UPLOAD_GRACE = timedelta(minutes=40)
SWEEP_BATCH = 50
# Monthly counting needs the current month only; older rows are purged.
RETAIN_DELETED_ROWS = timedelta(days=100)
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class UploadSettings:
    enabled: bool
    bucket: str | None
    max_stored_bytes: int
    max_per_month: int
    url_ttl_seconds: int
    max_zip_bytes: int

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> UploadSettings:
        enabled = environ.get("UPLOADS_ENABLED", "true").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        return cls(
            enabled=enabled,
            bucket=environ.get("S3_BUCKET", "").strip() or None,
            max_stored_bytes=_env_int(environ, "UPLOAD_MAX_STORED_BYTES", DEFAULT_MAX_STORED_BYTES),
            max_per_month=_env_int(environ, "UPLOAD_MAX_PER_MONTH", DEFAULT_MAX_PER_MONTH),
            url_ttl_seconds=_env_int(environ, "UPLOAD_URL_TTL_SECONDS", DEFAULT_URL_TTL_SECONDS),
            max_zip_bytes=_env_int(environ, "MAX_IMPORT_ZIP_BYTES", DEFAULT_MAX_ZIP_BYTES),
        )


class UploadRefused(Exception):
    """A request the budget or validation turns down (HTTP status + code)."""

    def __init__(self, status: int, code: str, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after

    def response(self):
        response = jsonify({"error": self.code, "message": self.message})
        response.status_code = self.status
        if self.retry_after is not None:
            response.headers["Retry-After"] = str(self.retry_after)
        return response


@dataclass(frozen=True)
class Reservation:
    s3_bucket: str
    s3_key: str
    size_bytes: int
    expires_at: datetime


def upload_key_for(ldihk_id: str, filename: object) -> str:
    """`uploads/<LDiHK-ID>/<random>-<name>.zip`: unique, so a URL never overwrites."""
    name = filename if isinstance(filename, str) and filename.strip() else "export.zip"
    stem = re.sub(r"\.zip$", "", name.strip(), flags=re.IGNORECASE)
    stem = _UNSAFE_NAME_CHARS.sub("_", stem).strip("._")[:80] or "export"
    return f"uploads/{ldihk_id}/{uuid.uuid4().hex[:16]}-{stem}.zip"


def reserve_upload(
    connection,
    *,
    ldihk_id: str,
    filename: object,
    size_bytes: int,
    settings: UploadSettings,
) -> Reservation:
    """Record an upload if the budgets allow it; raises UploadRefused otherwise."""
    if settings.bucket is None:
        raise UploadRefused(503, "upload_not_configured", "Upload storage is not configured.")
    try:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (UPLOAD_BUDGET_LOCK_ID,))
        stored_bytes, uploads_this_month, seconds_to_next_month = connection.execute(
            """
            SELECT
                (SELECT COALESCE(SUM(size_bytes), 0) FROM upload_reservations
                 WHERE deleted_at IS NULL),
                (SELECT count(*) FROM upload_reservations
                 WHERE created_at >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'),
                EXTRACT(EPOCH FROM (
                    (date_trunc('month', now() AT TIME ZONE 'UTC') + interval '1 month') AT TIME ZONE 'UTC'
                    - now()
                ))::int
            """
        ).fetchone()
        if uploads_this_month >= settings.max_per_month:
            raise UploadRefused(
                429,
                "upload_budget_exhausted",
                "This month's upload limit is reached; uploads open again on the 1st (UTC).",
                retry_after=max(60, int(seconds_to_next_month)),
            )
        if int(stored_bytes) + size_bytes > settings.max_stored_bytes:
            raise UploadRefused(
                429,
                "upload_storage_full",
                "Too many archives are waiting to be processed. Please try again in an hour.",
                retry_after=3600,
            )
        key = upload_key_for(ldihk_id, filename)
        expires_at = connection.execute(
            """
            INSERT INTO upload_reservations (id, ldihk_id, s3_bucket, s3_key, size_bytes, expires_at)
            VALUES (%s, %s, %s, %s, %s, now() + make_interval(secs => %s))
            RETURNING expires_at
            """,
            (uuid.uuid4(), ldihk_id, settings.bucket, key, size_bytes, settings.url_ttl_seconds),
        ).fetchone()[0]
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return Reservation(settings.bucket, key, size_bytes, expires_at)


def presign_upload(raw_s3_client, reservation: Reservation, *, ttl_seconds: int) -> dict[str, object]:
    """A PUT URL for exactly this size that can create the object only once."""
    headers = {"Content-Type": CONTENT_TYPE, "If-None-Match": "*"}
    url = raw_s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": reservation.s3_bucket,
            "Key": reservation.s3_key,
            "ContentType": CONTENT_TYPE,
            "ContentLength": reservation.size_bytes,
            "IfNoneMatch": "*",
        },
        ExpiresIn=ttl_seconds,
    )
    return {
        "url": url,
        "method": "PUT",
        # The browser sets Content-Length itself; it is signed and must match.
        "headers": headers,
        "s3Bucket": reservation.s3_bucket,
        "s3Key": reservation.s3_key,
        "expiresAt": reservation.expires_at.astimezone(timezone.utc).isoformat(),
        "isMock": False,
    }


def delete_uploads(connection, raw_s3_client, objects: list[tuple[str, str]]) -> int:
    """Delete (bucket, key) objects (free on R2) and mark their reservations; best effort."""
    deleted_keys: list[str] = []
    for bucket, key in objects:
        try:
            raw_s3_client.delete_object(Bucket=bucket, Key=key)
        except Exception:
            LOGGER.warning("Could not delete an uploaded archive", exc_info=True)
            continue
        deleted_keys.append(key)
    if deleted_keys:
        mark_uploads_deleted(connection, deleted_keys)
    return len(deleted_keys)


def mark_uploads_deleted(connection, keys: list[str]) -> None:
    connection.execute(
        "UPDATE upload_reservations SET deleted_at = now() WHERE s3_key = ANY(%s) AND deleted_at IS NULL",
        (keys,),
    )
    connection.commit()


def sweep_unused_uploads(connection, raw_s3_client, *, limit: int = SWEEP_BATCH) -> int:
    """Delete archives whose URL expired without an import still needing them."""
    rows = connection.execute(
        """
        SELECT r.s3_bucket, r.s3_key
        FROM upload_reservations r
        WHERE r.deleted_at IS NULL
          AND r.expires_at < now() - make_interval(secs => %s)
          AND NOT EXISTS (
              SELECT 1 FROM imports i
              WHERE i.s3_key = r.s3_key AND i.status IN ('queued', 'running')
          )
        ORDER BY r.expires_at
        LIMIT %s
        """,
        (UNUSED_UPLOAD_GRACE.total_seconds(), limit),
    ).fetchall()
    connection.commit()
    deleted = delete_uploads(connection, raw_s3_client, [(bucket, key) for bucket, key in rows])
    connection.execute(
        "DELETE FROM upload_reservations WHERE deleted_at IS NOT NULL AND created_at < now() - make_interval(secs => %s)",
        (RETAIN_DELETED_ROWS.total_seconds(),),
    )
    connection.commit()
    return deleted


def user_upload_objects(connection, ldihk_id: str) -> list[tuple[str, str]]:
    """Every (bucket, key) that may still hold this user's archives."""
    rows = connection.execute(
        """
        SELECT s3_bucket, s3_key FROM upload_reservations
        WHERE ldihk_id = %s AND deleted_at IS NULL
        UNION
        SELECT i.s3_bucket, i.s3_key FROM imports i
        JOIN users u ON u.id = i.user_id
        WHERE u.external_id = %s AND u.is_synthetic = false
        """,
        (ldihk_id, ldihk_id),
    ).fetchall()
    connection.commit()
    return [(bucket, key) for bucket, key in rows]


def forget_user_reservations(connection, ldihk_id: str) -> None:
    """Keep the rows for the budget counts, but without the user's ID."""
    connection.execute(
        "UPDATE upload_reservations SET ldihk_id = NULL WHERE ldihk_id = %s",
        (ldihk_id,),
    )
    connection.commit()


def create_uploads_blueprint(
    connection_factory: Callable[[], object],
    *,
    s3_client_factory: Callable[[], object] | None = None,
    environ: Mapping[str, str] = os.environ,
) -> Blueprint:
    blueprint = Blueprint("uploads_api", __name__)
    s3_clients: list[object] = []

    def raw_s3_client():
        if not s3_clients:
            if s3_client_factory is not None:
                s3_clients.append(s3_client_factory())
            else:
                from backend.ingestion.s3 import create_boto3_s3_client

                s3_clients.append(create_boto3_s3_client(environ))
        return s3_clients[0]

    @blueprint.post("/api/uploads")
    def create_upload():
        try:
            identity = require_bearer_identity()
        except PublicBoundaryError as error:
            return public_boundary_error_response(error)
        payload = request.get_json(silent=True)
        identity_errors = identity_field_errors(payload)
        if identity_errors:
            return identity_field_error_response(identity_errors)
        settings = UploadSettings.from_env(environ)
        try:
            size_bytes = _validated_request(payload, settings)
        except UploadRefused as refusal:
            return refusal.response()

        connection = None
        try:
            connection = connection_factory()
            try:
                sweep_unused_uploads(connection, raw_s3_client())
            except Exception:
                LOGGER.warning("Upload cleanup failed", exc_info=True)
                connection.rollback()
            reservation = reserve_upload(
                connection,
                ldihk_id=identity.ldihk_id,
                filename=payload.get("filename"),
                size_bytes=size_bytes,
                settings=settings,
            )
        except UploadRefused as refusal:
            return refusal.response()
        except db.DatabaseConfigError:
            return jsonify({"error": "database_unavailable"}), 503
        except Exception as error:
            if db.is_database_unavailable_error(error):
                LOGGER.warning("Database unavailable: %s", error)
                return jsonify({"error": "database_unavailable"}), 503
            raise
        finally:
            if connection is not None:
                connection.close()

        try:
            target = presign_upload(raw_s3_client(), reservation, ttl_seconds=settings.url_ttl_seconds)
        except Exception:
            # The reservation stays counted until the cleanup removes it.
            LOGGER.exception("Could not sign an upload URL")
            return jsonify({"error": "upload_signing_failed"}), 500
        return jsonify(target), 201

    return blueprint


def _validated_request(payload: object, settings: UploadSettings) -> int:
    if not settings.enabled:
        raise UploadRefused(503, "uploads_disabled", "Uploads are switched off at the moment.")
    if not isinstance(payload, dict):
        raise UploadRefused(400, "invalid_payload", "Expected a JSON object.")
    filename = payload.get("filename")
    if not isinstance(filename, str) or not filename.strip().lower().endswith(".zip"):
        raise UploadRefused(400, "invalid_filename", "Only .zip archives can be uploaded.")
    content_type = payload.get("contentType", CONTENT_TYPE)
    if content_type not in (CONTENT_TYPE, None):
        raise UploadRefused(400, "invalid_content_type", "Only application/zip uploads are supported.")
    size = payload.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise UploadRefused(400, "invalid_size", "The upload size is missing or invalid.")
    if size > settings.max_zip_bytes:
        limit_mb = settings.max_zip_bytes // (1024 * 1024)
        raise UploadRefused(413, "file_too_large", f"The archive is larger than {limit_mb} MB.")
    return size


def _env_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        LOGGER.warning("%s must be an integer; using %s", name, default)
        return default
    return value if value > 0 else default
