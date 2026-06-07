from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from flask import Flask, Response, jsonify, request


IDENTITY_FIELDS = frozenset({"ldihk_id", "user_id", "person_id"})
DEV_CORS_ORIGINS = frozenset(
    {
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }
)


@dataclass(frozen=True)
class PublicIdentity:
    ldihk_id: str


class PublicBoundaryError(ValueError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def require_bearer_identity() -> PublicIdentity:
    authorization = request.headers.get("Authorization")
    if authorization is None or not authorization.strip():
        raise PublicBoundaryError("missing_authorization", 401)

    parts = authorization.split()
    if len(parts) != 2 or parts[0] != "Bearer" or not parts[1]:
        raise PublicBoundaryError("invalid_authorization", 401)

    return PublicIdentity(ldihk_id=parts[1])


def public_boundary_error_response(error: PublicBoundaryError):
    return jsonify({"error": error.code}), error.status_code


def identity_field_errors(payload: object) -> dict[str, str]:
    fields: set[str] = set()
    _collect_identity_fields(payload, fields)
    return {field: "not_allowed" for field in sorted(fields)}


def identity_field_error_response(errors: dict[str, str]):
    return jsonify({"error": "invalid_payload", "fields": errors}), 400


def configure_cors(
    app: Flask,
    *,
    environ: Mapping[str, str] = os.environ,
) -> None:
    allowed_origins = _allowed_cors_origins(environ)

    @app.before_request
    def _handle_cors_preflight():
        if request.method != "OPTIONS" or "Origin" not in request.headers:
            return None

        origin = request.headers["Origin"]
        if origin not in allowed_origins:
            return "", 403

        response = app.response_class(status=204)
        _set_cors_headers(response, origin)
        return response

    @app.after_request
    def _add_cors_headers(response: Response):
        origin = request.headers.get("Origin")
        if origin in allowed_origins:
            _set_cors_headers(response, origin)
        return response


def _allowed_cors_origins(environ: Mapping[str, str]) -> set[str]:
    configured = {
        origin.strip()
        for origin in environ.get("FRONTEND_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    }
    return configured | set(DEV_CORS_ORIGINS)


def _set_cors_headers(response: Response, origin: str) -> None:
    response.headers["Access-Control-Allow-Origin"] = origin
    response.vary.add("Origin")
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response.headers["Access-Control-Max-Age"] = "600"


def _collect_identity_fields(payload: object, fields: set[str]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and key in IDENTITY_FIELDS:
                fields.add(key)
            _collect_identity_fields(value, fields)
        return

    if isinstance(payload, list):
        for item in payload:
            _collect_identity_fields(item, fields)
