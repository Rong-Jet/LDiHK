from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from flask import Flask, jsonify, request

from backend.db import DatabaseConfigError, connect
from backend.http_boundary import (
    PublicBoundaryError,
    configure_cors,
    identity_field_error_response,
    identity_field_errors,
    public_boundary_error_response,
    require_bearer_identity,
)
from backend.imports_api import ImportRepository, create_imports_blueprint
from backend.population_api import (
    PopulationValidationError,
    query_youtube_population,
)
from backend.query_api import (
    QueryValidationError as StructuredQueryValidationError,
    public_query_response,
    query_request_for_ldihk_id,
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
    configure_cors(app)
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
            identity = require_bearer_identity()
            request_payload = request.get_json(silent=True)
            identity_errors = identity_field_errors(request_payload)
            if identity_errors:
                return identity_field_error_response(identity_errors)

            query = validate_query_request(
                query_request_for_ldihk_id(
                    request_payload,
                    ldihk_id=identity.ldihk_id,
                )
            )
            connection = query_connection_factory()
            payload = public_query_response(
                query_structured_youtube_usage(connection, query)
            )
        except PublicBoundaryError as error:
            return public_boundary_error_response(error)
        except StructuredQueryValidationError as error:
            return jsonify({"error": error.code}), 400
        except DatabaseConfigError as error:
            return jsonify({"error": "database_unavailable", "message": str(error)}), 503
        finally:
            if connection is not None:
                connection.close()
        return jsonify(payload)

    @app.post("/api/population")
    def youtube_population_query():
        connection = None
        try:
            identity = require_bearer_identity()
            request_payload = request.get_json(silent=True)
            identity_errors = identity_field_errors(request_payload)
            if identity_errors:
                return identity_field_error_response(identity_errors)

            connection = query_connection_factory()
            payload = query_youtube_population(
                connection,
                request_payload,
                ldihk_id=identity.ldihk_id,
            )
        except PublicBoundaryError as error:
            return public_boundary_error_response(error)
        except PopulationValidationError as error:
            return jsonify({"error": error.code}), 400
        except DatabaseConfigError as error:
            return jsonify({"error": "database_unavailable", "message": str(error)}), 503
        finally:
            if connection is not None:
                connection.close()
        return jsonify(payload)

    return app


app = create_app()
