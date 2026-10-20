from __future__ import annotations

from datetime import datetime, timezone
import os
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from backend.app import create_app
from backend.uploads import Reservation, UploadRefused, UploadSettings, presign_upload, reserve_upload, upload_key_for


def auth_headers(ldihk_id: str = "ldihk-upload-test-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {ldihk_id}"}


class NoDatabase:
    """The validation tests must refuse before touching the database."""

    def __call__(self):
        raise AssertionError("the database must not be used")


def _app():
    return create_app(
        query_connection_factory=NoDatabase(),
        start_workers=False,
        enable_local_file_routes=False,
    )


class UploadRequestValidationTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(
            os.environ,
            {"S3_BUCKET": "ldihk-uploads", "RATE_LIMITS_ENABLED": "false", "UPLOADS_ENABLED": "true"},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = _app().test_client()

    def post(self, body, headers=None):
        return self.client.post("/api/uploads", headers=auth_headers() if headers is None else headers, json=body)

    def test_requires_a_bearer_id(self):
        response = self.post({"filename": "a.zip", "size": 10}, headers={})

        self.assertEqual(response.status_code, 401)

    def test_refuses_invalid_requests_before_touching_the_database(self):
        cases = [
            ({"filename": "a.rar", "size": 10}, 400, "invalid_filename"),
            ({"filename": "a.zip"}, 400, "invalid_size"),
            ({"filename": "a.zip", "size": 0}, 400, "invalid_size"),
            ({"filename": "a.zip", "size": True}, 400, "invalid_size"),
            ({"filename": "a.zip", "size": 10, "contentType": "text/html"}, 400, "invalid_content_type"),
            ({"filename": "a.zip", "size": 200 * 1024 * 1024 + 1}, 413, "file_too_large"),
        ]
        for body, status, code in cases:
            with self.subTest(body=body):
                response = self.post(body)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.get_json()["error"], code)

    def test_kill_switch_stops_all_uploads(self):
        with mock.patch.dict(os.environ, {"UPLOADS_ENABLED": "false"}):
            response = self.post({"filename": "a.zip", "size": 10})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "uploads_disabled")

    def test_body_identity_fields_are_rejected(self):
        response = self.post({"filename": "a.zip", "size": 10, "ldihk_id": "someone-else"})

        self.assertEqual(response.status_code, 400)


class PresignTests(unittest.TestCase):
    def test_url_is_single_use_and_bound_to_the_exact_size(self):
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url="https://account.r2.cloudflarestorage.com",
            region_name="auto",
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        reservation = Reservation(
            "ldihk-uploads", "uploads/ldihk-a/abc-export.zip", 12345, datetime(2026, 10, 18, tzinfo=timezone.utc)
        )

        target = presign_upload(client, reservation, ttl_seconds=120)

        query = parse_qs(urlsplit(target["url"]).query)
        self.assertEqual(query["X-Amz-SignedHeaders"], ["content-length;content-type;host;if-none-match"])
        self.assertEqual(query["X-Amz-Expires"], ["120"])
        self.assertEqual(target["headers"], {"Content-Type": "application/zip", "If-None-Match": "*"})
        self.assertEqual((target["s3Bucket"], target["s3Key"], target["method"]), ("ldihk-uploads", reservation.s3_key, "PUT"))


class UploadKeyTests(unittest.TestCase):
    def test_keys_are_unique_safe_and_under_the_user_prefix(self):
        first = upload_key_for("ldihk-a", "../../My Takeout (1).ZIP")
        second = upload_key_for("ldihk-a", "../../My Takeout (1).ZIP")

        self.assertNotEqual(first, second)
        for key in (first, second):
            self.assertTrue(key.startswith("uploads/ldihk-a/"))
            self.assertTrue(key.endswith("-My_Takeout_1.zip"), key)
            self.assertNotIn("..", key)
        self.assertTrue(upload_key_for("ldihk-a", None).endswith("-export.zip"))



class _BudgetConnection:
    """Answers the budget query with fixed numbers and records writes."""

    def __init__(self, database_bytes: int):
        self.database_bytes = database_bytes
        self.inserted = False
        self.rolled_back = False

    def execute(self, sql, parameters=None):
        if "INSERT INTO upload_reservations" in sql:
            self.inserted = True
            return mock.Mock(fetchone=lambda: (datetime.now(timezone.utc),))
        return mock.Mock(fetchone=lambda: (0, 0, 86400, self.database_bytes))

    def commit(self):
        pass

    def rollback(self):
        self.rolled_back = True


class DatabaseSizeGuardTests(unittest.TestCase):
    settings = UploadSettings(
        enabled=True, bucket="b", max_stored_bytes=10**9, max_per_month=100,
        url_ttl_seconds=120, max_zip_bytes=10**8, max_database_bytes=400 * 1024**2,
    )

    def test_refuses_uploads_when_the_database_is_nearly_full(self):
        connection = _BudgetConnection(database_bytes=401 * 1024**2)
        with self.assertRaises(UploadRefused) as caught:
            reserve_upload(connection, ldihk_id="ldihk-a", filename="a.zip", size_bytes=1000, settings=self.settings)
        self.assertEqual((caught.exception.status, caught.exception.code), (507, "database_full"))
        self.assertFalse(connection.inserted)

    def test_accepts_uploads_below_the_limit(self):
        connection = _BudgetConnection(database_bytes=100 * 1024**2)
        reserve_upload(connection, ldihk_id="ldihk-a", filename="a.zip", size_bytes=1000, settings=self.settings)
        self.assertTrue(connection.inserted)


if __name__ == "__main__":
    unittest.main()
