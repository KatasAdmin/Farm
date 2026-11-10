"""Reuse PostgreSQL sessions; each checkout keeps its own transaction boundary."""
import atexit
import os
import threading
import logging
import time
from contextlib import contextmanager
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool = None
_lock = threading.Lock()
_log = logging.getLogger('farm.database_pool')


@contextmanager
def connection():
    global _pool
    with _lock:
        if _pool is None:
            _pool = ConnectionPool(
                os.environ['DATABASE_URL'], min_size=2, max_size=16,
                timeout=10, max_idle=120, max_lifetime=1800, open=True,
                kwargs={'row_factory':dict_row, 'connect_timeout':10,
                        'options':'-c statement_timeout=30000 -c lock_timeout=10000 '
                                  '-c idle_in_transaction_session_timeout=15000 '
                                  '-c transaction_timeout=30000'})
    started = time.monotonic()
    try:
        with _pool.connection() as conn:
            elapsed = time.monotonic() - started
            if elapsed > 1:
                _log.warning('farm_db_checkout_slow wait_ms=%d stats=%s',int(elapsed*1000),_pool.get_stats())
            yield conn
    except Exception as exc:
        if type(exc).__name__ in ('PoolTimeout', 'OperationalError'):
            _log.error('farm_db_pool_error type=%s stats=%s',type(exc).__name__,_pool.get_stats())
        raise


def close():
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.close()


atexit.register(close)
