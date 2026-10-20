from __future__ import annotations

import os
import unittest
from unittest import mock

from flask import Flask

from backend.app import create_app
from backend.rate_limit import Limit, RateLimiter, configure_rate_limits
from backend.tests.test_free_hosting_api import FakeImportsRepository, SummaryConnection


def _auth(ldihk_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {ldihk_id}"}


def _app(env: dict[str, str]):
    with mock.patch.dict(os.environ, {"S3_BUCKET": "ldihk-uploads", **env}, clear=False):
        return create_app(
            imports_repository=FakeImportsRepository(),
            query_connection_factory=lambda: SummaryConnection(user_exists=False),
            start_workers=False,
        )


def _create_import(client, ldihk_id: str, headers: dict[str, str] | None = None):
    with mock.patch.dict(os.environ, {"S3_BUCKET": "ldihk-uploads"}, clear=False):
        return client.post(
            "/api/imports",
            headers={**_auth(ldihk_id), **(headers or {})},
            json={"s3_bucket": "ldihk-uploads", "s3_key": f"uploads/{ldihk_id}/takeout.zip"},
        )


class RateLimiterTests(unittest.TestCase):
    def test_sliding_window_allows_again_after_the_window(self):
        now = [0.0]
        limiter = RateLimiter(clock=lambda: now[0])
        rule = Limit(2, 60)

        self.assertIsNone(limiter.hit("k", rule))
        self.assertIsNone(limiter.hit("k", rule))
        self.assertAlmostEqual(limiter.hit("k", rule), 60)
        now[0] = 61
        self.assertIsNone(limiter.hit("k", rule))


class ApiRateLimitTests(unittest.TestCase):
    def test_imports_are_limited_per_id_with_retry_after(self):
        client = _app({}).test_client()
        ldihk_id = "ldihk-cosmic-nebula-abcdefgh2345"

        statuses = [_create_import(client, ldihk_id).status_code for _ in range(21)]
        limited = _create_import(client, ldihk_id)
        other_user = _create_import(client, "ldihk-cosmic-nebula-zzzzzzzz2345")

        self.assertEqual(statuses[:20], [201] * 20)
        self.assertEqual(statuses[20], 429)
        self.assertEqual(limited.get_json()["error"], "rate_limited")
        self.assertGreater(int(limited.headers["Retry-After"]), 0)
        self.assertEqual(other_user.status_code, 201)

    def test_failed_logins_are_limited_per_ip_when_the_ip_header_is_configured(self):
        client = _app({"CLIENT_IP_HEADER": "True-Client-IP"}).test_client()
        attacker = {"True-Client-IP": "203.0.113.7"}

        statuses = [
            client.get("/api/me", headers={**_auth(f"ldihk-guess-{index:04d}"), **attacker}).status_code
            for index in range(31)
        ]
        someone_else = client.get(
            "/api/me", headers={**_auth("ldihk-guess-other"), "True-Client-IP": "198.51.100.1"}
        )

        self.assertEqual(statuses[:30], [404] * 30)
        self.assertEqual(statuses[30], 429)
        self.assertEqual(someone_else.status_code, 404)

    def test_spoofable_forwarded_for_is_ignored_without_an_ip_header(self):
        client = _app({}).test_client()

        # Rotating X-Forwarded-For values must not create fresh per-IP quota,
        # and without CLIENT_IP_HEADER no per-IP limit applies at all.
        statuses = [
            client.get(
                "/api/me",
                headers={**_auth(f"ldihk-guess-{index:04d}"), "X-Forwarded-For": f"10.0.0.{index}"},
            ).status_code
            for index in range(40)
        ]

        self.assertEqual(set(statuses), {404})

    def test_rate_limits_can_be_disabled(self):
        app = Flask(__name__)
        self.assertIsNone(configure_rate_limits(app, environ={"RATE_LIMITS_ENABLED": "false"}))


if __name__ == "__main__":
    unittest.main()
