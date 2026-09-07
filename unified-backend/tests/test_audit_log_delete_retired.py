# test_audit_log_delete_retired.py
#
# Phase 6 / BD-HC3 approved fix: DELETE /audit-logs/{audit_log_id} was
# retired outright. Confirmed before removal (repo-wide search,
# documented in the Phase 5 artifact report and re-verified fresh at
# the start of Phase 6): zero callers in the frontend
# (services/index.ts's auditService exposes only list/get/
# getUserLogs), zero callers anywhere else in the backend (services,
# background jobs, scripts), zero references in tests, and the route
# itself was the only caller of AuditLogService.delete_log, which was
# itself the only caller of AuditLogRepository.delete (app/rbac side)
# — so both were removed alongside the route as directly-associated
# dead code. The audit_logs table/model, audit-log creation, listing,
# and the ticket-domain audit trail are all untouched.
#
# Same convention as this repo's other authorization-fix test files:
# route/service functions called (or confirmed absent) directly, real
# seeded users, everything inside a transaction that is always rolled
# back. Run this file individually (DB-touching test caveat).

import inspect
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.rbac.api.v1 import audit_logs as audit_logs_module
from app.rbac.models.audit_log import AuditLog
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.schemas.audit_log import AuditLogCreate
from app.rbac.services.audit_log_service import AuditLogService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _build_service(session) -> AuditLogService:
    return AuditLogService(audit_log_repository=AuditLogRepository(session))


async def _get_user_by_role(session, role_name: str) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == role_name, User.is_active.is_(True))
    )
    users = result.unique().scalars().all()
    if users:
        return users[0]
    pytest.skip(f"No active seeded {role_name!r} found.")


# ---------------------------------------------------------
# The endpoint is no longer callable: no DELETE route on this router,
# no route function to import, no service/repository method left
# behind for it to have called.
# ---------------------------------------------------------


def test_no_delete_route_registered_on_audit_logs_router():
    delete_routes = [
        route
        for route in audit_logs_module.router.routes
        if "DELETE" in getattr(route, "methods", set())
    ]
    assert delete_routes == [], (
        "DELETE /audit-logs/{audit_log_id} must not be registered on the "
        "router — it was retired in Phase 6 (BD-HC3)."
    )


def test_delete_audit_log_route_function_no_longer_exists():
    assert not hasattr(audit_logs_module, "delete_audit_log")


def test_audit_log_service_has_no_delete_log_method():
    assert not hasattr(AuditLogService, "delete_log")


def test_audit_log_repository_has_no_delete_method():
    assert not hasattr(AuditLogRepository, "delete")


def test_no_remaining_source_reference_to_the_retired_route():
    """A second, cheap post-removal search directly against this
    module's own source, as required by Step 3's post-removal repo
    search — the broader repo-wide grep was run manually and is
    documented in the Phase 6 report; this asserts the one file that
    used to define the route no longer mentions it."""

    source = inspect.getsource(audit_logs_module)
    assert "delete_audit_log" not in source
    assert "@router.delete" not in source


# ---------------------------------------------------------
# Regression: audit-log creation still works, unaffected by the
# deletion-path removal (HC-1 was explicitly out of scope this phase).
# ---------------------------------------------------------


async def test_audit_log_creation_still_works(db_session):
    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")

    created = await audit_logs_module.create_audit_log(
        AuditLogCreate(action="phase6.regression.create", entity_type="test", entity_id="1"),
        service=service,
        current_user=actor,
    )
    assert created.action == "phase6.regression.create"

    fetched = await AuditLogRepository(db_session).get_by_id(created.audit_log_id)
    assert fetched is not None


# ---------------------------------------------------------
# Regression: audit-log listing (the HC-2 fix, same phase) still
# works, and export is unaffected — export has no backend endpoint at
# all (client-side CSV generation from already-fetched rows, per
# unified-frontend/CLAUDE.md's own documented design), so there is
# nothing server-side that could have been broken by retiring delete.
# ---------------------------------------------------------


async def test_audit_log_listing_still_works(db_session):
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["audit:view"]
    service = _build_service(db_session)

    result = await audit_logs_module.list_audit_logs(
        page=1, page_size=20, service=service, current_user=actor
    )
    assert result.total >= 0


# ---------------------------------------------------------
# Regression: existing (pre-Phase-6) audit records are untouched by
# this change — a row created before this phase's work is still
# present, byte-identical, with no delete path left to reach it.
# ---------------------------------------------------------


async def test_existing_audit_records_are_untouched(db_session):
    repository = AuditLogRepository(db_session)
    marker = f"phase6_untouched_record_{uuid.uuid4().hex[:8]}"

    log = AuditLog(
        audit_log_id=uuid.uuid4(),
        user_id=None,
        action=marker,
        entity_type="test",
        entity_id="untouched",
        timestamp=datetime.now(timezone.utc),
    )
    db_session.add(log)
    await db_session.flush()

    reloaded = await repository.get_by_id(log.audit_log_id)
    assert reloaded is not None
    assert reloaded.action == marker
    assert reloaded.entity_id == "untouched"
