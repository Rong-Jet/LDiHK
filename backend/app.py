from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Callable

from flask import Flask, jsonify, request

from backend.background import start_in_process_workers
from backend.db import DatabaseConfigError, connect, is_database_unavailable_error
from backend.http_boundary import (
    PublicBoundaryError,
    configure_cors,
    identity_field_error_response,
    identity_field_errors,
    public_boundary_error_response,
    require_bearer_identity,
)
from backend.imports_api import (
    ImportRepository,
    PostgresImportRepository,
    create_imports_blueprint,
    status_payload,
)
from backend.population_api import (
    PopulationValidationError,
    query_youtube_population,
)
from backend.query_api import (
    QueryValidationError as StructuredQueryValidationError,
    fetch_user_summary,
    public_query_response,
    query_request_for_ldihk_id,
    query_youtube_usage as query_structured_youtube_usage,
    validate_query_request,
    validate_timezone_name,
)
from backend.youtube_sql import (
    DEFAULT_SQLITE_PATH,
    QueryValidationError,
    query_youtube_usage,
)
from backend.youtube_temporal import build_temporal_usage
from backend.youtube_usage import DEFAULT_OUTPUT_PATH

LOGGER = logging.getLogger(__name__)
ENABLE_LOCAL_FILE_ROUTES_ENV = "ENABLE_LOCAL_FILE_ROUTES"
# Requests that should not count as user activity for the worker threads:
# uptime pings must not keep waking the (free-tier) database.
_INACTIVE_PATHS = frozenset({"/health"})


def create_app(
    processed_path: Path | str = DEFAULT_OUTPUT_PATH,
    sqlite_path: Path | str = DEFAULT_SQLITE_PATH,
    imports_repository: ImportRepository | None = None,
    query_connection_factory: Callable[[], object] = connect,
    *,
    enable_local_file_routes: bool | None = None,
    start_workers: bool = True,
) -> Flask:
    app = Flask(__name__)
    _configure_logging()
    configure_cors(app)
    processed_path = Path(processed_path)
    sqlite_path = Path(sqlite_path)
    imports_repository = (
        PostgresImportRepository() if imports_repository is None else imports_repository
    )
    workers = start_in_process_workers() if start_workers else None
    app.register_blueprint(
        create_imports_blueprint(
            imports_repository,
            on_import_created=workers.signal.notify if workers is not None else None,
        )
    )
    if enable_local_file_routes is None:
        enable_local_file_routes = _env_flag(ENABLE_LOCAL_FILE_ROUTES_ENV, default=True)

    if workers is not None:

        @app.after_request
        def _notify_workers(response):
            # After the request, so a just-created import is already committed
            # when the import thread wakes up.
            if request.method != "OPTIONS" and request.path not in _INACTIVE_PATHS:
                workers.signal.notify()
            return response

    def database_unavailable(error: Exception | None = None):
        payload = {"error": "database_unavailable"}
        if isinstance(error, DatabaseConfigError):
            # Our own configuration message; driver errors may include hostnames.
            payload["message"] = str(error)
        return jsonify(payload), 503

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    if enable_local_file_routes:
        _register_local_file_routes(app, processed_path, sqlite_path)

    @app.get("/api/me")
    def current_user_summary():
        connection = None
        try:
            identity = require_bearer_identity()
            bucket_timezone = validate_timezone_name(
                request.args.get("timezone") or "UTC"
            )
            connection = query_connection_factory()
            summary = fetch_user_summary(
                connection,
                ldihk_id=identity.ldihk_id,
                bucket_timezone=bucket_timezone,
            )
        except PublicBoundaryError as error:
            return public_boundary_error_response(error)
        except StructuredQueryValidationError as error:
            return jsonify({"error": error.code}), 400
        except DatabaseConfigError as error:
            return database_unavailable(error)
        except Exception as error:
            if is_database_unavailable_error(error):
                LOGGER.warning("Database unavailable: %s", error)
                return database_unavailable()
            raise
        finally:
            if connection is not None:
                connection.close()

        latest_import = None
        get_latest = getattr(imports_repository, "get_latest_import_for_user", None)
        if get_latest is not None:
            try:
                job = get_latest(identity.ldihk_id)
            except Exception as error:
                if is_database_unavailable_error(error):
                    return database_unavailable()
                raise
            latest_import = status_payload(job) if job is not None else None

        if summary is None and latest_import is None:
            return jsonify({"error": "unknown_ldihk_id"}), 404
        if summary is None:
            # Uploaded, but nothing imported yet (queued, running or failed).
            summary = {
                "ldihk_id": identity.ldihk_id,
                "exists": True,
                "timezone": bucket_timezone,
                "datasets": {},
            }
        return jsonify({**summary, "latest_import": latest_import})

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
            return database_unavailable(error)
        except Exception as error:
            if is_database_unavailable_error(error):
                LOGGER.warning("Database unavailable: %s", error)
                return database_unavailable()
            raise
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
        except (PopulationValidationError, StructuredQueryValidationError) as error:
            return jsonify({"error": error.code}), 400
        except DatabaseConfigError as error:
            return database_unavailable(error)
        except Exception as error:
            if is_database_unavailable_error(error):
                LOGGER.warning("Database unavailable: %s", error)
                return database_unavailable()
            raise
        finally:
            if connection is not None:
                connection.close()
        return jsonify(payload)

    return app


def _register_local_file_routes(
    app: Flask, processed_path: Path, sqlite_path: Path
) -> None:
    """Unauthenticated routes over local processed files (development only)."""

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


def _configure_logging() -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _env_flag(name: str, *, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


app = create_app()
