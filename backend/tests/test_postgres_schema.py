import os
import re
import unittest
from contextlib import closing

from backend.db import (
    DatabaseConfigError,
    connect,
    get_database_url,
    list_migrations,
    run_migrations,
)


REQUIRED_TABLES = {
    "users",
    "imports",
    "source_files",
    "usage_events",
    "subscriptions",
    "youtube_videos",
    "youtube_channels",
    "enrichment_jobs",
    "import_warnings",
}


def compact_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.lower())


class PostgresSchemaContractTests(unittest.TestCase):
    def test_migration_contract_defines_core_tables_constraints_and_indexes(self):
        migrations = list_migrations()

        self.assertEqual([migration.version for migration in migrations], ["001"])
        sql = compact_sql("\n".join(migration.sql for migration in migrations))

        for table in REQUIRED_TABLES:
            self.assertIn(f"create table if not exists {table}", sql)

        self.assertIn("unique (user_id, event_fingerprint)", sql)
        self.assertIn("unique (user_id, channel_id)", sql)
        self.assertIn(
            "create index if not exists idx_imports_status "
            "on imports (status, created_at)",
            sql,
        )
        self.assertIn(
            "create index if not exists idx_enrichment_jobs_status "
            "on enrichment_jobs (status, run_after)",
            sql,
        )

    def test_database_url_is_required(self):
        with self.assertRaisesRegex(DatabaseConfigError, "DATABASE_URL"):
            get_database_url({})

    def test_database_url_must_be_postgres(self):
        with self.assertRaisesRegex(DatabaseConfigError, "Postgres"):
            get_database_url({"DATABASE_URL": "sqlite:///tmp/app.db"})

    @unittest.skipUnless(
        os.environ.get("TEST_DATABASE_URL"),
        "set TEST_DATABASE_URL to run Postgres schema integration tests",
    )
    def test_run_migrations_creates_schema_in_postgres(self):
        with closing(connect(os.environ["TEST_DATABASE_URL"])) as connection:
            run_migrations(connection)

            table_rows = connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = ANY(%s)
                """,
                (sorted(REQUIRED_TABLES),),
            ).fetchall()
            self.assertEqual({row[0] for row in table_rows}, REQUIRED_TABLES)

            constraint_rows = connection.execute(
                """
                SELECT rel.relname, pg_get_constraintdef(con.oid)
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                WHERE nsp.nspname = 'public'
                  AND con.contype = 'u'
                  AND rel.relname IN ('usage_events', 'subscriptions')
                """
            ).fetchall()
            constraints_by_table: dict[str, set[str]] = {}
            for table_name, constraint_definition in constraint_rows:
                constraints_by_table.setdefault(table_name, set()).add(
                    constraint_definition
                )
            self.assertIn(
                "UNIQUE (user_id, event_fingerprint)",
                constraints_by_table.get("usage_events", set()),
            )
            self.assertIn(
                "UNIQUE (user_id, channel_id)",
                constraints_by_table.get("subscriptions", set()),
            )

            index_rows = connection.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname IN (
                    'idx_imports_status',
                    'idx_enrichment_jobs_status'
                  )
                """
            ).fetchall()
            self.assertEqual(
                {row[0] for row in index_rows},
                {"idx_imports_status", "idx_enrichment_jobs_status"},
            )
