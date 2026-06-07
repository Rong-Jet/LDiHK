from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse


DATABASE_URL_ENV = "DATABASE_URL"
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class DatabaseConfigError(RuntimeError):
    pass


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


def connect(database_url: str | None = None, *, autocommit: bool = False):
    database_url = get_database_url() if database_url is None else database_url.strip()
    _validate_postgres_url(database_url)
    try:
        import psycopg
    except ModuleNotFoundError as error:  # pragma: no cover - depends on env setup
        raise RuntimeError(
            "psycopg is required for Postgres connections; run `uv sync` first"
        ) from error
    return psycopg.connect(database_url, autocommit=autocommit)


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
        connection = connect(database_url)

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
