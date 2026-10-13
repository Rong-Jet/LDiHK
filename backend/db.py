from __future__ import annotations

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
# processes starting at once cannot apply the same migration twice.
MIGRATION_ADVISORY_LOCK_ID = 7_416_200_421


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
        connect_kwargs["options"] = f"-c statement_timeout={statement_timeout_ms}"
    return psycopg.connect(database_url, **connect_kwargs)


def is_database_unavailable_error(error: BaseException) -> bool:
    """True for errors that mean "the database is down", not "bad query"."""
    if isinstance(error, DatabaseUnavailableError):
        return True
    try:
        import psycopg
    except ModuleNotFoundError:  # pragma: no cover - depends on env setup
        return False
    return isinstance(error, (psycopg.OperationalError, psycopg.InterfaceError))


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
    should_close = connection is None
    if connection is None:
        connection = connect(database_url, statement_timeout_ms=0)

    try:
        _acquire_migration_lock(connection)
        try:
            _ensure_schema_migrations(connection)
            applied_versions = _applied_migration_versions(connection)
            applied: list[Migration] = []
            for migration in list_migrations(migrations_dir):
                if migration.version in applied_versions:
                    continue
                _apply_migration(connection, migration)
                applied.append(migration)
                applied_versions.add(migration.version)
            return applied
        finally:
            _release_migration_lock(connection)
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


def _acquire_migration_lock(connection) -> None:
    if not _supports_advisory_locks(connection):
        return
    connection.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_ADVISORY_LOCK_ID,))
    connection.commit()


def _release_migration_lock(connection) -> None:
    if not _supports_advisory_locks(connection):
        return
    try:
        connection.rollback()
        connection.execute(
            "SELECT pg_advisory_unlock(%s)", (MIGRATION_ADVISORY_LOCK_ID,)
        )
        connection.commit()
    except Exception:
        # Session-level advisory locks are released when the connection closes.
        pass


def _supports_advisory_locks(connection) -> bool:
    return type(connection).__module__.startswith("psycopg")


def _ensure_schema_migrations(connection) -> None:
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _applied_migration_versions(connection) -> set[str]:
    rows = connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall()
    connection.commit()
    return {row[0] for row in rows}


def _apply_migration(connection, migration: Migration) -> None:
    try:
        connection.execute(migration.sql)
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name)
            VALUES (%s, %s)
            """,
            (migration.version, migration.name),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
