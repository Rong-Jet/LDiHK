from __future__ import annotations

import os
import unittest
from unittest import mock

from backend import db, db_pool


URL_A = "postgresql://user:secret@db-a.example/ldihk"
URL_B = "postgresql://user:secret@db-b.example/ldihk"


class FakePool:
    def __init__(self, url: str, size: int):
        self.url = url
        self.size = size
        self.closed = False

    def getconn(self):
        return ("pooled", self.url)

    def close(self):
        self.closed = True


class PooledConnectTests(unittest.TestCase):
    def setUp(self):
        db_pool.close_pool()
        self.addCleanup(db_pool.close_pool)

    def test_missing_database_url_is_a_config_error(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": ""}):
            with self.assertRaises(db.DatabaseConfigError):
                db_pool.pooled_connect()

    def test_pool_size_zero_opens_a_plain_connection(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": URL_A, "DATABASE_POOL_SIZE": "0"}):
            with mock.patch.object(db, "connect", return_value="direct") as connect:
                self.assertEqual(db_pool.pooled_connect(), "direct")
        connect.assert_called_once_with(URL_A)

    def test_pool_is_created_once_and_replaced_when_the_url_changes(self):
        with mock.patch.object(db_pool, "_create_pool", side_effect=FakePool) as create:
            with mock.patch.dict(os.environ, {"DATABASE_URL": URL_A, "DATABASE_POOL_SIZE": "3"}):
                self.assertEqual(db_pool.pooled_connect(), ("pooled", URL_A))
                self.assertEqual(db_pool.pooled_connect(), ("pooled", URL_A))
            first_pool = db_pool._pool
            with mock.patch.dict(os.environ, {"DATABASE_URL": URL_B}):
                self.assertEqual(db_pool.pooled_connect(), ("pooled", URL_B))

        self.assertEqual([call.args for call in create.call_args_list], [(URL_A, 3), (URL_B, 4)])
        self.assertTrue(first_pool.closed)

    def test_connection_kwargs_keep_pooler_safe_settings(self):
        with mock.patch.dict(os.environ, {"DATABASE_STATEMENT_TIMEOUT_MS": "1500"}):
            kwargs = db.connection_kwargs()
        self.assertIsNone(kwargs["prepare_threshold"])
        self.assertFalse(kwargs["autocommit"])
        self.assertEqual(kwargs["options"], "-c statement_timeout=1500")


if __name__ == "__main__":
    unittest.main()
