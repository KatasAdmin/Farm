"""Reuse PostgreSQL sessions; each checkout keeps its own transaction boundary."""
import atexit
import os
import threading
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool = None
_lock = threading.Lock()


def connection():
    global _pool
    with _lock:
        if _pool is None:
            _pool = ConnectionPool(
                os.environ['DATABASE_URL'], min_size=2, max_size=12,
                timeout=10, max_idle=120, max_lifetime=1800, open=True,
                kwargs={'row_factory':dict_row, 'connect_timeout':10,
                        'options':'-c statement_timeout=30000 -c lock_timeout=10000 '
                                  '-c idle_in_transaction_session_timeout=30000 '
                                  '-c transaction_timeout=60000'})
    return _pool.connection()


def close():
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.close()


atexit.register(close)
