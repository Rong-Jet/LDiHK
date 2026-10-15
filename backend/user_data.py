"""Erase everything stored about one LDiHK user ("Delete My Data").

Used by DELETE /api/me. Database rows go in one transaction; uploaded
objects under uploads/<LDiHKID>/ are removed afterwards on a best-effort
basis (the bucket's 1-day lifecycle rule removes leftovers anyway). The
shared YouTube video cache (durations, availability) is not personal data
and stays.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Mapping

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeletionSummary:
    events_deleted: int
    imports_deleted: int
    subscriptions_deleted: int


def delete_user_data(connection, *, ldihk_id: str) -> DeletionSummary | None:
    """Delete a real (non-synthetic) user and all their rows; None if unknown."""
    try:
        row = connection.execute(
            """
            SELECT id
            FROM users
            WHERE external_id = %s
              AND is_synthetic = false
            FOR UPDATE
            """,
            (ldihk_id,),
        ).fetchone()
        if row is None:
            connection.rollback()
            return None
        user_id = row[0]
        user_imports = "SELECT id FROM imports WHERE user_id = %s"

        connection.execute(
            f"""
            DELETE FROM enrichment_jobs
            WHERE payload_json ->> 'import_id' IN (
                SELECT id::text FROM ({user_imports}) user_imports
            )
            """,
            (user_id,),
        )
        connection.execute(
            f"DELETE FROM import_warnings WHERE import_id IN ({user_imports})",
            (user_id,),
        )
        events = connection.execute(
            "DELETE FROM usage_events WHERE user_id = %s", (user_id,)
        ).rowcount
        subscriptions = connection.execute(
            "DELETE FROM subscriptions WHERE user_id = %s", (user_id,)
        ).rowcount
        connection.execute(
            f"DELETE FROM source_files WHERE import_id IN ({user_imports})",
            (user_id,),
        )
        imports = connection.execute(
            "DELETE FROM imports WHERE user_id = %s", (user_id,)
        ).rowcount
        connection.execute("DELETE FROM users WHERE id = %s", (user_id,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return DeletionSummary(
        events_deleted=max(events, 0),
        imports_deleted=max(imports, 0),
        subscriptions_deleted=max(subscriptions, 0),
    )


def delete_user_uploads(
    ldihk_id: str,
    *,
    s3_client=None,
    environ: Mapping[str, str] = os.environ,
) -> int | None:
    """Delete objects under uploads/<LDiHKID>/; returns the count or None."""
    bucket = environ.get("S3_BUCKET", "").strip()
    if not bucket:
        return None
    try:
        if s3_client is None:
            from backend.ingestion.s3 import create_boto3_s3_client

            s3_client = create_boto3_s3_client(environ)
        deleted = 0
        prefix = f"uploads/{ldihk_id}/"
        continuation: dict[str, str] = {}
        while True:
            page = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix, **continuation)
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if keys:
                s3_client.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True})
                deleted += len(keys)
            if not page.get("IsTruncated"):
                return deleted
            continuation = {"ContinuationToken": page["NextContinuationToken"]}
    except Exception:
        LOGGER.warning("Could not delete uploads for a deleted user", exc_info=True)
        return None
