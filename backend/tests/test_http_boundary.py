from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.app import create_app


class HttpBoundaryTests(unittest.TestCase):
    def test_health_remains_unauthenticated(self):
        app = create_app()

        response = app.test_client().get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_cors_allows_configured_frontend_origin(self):
        with patch.dict(
            os.environ,
            {"FRONTEND_ALLOWED_ORIGINS": "https://frontend.example.com"},
        ):
            app = create_app()

        response = app.test_client().options(
            "/api/imports",
            headers={
                "Origin": "https://frontend.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            "https://frontend.example.com",
        )
        self.assertEqual(response.headers["Vary"], "Origin")
        self.assertIn("POST", response.headers["Access-Control-Allow-Methods"])
        self.assertIn("Authorization", response.headers["Access-Control-Allow-Headers"])

    def test_cors_allows_explicit_dev_origin(self):
        with patch.dict(os.environ, {"FRONTEND_ALLOWED_ORIGINS": ""}):
            app = create_app()

        response = app.test_client().options(
            "/api/query",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            "http://localhost:5173",
        )

    def test_cors_rejects_unlisted_origin_preflight(self):
        with patch.dict(
            os.environ,
            {"FRONTEND_ALLOWED_ORIGINS": "https://frontend.example.com"},
        ):
            app = create_app()

        response = app.test_client().options(
            "/api/imports",
            headers={
                "Origin": "https://attacker.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)


if __name__ == "__main__":
    unittest.main()
