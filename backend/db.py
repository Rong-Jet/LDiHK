from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse


DATABASE_URL_ENV = "DATABASE_URL"
DATABASE_CONNECT_TIMEOUT_ENV = "DATABASE_CONNECT_TIMEOUT_SECONDS"
DATABASE_STATEMENT_TIMEOUT_ENV = "DATABASE_STATEMENT_TIMEOUT_MS"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_STATEMENT_TIMEOUT_MS = 60000
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
# Arbitrary constant shared by every process that runs migrations, so two
# processes starting at once cannot apply the same migration twice. Taken as a
# transaction-level lock (an earlier version used 7_416_200_421 as a session
# lock, which a transaction pooler could leave held; a new ID avoids it).
MIGRATION_ADVISORY_LOCK_ID = 7_416_200_423
# Startup must never hang behind a lock: give up and log instead.
MIGRATION_LOCK_TIMEOUT = "60s"

LOGGER = logging.getLogger(__name__)
_warned_pooler_hosts: set[str] = set()
_warned_schema_missing = False


class DatabaseConfigError(RuntimeError):
    pass


class DatabaseUnavailableError(RuntimeError):
    """Raised when Postgres is configured but cannot be reached or queried."""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    sql: str


def get_database_url(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    database_url = env.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        raise DatabaseConfigError("DATABASE_URL is required to connect to Postgres")
    _validate_postgres_url(database_url)
    return database_url


def connect(
    database_url: str | None = None,
    *,
    autocommit: bool = False,
    statement_timeout_ms: int | None = None,
):
    database_url = get_database_url() if database_url is None else database_url.strip()
    _validate_postgres_url(database_url)
    try:
        import psycopg
    except ModuleNotFoundError as error:  # pragma: no cover - depends on env setup
        raise RuntimeError(
            "psycopg is required for Postgres connections; run `uv sync` first"
        ) from error
    return psycopg.connect(
        database_url,
        **connection_kwargs(
            database_url, autocommit=autocommit, statement_timeout_ms=statement_timeout_ms
        ),
    )


def connection_kwargs(
    database_url: str | None = None,
    *,
    autocommit: bool = False,
    statement_timeout_ms: int | None = None,
) -> dict[str, object]:
    """Keyword arguments for psycopg.connect (shared with the pool)."""
    if statement_timeout_ms is None:
        statement_timeout_ms = _env_int(
            DATABASE_STATEMENT_TIMEOUT_ENV, DEFAULT_STATEMENT_TIMEOUT_MS
        )
    connect_kwargs: dict[str, object] = {
        "autocommit": autocommit,
        "connect_timeout": _env_int(
            DATABASE_CONNECT_TIMEOUT_ENV, DEFAULT_CONNECT_TIMEOUT_SECONDS
        ),
        # Transaction-mode poolers (Neon "-pooler" hosts, Supabase port 6543)
        # do not support server-side prepared statements.
        "prepare_threshold": None,
    }
    if statement_timeout_ms > 0:
        if database_url and is_transaction_pooler_url(database_url):
            # Poolers reject startup options ("unsupported startup parameter
            # in options: statement_timeout"). The direct connection string
            # keeps the timeout; through a pooler the server default applies.
            _warn_pooler_once(database_url)
        else:
            connect_kwargs["options"] = f"-c statement_timeout={statement_timeout_ms}"
    return connect_kwargs


def is_transaction_pooler_url(database_url: str) -> bool:
    """Neon "-pooler" hosts and Supabase poolers (PgBouncer / Supavisor)."""
    parsed = urlparse(database_url)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        port = None
    return "-pooler." in host or host.endswith("pooler.supabase.com") or port == 6543


def _warn_pooler_once(database_url: str) -> None:
    host = (urlparse(database_url).hostname or "").lower()
    if host in _warned_pooler_hosts:
        return
    _warned_pooler_hosts.add(host)
    LOGGER.info(
        "DATABASE_URL points at a connection pooler; %s is not applied. Use the "
        "direct connection string to enable it.",
        DATABASE_STATEMENT_TIMEOUT_ENV,
    )


def is_invalid_timezone_error(error: BaseException) -> bool:
    """True when Postgres rejected a time zone name (e.g. missing tz data)."""
    try:
        import psycopg
    except ModuleNotFoundError:  # pragma: no cover - depends on env setup
        return False
    return isinstance(error, psycopg.errors.InvalidParameterValue) and (
        "time zone" in str(error)
    )


def is_database_unavailable_error(error: BaseException) -> bool:
    """True for errors that mean "the database is down", not "bad query".

    A missing table counts too: the database is reachable but not migrated yet.
    """
    if isinstance(error, DatabaseUnavailableError):
        return True
    try:
        import psycopg
    except ModuleNotFoundError:  # pragma: no cover - depends on env setup
        return False
    if isinstance(error, psycopg.errors.UndefinedTable):
        _warn_schema_missing_once(error)
        return True
    return isinstance(error, (psycopg.OperationalError, psycopg.InterfaceError))


def _warn_schema_missing_once(error: BaseException) -> None:
    global _warned_schema_missing
    if _warned_schema_missing:
        return
    _warned_schema_missing = True
    LOGGER.error(
        "The database schema is missing (%s). Migrations run when the service "
        "starts only with RUN_WORKERS_IN_PROCESS=true; otherwise run "
        "backend/scripts/run_migrations.py.",
        str(error).splitlines()[0],
    )


def list_migrations(
    migrations_dir: Path | str = DEFAULT_MIGRATIONS_DIR,
) -> list[Migration]:
    migration_paths = sorted(Path(migrations_dir).glob("*.sql"))
    return [
        Migration(
            version=_migration_version(path),
            name=path.name,
            path=path,
            sql=path.read_text(encoding="utf-8"),
        )
        for path in migration_paths
    ]


def run_migrations(
    connection=None,
    *,
    database_url: str | None = None,
    migrations_dir: Path | str = DEFAULT_MIGRATIONS_DIR,
) -> list[Migration]:
    """Apply pending migrations in ONE transaction, all or none.

    One transaction with a transaction-level advisory lock also works through
    transaction-mode poolers (Neon "-pooler" hosts), where session locks and
    session settings can land on different server connections.
    """
    should_close = connection is None
    if connection is None:
        connection = connect(database_url, statement_timeout_ms=0)

    try:
        try:
            if _supports_advisory_locks(connection):
                connection.execute(f"SET LOCAL lock_timeout = '{MIGRATION_LOCK_TIMEOUT}'")
                connection.execute(
                    "SELECT pg_advisory_xact_lock(%s)", (MIGRATION_ADVISORY_LOCK_ID,)
                )
            _ensure_schema_migrations(connection)
            applied_versions = _applied_migration_versions(connection)
            applied: list[Migration] = []
            for migration in list_migrations(migrations_dir):
                if migration.version in applied_versions:
                    continue
                _apply_migration(connection, migration)
                applied.append(migration)
                applied_versions.add(migration.version)
            connection.commit()
            return applied
        except Exception:
            connection.rollback()
            raise
    finally:
        if should_close:
            connection.close()


def _validate_postgres_url(database_url: str) -> None:
    if not database_url:
        raise DatabaseConfigError("DATABASE_URL is required to connect to Postgres")
    scheme = urlparse(database_url).scheme
    if scheme not in {"postgres", "postgresql"}:
        raise DatabaseConfigError("DATABASE_URL must be a Postgres connection URL")


def _migration_version(path: Path) -> str:
    return path.name.split("_", 1)[0]


def _env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError as error:
        raise DatabaseConfigError(f"{name} must be an integer") from error


def _supports_advisory_locks(connection) -> bool:
    return type(connection).__module__.startswith("psycopg")


def _ensure_schema_migrations(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def _applied_migration_versions(connection) -> set[str]:
    rows = connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall()
    return {row[0] for row in rows}


def _apply_migration(connection, migration: Migration) -> None:
    connection.execute(migration.sql)
    connection.execute(
        """
        INSERT INTO schema_migrations (version, name)
        VALUES (%s, %s)
        """,
        (migration.version, migration.name),
    )
