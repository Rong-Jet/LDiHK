"""Gzip for JSON API responses.

Flask does not compress responses, and Render's free plan includes 5 GB of
outbound traffic a month (going over without a payment method suspends every
free service for the rest of the month). A one-year date x hour query is
648 KB of JSON per platform but about 25 KB gzipped.
"""

from __future__ import annotations

import gzip

from flask import Flask, Response, request

MIN_COMPRESS_BYTES = 1024
COMPRESSION_LEVEL = 5


def configure_compression(
    app: Flask,
    *,
    min_size: int = MIN_COMPRESS_BYTES,
    level: int = COMPRESSION_LEVEL,
) -> None:
    @app.after_request
    def _gzip_json(response: Response) -> Response:
        if (
            response.direct_passthrough
            or response.mimetype != "application/json"
            or "Content-Encoding" in response.headers
        ):
            return response
        data = response.get_data()
        if len(data) < min_size:
            return response
        # Caches must not serve the gzipped body to clients that cannot read it.
        response.vary.add("Accept-Encoding")
        if "gzip" not in request.accept_encodings:
            return response
        response.set_data(gzip.compress(data, compresslevel=level, mtime=0))
        response.headers["Content-Encoding"] = "gzip"
        return response
