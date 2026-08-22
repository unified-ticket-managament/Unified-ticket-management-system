# impersonation_context.py
"""
A per-request signal, carried outside the normal function-parameter
chain, so both AuditLogRepository.create() implementations (rbac's and
ticketing's — app/rbac/repositories/audit_log_repository.py,
app/ticketing/repositories/audit_log_repository.py) can stamp "who was
really behind this" onto an audit row without changing the signature
of AuditLogService.log_event()/create_log(), which ~30+ existing call
sites across both domains already call with a fixed set of positional/
keyword arguments.

Why a ContextVar and not a parameter: threading a new
impersonator_id/impersonator_name pair through every one of those call
sites (and everything upstream of them, transitively) would touch far
more files than the actual feature warrants. A ContextVar set once,
per request, in app/dependencies/auth.py's _authenticate_token — the
one place that already resolves "who is making this request" — reaches
every downstream write with no other code needing to know it exists.

Safe under FastAPI/Starlette's ASGI model: each inbound request runs in
its own asyncio Task, and contextvars are copied at Task-creation time
with no back-propagation between concurrent requests — the same
isolation property app/core/rbac_cache.py's per-process design already
relies on, just one level more granular (per-request instead of
per-process). _authenticate_token sets this unconditionally on every
call (to the real tuple, or explicitly to None) rather than only in the
impersonating branch, so correctness never depends on assuming a fresh
Task starts with no leftover value — see that function's own comment.
"""

from contextvars import ContextVar
from uuid import UUID

_impersonator: ContextVar[tuple[UUID, str] | None] = ContextVar(
    "_impersonator", default=None
)


def set_impersonator(actor_id: UUID | None, actor_name: str | None) -> None:
    """
    Call with (None, None) — or just omit actor_id — to explicitly
    clear the signal for a non-impersonated request.
    """

    if actor_id is None:
        _impersonator.set(None)
    else:
        _impersonator.set((actor_id, actor_name or ""))


def get_impersonator() -> tuple[UUID, str] | None:
    """
    Returns (impersonator_user_id, impersonator_name) if the current
    request is an impersonated session, else None. Read by
    AuditLogRepository.create() on both the rbac and ticketing sides at
    the moment an audit row is written — never by any authorization or
    visibility check, which is what keeps the impersonating admin's own
    privileges from leaking into the impersonated request.
    """

    return _impersonator.get()
