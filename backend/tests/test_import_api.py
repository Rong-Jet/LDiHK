from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.app import create_app
from backend.imports_api import ImportJob


def auth_headers(ldihk_id: str = "demo_user") -> dict[str, str]:
    return {"Authorization": f"Bearer {ldihk_id}"}


class InMemoryImportRepository:
    def __init__(self) -> None:
        self.imports: dict[str, ImportJob] = {}
        self.created_payloads: list[dict[str, str | None]] = []

    def create_import(
        self,
        *,
        user_external_id: str,
        s3_bucket: str,
        s3_key: str,
        s3_etag: str | None,
    ) -> ImportJob:
        import_id = f"import-{len(self.imports) + 1}"
        created_at = datetime(2026, 6, 6, 8, 0, tzinfo=timezone.utc)
        job = ImportJob(
            import_id=import_id,
            user_id=user_external_id,
            status="queued",
            records_seen=0,
            records_imported=0,
            warnings_count=0,
            error_message=None,
            created_at=created_at,
            started_at=None,
            finished_at=None,
        )
        self.imports[import_id] = job
        self.created_payloads.append(
            {
                "user_id": user_external_id,
                "s3_bucket": s3_bucket,
                "s3_key": s3_key,
                "s3_etag": s3_etag,
            }
        )
        return job

    def get_import(self, import_id: str) -> ImportJob | None:
        return self.imports.get(import_id)


class ImportApiTests(unittest.TestCase):
    def test_create_import_requires_authorization(self):
        repository = InMemoryImportRepository()
        app = create_app(imports_repository=repository)

        response = app.test_client().post(
            "/api/imports",
            json={
                "s3_bucket": "existing-bucket",
                "s3_key": "uploads/demo_user/takeout.zip",
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"error": "missing_authorization"})
        self.assertEqual(repository.created_payloads, [])

    def test_create_import_rejects_malformed_authorization(self):
        repository = InMemoryImportRepository()
        app = create_app(imports_repository=repository)

        response = app.test_client().post(
            "/api/imports",
            headers={"Authorization": "Token demo_user"},
            json={
                "s3_bucket": "existing-bucket",
                "s3_key": "uploads/demo_user/takeout.zip",
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"error": "invalid_authorization"})
        self.assertEqual(repository.created_payloads, [])

    def test_create_import_rejects_body_identity_fields(self):
        for field in ("user_id", "person_id", "ldihk_id"):
            with self.subTest(field=field):
                repository = InMemoryImportRepository()
                app = create_app(imports_repository=repository)

                response = app.test_client().post(
                    "/api/imports",
                    headers=auth_headers(),
                    json={
                        field: "spoofed_user",
                        "s3_bucket": "existing-bucket",
                        "s3_key": "uploads/demo_user/takeout.zip",
                    },
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json(),
                    {
                        "error": "invalid_payload",
                        "fields": {field: "not_allowed"},
                    },
                )
                self.assertEqual(repository.created_payloads, [])

    def test_create_import_returns_created_queued_job(self):
        repository = InMemoryImportRepository()
        app = create_app(imports_repository=repository)

        response = app.test_client().post(
            "/api/imports",
            headers=auth_headers(),
            json={
                "s3_bucket": "existing-bucket",
                "s3_key": "uploads/demo_user/takeout.zip",
                "s3_etag": "optional-etag",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.get_json(),
            {"import_id": "import-1", "ldihk_id": "demo_user", "status": "queued"},
        )
        self.assertEqual(
            repository.created_payloads,
            [
                {
                    "user_id": "demo_user",
                    "s3_bucket": "existing-bucket",
                    "s3_key": "uploads/demo_user/takeout.zip",
                    "s3_etag": "optional-etag",
                }
            ],
        )

    def test_get_import_returns_status_counters_and_timestamps(self):
        repository = InMemoryImportRepository()
        app = create_app(imports_repository=repository)
        client = app.test_client()

        create_response = client.post(
            "/api/imports",
            headers=auth_headers(),
            json={
                "s3_bucket": "existing-bucket",
                "s3_key": "uploads/demo_user/takeout.zip",
            },
        )
        import_id = create_response.get_json()["import_id"]

        response = client.get(f"/api/imports/{import_id}", headers=auth_headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "import_id": import_id,
                "ldihk_id": "demo_user",
                "status": "queued",
                "records_seen": 0,
                "records_imported": 0,
                "warnings_count": 0,
                "error_message": None,
                "created_at": "2026-06-06T08:00:00+00:00",
                "started_at": None,
                "finished_at": None,
            },
        )

    def test_get_import_enforces_bearer_identity_ownership(self):
        repository = InMemoryImportRepository()
        app = create_app(imports_repository=repository)
        client = app.test_client()

        create_response = client.post(
            "/api/imports",
            headers=auth_headers("demo_user"),
            json={
                "s3_bucket": "existing-bucket",
                "s3_key": "uploads/demo_user/takeout.zip",
            },
        )
        import_id = create_response.get_json()["import_id"]

        response = client.get(
            f"/api/imports/{import_id}",
            headers=auth_headers("other_user"),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {"error": "import_not_found"})

    def test_get_import_returns_not_found_for_unknown_id(self):
        repository = InMemoryImportRepository()
        app = create_app(imports_repository=repository)

        response = app.test_client().get(
            "/api/imports/missing-import",
            headers=auth_headers(),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {"error": "import_not_found"})

    def test_create_import_rejects_invalid_payloads_with_stable_error_codes(self):
        repository = InMemoryImportRepository()
        app = create_app(imports_repository=repository)

        response = app.test_client().post(
            "/api/imports",
            headers=auth_headers(),
            json={
                "s3_bucket": "",
                "s3_key": "uploads/demo_user/takeout.zip",
                "s3_etag": 123,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {
                "error": "invalid_payload",
                "fields": {
                    "s3_bucket": "required",
                    "s3_etag": "must_be_string",
                },
            },
        )
        self.assertEqual(repository.created_payloads, [])

    def test_create_import_rejects_unsafe_s3_keys(self):
        repository = InMemoryImportRepository()
        app = create_app(imports_repository=repository)

        response = app.test_client().post(
            "/api/imports",
            headers=auth_headers(),
            json={
                "s3_bucket": "existing-bucket",
                "s3_key": "../takeout.zip",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {
                "error": "invalid_payload",
                "fields": {"s3_key": "unsafe_key"},
            },
        )
        self.assertEqual(repository.created_payloads, [])

    def test_create_import_requires_s3_key_under_user_upload_prefix(self):
        repository = InMemoryImportRepository()
        app = create_app(imports_repository=repository)

        response = app.test_client().post(
            "/api/imports",
            headers=auth_headers(),
            json={
                "s3_bucket": "existing-bucket",
                "s3_key": "uploads/other_user/takeout.zip",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {
                "error": "invalid_payload",
                "fields": {"s3_key": "must_match_user_upload_prefix"},
            },
        )
        self.assertEqual(repository.created_payloads, [])


if __name__ == "__main__":
    unittest.main()
