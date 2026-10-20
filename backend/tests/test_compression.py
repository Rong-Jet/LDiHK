from __future__ import annotations

import gzip
import json
import unittest

from flask import Flask, jsonify

from backend.background import DEFAULT_ACTIVE_WINDOW_SECONDS
from backend.compression import MIN_COMPRESS_BYTES, configure_compression


def _app() -> Flask:
    app = Flask(__name__)
    configure_compression(app)

    @app.get("/large")
    def large():
        return jsonify({"rows": [{"date": "2026-10-01", "hour": hour, "event_count": 0} for hour in range(200)]})

    @app.get("/small")
    def small():
        return jsonify({"status": "ok"})

    @app.get("/text")
    def text():
        return "x" * (MIN_COMPRESS_BYTES * 4)

    return app


class CompressionTests(unittest.TestCase):
    def test_large_json_is_gzipped_when_the_client_accepts_it(self):
        response = _app().test_client().get("/large", headers={"Accept-Encoding": "gzip, deflate, br"})

        self.assertEqual(response.headers.get("Content-Encoding"), "gzip")
        self.assertIn("Accept-Encoding", response.headers.get("Vary", ""))
        body = json.loads(gzip.decompress(response.data))
        self.assertEqual(len(body["rows"]), 200)
        self.assertEqual(int(response.headers["Content-Length"]), len(response.data))

    def test_clients_without_gzip_get_plain_json(self):
        response = _app().test_client().get("/large")

        self.assertNotIn("Content-Encoding", response.headers)
        self.assertEqual(len(json.loads(response.data)["rows"]), 200)

    def test_small_and_non_json_responses_are_left_alone(self):
        client = _app().test_client()
        for path in ("/small", "/text"):
            with self.subTest(path=path):
                response = client.get(path, headers={"Accept-Encoding": "gzip"})
                self.assertNotIn("Content-Encoding", response.headers)


class WorkerWindowTests(unittest.TestCase):
    def test_in_process_workers_stop_polling_soon_after_traffic(self):
        # Every minute the workers keep polling keeps a free Neon database
        # awake (~5 minutes more after the last query) and costs compute hours.
        self.assertLessEqual(DEFAULT_ACTIVE_WINDOW_SECONDS, 300)


if __name__ == "__main__":
    unittest.main()
