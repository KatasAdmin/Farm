"""Reuse must keep commit/rollback boundaries identical to a fresh connection."""
import os
import unittest
from unittest.mock import patch
import database_pool
from psycopg_pool import ConnectionPool


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'Requires isolated PostgreSQL')
class PoolTransactions(unittest.TestCase):
    def test_reuse_commits_and_rolls_back_without_leaking_transactions(self):
        with ConnectionPool(os.environ['TEST_DATABASE_URL'],min_size=1,max_size=1,
                            kwargs={'row_factory':database_pool.dict_row}) as pool:
            with patch.object(database_pool,'_pool',pool):
                with database_pool.connection() as c:
                    pid=c.execute('SELECT pg_backend_pid() AS id').fetchone()['id']
                    c.execute('CREATE TEMP TABLE pool_boundary_test(value integer)')
                    c.execute('INSERT INTO pool_boundary_test VALUES(1)')
                with self.assertRaises(RuntimeError):
                    with database_pool.connection() as c:
                        self.assertEqual(c.execute('SELECT pg_backend_pid() AS id').fetchone()['id'],pid)
                        c.execute('INSERT INTO pool_boundary_test VALUES(2)')
                        raise RuntimeError('Abort the second transaction')
                with database_pool.connection() as c:
                    self.assertEqual(c.execute('SELECT sum(value) AS n FROM pool_boundary_test').fetchone()['n'],1)
                    c.execute('DROP TABLE pool_boundary_test')
