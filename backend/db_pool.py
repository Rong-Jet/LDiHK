"""Connection pool for request handlers.

Opening a Postgres connection to a hosted database (TLS handshake plus auth)
costs more than most of our queries, so request handlers borrow connections
from a small pool instead. The pool keeps no connection open longer than
DATABASE_POOL_MAX_IDLE_SECONDS, so a scale-to-zero database (Neon free) can
still suspend between visits. Background workers keep their own connections.

Borrowed connections behave like ordinary psycopg connections; close() hands
them back (rolling back anything uncommitted, exactly like closing would).
Set DATABASE_POOL_SIZE=0 to open a fresh connection per request instead.
"""

from __future__ import annotations

import logging
import os
import threading

from backend import db


DATABASE_POOL_SIZE_ENV = "DATABASE_POOL_SIZE"
DATABASE_POOL_MAX_IDLE_ENV = "DATABASE_POOL_MAX_IDLE_SECONDS"
# Matches the default number of gunicorn threads (GUNICORN_THREADS).
DEFAULT_POOL_SIZE = 4
DEFAULT_MAX_IDLE_SECONDS = 60
# Give up on a failing connection attempt after this long, so new requests
# start a fresh attempt soon after the database comes back.
RECONNECT_TIMEOUT_SECONDS = 30.0

_lock = threading.Lock()
_pool = None
_pool_url: str | None = None


def pooled_connect():
    """A connection from the pool (or a new one when pooling is off)."""
    database_url = db.get_database_url()
    size = db._env_int(DATABASE_POOL_SIZE_ENV, DEFAULT_POOL_SIZE)
    if size <= 0:
        return db.connect(database_url)
    return _get_pool(database_url, size).getconn()


def close_pool() -> None:
    """Close every pooled connection (tests, shutdown)."""
    global _pool, _pool_url
    with _lock:
        if _pool is not None:
            _pool.close()
        _pool, _pool_url = None, None


def _get_pool(database_url: str, size: int):
    global _pool, _pool_url
    with _lock:
        if _pool is not None and _pool_url == database_url:
            return _pool
        if _pool is not None:
            _pool.close()
        # Created on first use, so it never exists in a process before a fork.
        _pool = _create_pool(database_url, size)
        _pool_url = database_url
        return _pool


def _create_pool(database_url: str, size: int):
    import psycopg
    from psycopg.pq import TransactionStatus
    from psycopg_pool import ConnectionPool

    class PooledConnection(psycopg.Connection):
        def close(self) -> None:
            # Handlers often close after read-only queries without committing.
            # Roll back here so the pool does not log a warning for each one.
            if not self.closed and getattr(self, "_pool", None) is not None:
                if self.pgconn.transaction_status in (
                    TransactionStatus.INTRANS,
                    TransactionStatus.INERROR,
                ):
                    try:
                        self.rollback()
                    except psycopg.Error:
                        pass  # The pool discards broken connections.
            super().close()

    # Every checkout and return is logged at INFO, which would drown the logs.
    logging.getLogger("psycopg.pool").setLevel(logging.WARNING)
    connect_timeout = db._env_int(db.DATABASE_CONNECT_TIMEOUT_ENV, db.DEFAULT_CONNECT_TIMEOUT_SECONDS)
    return ConnectionPool(
        database_url,
        connection_class=PooledConnection,
        kwargs=db.connection_kwargs(database_url),
        min_size=0,
        max_size=size,
        max_idle=float(db._env_int(DATABASE_POOL_MAX_IDLE_ENV, DEFAULT_MAX_IDLE_SECONDS)),
        max_lifetime=1800.0,
        # A connection may have been dropped while idle (network, server).
        check=ConnectionPool.check_connection,
        close_returns=True,
        timeout=float(connect_timeout + 5),
        reconnect_timeout=RECONNECT_TIMEOUT_SECONDS,
        num_workers=1,
        name="ldihk-requests",
        open=True,
    )
