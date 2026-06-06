from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from flask import Flask, jsonify, request

from backend.db import DatabaseConfigError, connect
from backend.imports_api import ImportRepository, create_imports_blueprint
from backend.query_api import (
    QueryValidationError as StructuredQueryValidationError,
    query_youtube_usage as query_structured_youtube_usage,
    validate_query_request,
)
from backend.youtube_sql import (
    DEFAULT_SQLITE_PATH,
    QueryValidationError,
    query_youtube_usage,
)
from backend.youtube_temporal import build_temporal_usage
from backend.youtube_usage import DEFAULT_OUTPUT_PATH


def create_app(
    processed_path: Path | str = DEFAULT_OUTPUT_PATH,
    sqlite_path: Path | str = DEFAULT_SQLITE_PATH,
    imports_repository: ImportRepository | None = None,
    query_connection_factory: Callable[[], object] = connect,
) -> Flask:
    app = Flask(__name__)
    processed_path = Path(processed_path)
    sqlite_path = Path(sqlite_path)
    app.register_blueprint(create_imports_blueprint(imports_repository))

    def processed_data_missing():
        return (
            jsonify(
                {
                    "error": "processed_data_missing",
                    "expected_path": str(processed_path),
                }
            ),
            503,
        )

    def read_processed_payload() -> dict[str, object] | None:
        if not processed_path.exists():
            return None
        return json.loads(processed_path.read_text(encoding="utf-8"))

    def sql_data_missing():
        return (
            jsonify(
                {
                    "error": "sql_data_missing",
                    "expected_path": str(sqlite_path),
                }
            ),
            503,
        )

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/users/local_user/youtube-usage")
    def youtube_usage():
        payload = read_processed_payload()
        if payload is None:
            return processed_data_missing()
        return jsonify(payload)

    @app.get("/api/v2/users/local_user/youtube-usage/temporal")
    def youtube_usage_temporal():
        payload = read_processed_payload()
        if payload is None:
            return processed_data_missing()
        return jsonify(build_temporal_usage(payload))

    @app.post("/api/v3/query")
    def youtube_usage_v3_query():
        if not sqlite_path.exists():
            return sql_data_missing()
        try:
            payload = query_youtube_usage(sqlite_path, request.get_json(silent=True))
        except QueryValidationError as error:
            return jsonify({"error": error.code}), 400
        return jsonify(payload)

    @app.post("/api/query")
    def youtube_usage_structured_query():
        connection = None
        try:
            query = validate_query_request(request.get_json(silent=True))
            connection = query_connection_factory()
            payload = query_structured_youtube_usage(connection, query)
        except StructuredQueryValidationError as error:
            return jsonify({"error": error.code}), 400
        except DatabaseConfigError as error:
            return jsonify({"error": "database_unavailable", "message": str(error)}), 503
        finally:
            if connection is not None:
                connection.close()
        return jsonify(payload)

    return app


app = create_app()
