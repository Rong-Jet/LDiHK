"""In-memory rate limits for the public API.

The free deployment runs a single web process, so limits kept in memory are
enough to slow down ID guessing, import spam and expensive population
queries without an extra service such as Redis. Separate gunicorn processes
would each keep their own counters.

Per-ID limits always apply. Per-IP limits only apply when CLIENT_IP_HEADER
names a header the hosting proxy sets reliably: Render appends to a
client-supplied X-Forwarded-For instead of replacing it, so that header is
not trusted by default.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import os
import re
import threading
import time
from typing import Callable, Mapping

from flask import Flask, Response, jsonify, request

CLIENT_IP_HEADER_ENV = "CLIENT_IP_HEADER"
RATE_LIMITS_ENABLED_ENV = "RATE_LIMITS_ENABLED"
_BEARER_PATTERN = re.compile(r"^Bearer ([A-Za-z0-9][A-Za-z0-9._-]{2,127})$")
_MAX_TRACKED_KEYS = 20_000


@dataclass(frozen=True)
class Limit:
    limit: int
    window_seconds: float


class RateLimiter:
    """Sliding-window counters keyed by arbitrary strings."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def retry_after(self, key: str, rule: Limit) -> float | None:
        """Seconds until ``key`` may be hit again, or None if it is allowed now."""
        with self._lock:
            hits = self._prune(key, rule)
            if len(hits) >= rule.limit:
                return max(0.0, hits[0] + rule.window_seconds - self._clock())
            return None

    def hit(self, key: str, rule: Limit) -> float | None:
        """Record one hit; returns the wait in seconds if over the limit."""
        with self._lock:
            hits = self._prune(key, rule)
            if len(hits) >= rule.limit:
                return max(0.0, hits[0] + rule.window_seconds - self._clock())
            hits.append(self._clock())
            if len(self._hits) > _MAX_TRACKED_KEYS:
                self._drop_empty()
            return None

    def _prune(self, key: str, rule: Limit) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        cutoff = self._clock() - rule.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def _drop_empty(self) -> None:
        for key in [key for key, hits in self._hits.items() if not hits]:
            del self._hits[key]


# (method, path) -> rules applied before the request runs.
PER_ID_LIMITS: dict[tuple[str, str], Limit] = {
    ("POST", "/api/imports"): Limit(20, 3600),
    ("POST", "/api/uploads"): Limit(20, 3600),
    ("POST", "/api/population"): Limit(120, 3600),
    ("POST", "/api/query"): Limit(1500, 3600),
    ("DELETE", "/api/me"): Limit(5, 3600),
}
PER_IP_LIMITS: dict[tuple[str, str], Limit] = {
    ("POST", "/api/imports"): Limit(60, 3600),
    ("POST", "/api/uploads"): Limit(60, 3600),
}
GLOBAL_LIMITS: dict[tuple[str, str], Limit] = {
    # A classroom uploading at once fits; a script creating users does not.
    ("POST", "/api/imports"): Limit(300, 3600),
    ("POST", "/api/uploads"): Limit(300, 3600),
}
# Failed logins (404 unknown_ldihk_id) count after the response.
UNKNOWN_ID_PER_IP = Limit(30, 600)
UNKNOWN_ID_GLOBAL = Limit(600, 3600)


def configure_rate_limits(
    app: Flask,
    *,
    limiter: RateLimiter | None = None,
    environ: Mapping[str, str] = os.environ,
) -> RateLimiter | None:
    if environ.get(RATE_LIMITS_ENABLED_ENV, "true").strip().lower() in {"0", "false", "no", "off"}:
        return None
    limiter = limiter or RateLimiter()
    ip_header = environ.get(CLIENT_IP_HEADER_ENV, "").strip() or None

    def client_ip() -> str | None:
        if ip_header is None:
            return None
        value = request.headers.get(ip_header, "").split(",")[0].strip()
        return value or None

    def bearer_id() -> str | None:
        match = _BEARER_PATTERN.match(request.headers.get("Authorization", "").strip())
        return match.group(1) if match else None

    @app.before_request
    def _enforce_limits():
        if request.method == "OPTIONS":
            return None
        route = (request.method, request.path)
        checks: list[tuple[str, Limit]] = []
        ldihk_id = bearer_id()
        if route in PER_ID_LIMITS and ldihk_id is not None:
            checks.append((f"id:{route}:{ldihk_id}", PER_ID_LIMITS[route]))
        ip = client_ip()
        if route in PER_IP_LIMITS and ip is not None:
            checks.append((f"ip:{route}:{ip}", PER_IP_LIMITS[route]))
        if route in GLOBAL_LIMITS:
            checks.append((f"global:{route}", GLOBAL_LIMITS[route]))
        if route == ("GET", "/api/me"):
            # Only failed lookups count (see _count_unknown_ids); check here.
            checks_unknown = [("unknown:global", UNKNOWN_ID_GLOBAL)]
            if ip is not None:
                checks_unknown.append((f"unknown:ip:{ip}", UNKNOWN_ID_PER_IP))
            for key, rule in checks_unknown:
                wait = limiter.retry_after(key, rule)
                if wait is not None:
                    return _rate_limited(wait)

        # Check everything first so a rejected request does not use up quota.
        for key, rule in checks:
            wait = limiter.retry_after(key, rule)
            if wait is not None:
                return _rate_limited(wait)
        for key, rule in checks:
            limiter.hit(key, rule)
        return None

    @app.after_request
    def _count_unknown_ids(response: Response) -> Response:
        if (request.method, request.path) == ("GET", "/api/me") and response.status_code == 404:
            limiter.hit("unknown:global", UNKNOWN_ID_GLOBAL)
            ip = client_ip()
            if ip is not None:
                limiter.hit(f"unknown:ip:{ip}", UNKNOWN_ID_PER_IP)
        return response

    return limiter


def _rate_limited(wait_seconds: float):
    retry_after = max(1, math.ceil(wait_seconds))
    response = jsonify({"error": "rate_limited", "retry_after": retry_after})
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    return response
