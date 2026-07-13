"""
Per-request DB time accounting, backing the `db` phase of the
Server-Timing header (see app/main.py). A ContextVar (not a plain
module global) is required for correctness under concurrency: each
FastAPI request runs as its own asyncio Task, and asyncio copies the
ContextVar context per-Task, so concurrent requests' DB-time totals
never bleed into each other even though they share one engine/event
listener pair.

SQLAlchemy's async engine still executes the underlying DBAPI calls
through a sync codepath (via greenlet) — `before_cursor_execute`/
`after_cursor_execute` are DBAPI-level events that fire correctly for
`create_async_engine` as long as they're registered on `.sync_engine`,
which is the standard, documented way to instrument query time under
the async engine.
"""

import time
from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

_db_time_ms: ContextVar[float] = ContextVar("db_time_ms", default=0.0)
_query_start: ContextVar[float] = ContextVar("query_start", default=0.0)


def reset_db_time() -> None:
    _db_time_ms.set(0.0)


def get_db_time_ms() -> float:
    return _db_time_ms.get()


def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    _query_start.set(time.perf_counter())


def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    start = _query_start.get()
    if start:
        _db_time_ms.set(_db_time_ms.get() + (time.perf_counter() - start) * 1000)


def register_db_timing(engine: AsyncEngine) -> None:
    event.listen(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(engine.sync_engine, "after_cursor_execute", _after_cursor_execute)
