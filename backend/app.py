from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, jsonify

from backend.youtube_usage import DEFAULT_OUTPUT_PATH


def create_app(processed_path: Path | str = DEFAULT_OUTPUT_PATH) -> Flask:
    app = Flask(__name__)
    processed_path = Path(processed_path)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/users/local_user/youtube-usage")
    def youtube_usage():
        if not processed_path.exists():
            return (
                jsonify(
                    {
                        "error": "processed_data_missing",
                        "expected_path": str(processed_path),
                    }
                ),
                503,
            )

        payload = json.loads(processed_path.read_text(encoding="utf-8"))
        return jsonify(payload)

    return app


app = create_app()
