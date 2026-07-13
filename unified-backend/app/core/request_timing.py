"""
Temporary, per-request named-stage timing — added specifically to
diagnose the real ~10-30s Interactions-tab load time report against
the actual running app (not an isolated benchmark). Same ContextVar
pattern as app/database/timing.py's total `db` time, generalized to
multiple named stages (auth, visibility, query, count, enrichment,
serialization) so Server-Timing can report each one individually
instead of only `total`/`db`.

Intentionally lightweight: a plain dict behind a ContextVar, reset by
the same ServerTimingMiddleware that already resets `db_time_ms` per
request (see app/main.py) — correctness under concurrency relies on
the same fact documented there (each request is its own asyncio Task,
so each gets its own copy of the ContextVar's dict).
"""

import time
from contextlib import contextmanager
from contextvars import ContextVar

_stage_times: ContextVar[dict] = ContextVar("stage_times", default=None)


def reset_stage_times() -> None:
    _stage_times.set({})


def get_stage_times() -> dict:
    return _stage_times.get() or {}


def record_stage(name: str, duration_ms: float) -> None:
    stages = _stage_times.get()
    if stages is None:
        return  # reset_stage_times() wasn't called (e.g. outside a request) — no-op
    stages[name] = stages.get(name, 0.0) + duration_ms


@contextmanager
def timed_stage(name: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        record_stage(name, (time.perf_counter() - start) * 1000)
