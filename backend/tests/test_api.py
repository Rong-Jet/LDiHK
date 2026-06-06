import json
import tempfile
import unittest
from pathlib import Path

from backend.app import create_app


class YoutubeUsageApiTests(unittest.TestCase):
    def test_health_returns_ok(self):
        app = create_app(processed_path=Path("does-not-need-to-exist.json"))

        response = app.test_client().get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_serves_processed_youtube_usage_json(self):
        payload = {
            "schema_version": "youtube_usage.v1",
            "person_id": "local_user",
            "events": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            processed_path = Path(tmpdir) / "youtube_usage.v1.json"
            processed_path.write_text(json.dumps(payload), encoding="utf-8")
            app = create_app(processed_path=processed_path)

            response = app.test_client().get("/api/users/local_user/youtube-usage")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), payload)

    def test_missing_processed_youtube_usage_returns_service_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            processed_path = Path(tmpdir) / "missing.json"
            app = create_app(processed_path=processed_path)

            response = app.test_client().get("/api/users/local_user/youtube-usage")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {
                "error": "processed_data_missing",
                "expected_path": str(processed_path),
            },
        )
