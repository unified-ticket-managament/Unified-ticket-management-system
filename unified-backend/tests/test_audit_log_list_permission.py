# test_audit_log_list_permission.py
#
# Phase 6 / BD-HC2 approved fix: GET /audit-logs (list_audit_logs)
# previously gated on a hardcoded `role.name != "Super Admin"` check —
# the only route on this router that didn't already use
# ensure_has_permission, unlike its siblings get_audit_log/
# get_user_audit_logs (both already audit:view-gated). This was a real
# functional gap: the RBAC-native Audit Logs frontend page
# (audit-logs/page.tsx) gates itself on hasPermission("audit:view") and
# Site Lead holds audit:view by default, so a Site Lead passed the
# frontend gate and then had this exact route 403 on them, rendering a
# hard ErrorState. Fixed by replacing the hardcoded check with
# ensure_has_permission(current_user, "audit:view") — the same helper
# and same permission name already used by this file's own sibling
# routes.
#
# create_audit_log and the (now-retired, see
# test_audit_log_delete_retired.py) delete_audit_log route are
# deliberately untouched by this change — their own hardcoded
# Super-Admin-only checks remain exactly as before; this file covers
# list_audit_logs only.
#
# Same convention as test_permission_catalog_authorization.py: route
# function called directly, real seeded users, `.permissions` set
# explicitly per test, everything inside a transaction that is always
# rolled back. Run this file individually (DB-touching test caveat).

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.rbac.api.v1.audit_logs import list_audit_logs
from app.rbac.models.audit_log import AuditLog
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.repositories.role_repository import RoleRepository
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


async def _get_role(session, role_name: str) -> Role:
    role = await RoleRepository(session).get_by_name(role_name)
    if role is None:
        pytest.skip(f"No {role_name!r} role seeded.")
    return role


# ---------------------------------------------------------
# Regression: seed grants unchanged — this fix must not depend on
# widening anyone's default permission set.
# ---------------------------------------------------------


async def test_super_admin_role_holds_audit_view(db_session):
    role = await _get_role(db_session, "Super Admin")
    names = {
        p.permission_name
        for p in await RolePermissionRepository(db_session).get_permissions_by_role(role.role_id)
    }
    assert "audit:view" in names


async def test_site_lead_role_holds_audit_view(db_session):
    role = await _get_role(db_session, "Site Lead")
    names = {
        p.permission_name
        for p in await RolePermissionRepository(db_session).get_permissions_by_role(role.role_id)
    }
    assert "audit:view" in names


# ---------------------------------------------------------
# Positive: Super Admin with audit:view -> allowed (unchanged from
# before this fix — Super Admin passed the old hardcoded check too).
# ---------------------------------------------------------


async def test_super_admin_with_audit_view_can_list(db_session):
    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["audit:view"]

    result = await list_audit_logs(page=1, page_size=20, service=service, current_user=actor)
    assert result.total >= 0


# ---------------------------------------------------------
# Positive: Site Lead with audit:view -> allowed. This is the exact
# case that was previously, incorrectly, a 403 — the core fix under
# test.
# ---------------------------------------------------------


async def test_site_lead_with_audit_view_can_list(db_session):
    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Site Lead")
    actor.permissions = ["audit:view"]

    result = await list_audit_logs(page=1, page_size=20, service=service, current_user=actor)
    assert result.total >= 0


# ---------------------------------------------------------
# Negative: a role without audit:view is still denied, even though the
# old hardcoded check would have denied every non-Super-Admin role for
# a different reason — proves this is now a real permission check, not
# a disguised role check.
# ---------------------------------------------------------


@pytest.mark.parametrize("actor_role_name", ["Account Manager", "Team Lead", "Staff"])
async def test_actor_without_audit_view_is_denied(db_session, actor_role_name):
    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, actor_role_name)
    actor.permissions = []  # explicitly holds nothing, regardless of real seed grant

    with pytest.raises(HTTPException) as exc_info:
        await list_audit_logs(page=1, page_size=20, service=service, current_user=actor)
    assert exc_info.value.status_code == 403


async def test_actor_with_unrelated_permission_is_still_denied(db_session):
    """Holding some other permission must not imply audit:view."""

    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Team Lead")
    actor.permissions = ["user:view", "ticket:view_own"]

    with pytest.raises(HTTPException) as exc_info:
        await list_audit_logs(page=1, page_size=20, service=service, current_user=actor)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------
# Proves this is a real permission check, not a role check in
# disguise: a role that does NOT default-hold audit:view (Staff) still
# succeeds once explicitly granted it — mirrors the established
# pattern in test_permission_catalog_authorization.py.
# ---------------------------------------------------------


async def test_actor_granted_audit_view_via_override_can_list(db_session):
    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Staff")
    actor.permissions = ["audit:view"]  # simulates an active personal override grant

    result = await list_audit_logs(page=1, page_size=20, service=service, current_user=actor)
    assert result.total >= 0


# ---------------------------------------------------------
# Regression: existing pagination behavior is unaffected by this
# change — page/page_size still slice the same underlying data the
# same way. Uses throwaway rows (never touching real audit history)
# inside the rolled-back transaction.
# ---------------------------------------------------------


async def test_pagination_behavior_unchanged(db_session):
    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["audit:view"]

    marker = f"phase6_pagination_test_{uuid.uuid4().hex[:8]}"
    base_time = datetime.now(timezone.utc)
    for i in range(5):
        db_session.add(
            AuditLog(
                audit_log_id=uuid.uuid4(),
                user_id=None,
                action=marker,
                entity_type="test",
                entity_id=str(i),
                timestamp=base_time - timedelta(seconds=i),
            )
        )
    await db_session.flush()

    total_before = (await list_audit_logs(page=1, page_size=1000, service=service, current_user=actor)).total

    page_1 = await list_audit_logs(page=1, page_size=2, service=service, current_user=actor)
    page_2 = await list_audit_logs(page=2, page_size=2, service=service, current_user=actor)

    assert page_1.total == total_before
    assert page_2.total == total_before
    assert len(page_1.logs) == 2
    # No overlap between consecutive pages.
    page_1_ids = {log.audit_log_id for log in page_1.logs}
    page_2_ids = {log.audit_log_id for log in page_2.logs}
    assert page_1_ids.isdisjoint(page_2_ids)


# ---------------------------------------------------------
# Regression: create_audit_log (HC-1, not in scope for this phase) and
# the sibling audit:view-gated routes are unaffected by this change.
# ---------------------------------------------------------


async def test_create_audit_log_still_hardcoded_super_admin_only(db_session):
    """HC-1 was explicitly out of scope for Phase 6 — confirms
    create_audit_log's own hardcoded check is untouched."""

    from app.rbac.api.v1.audit_logs import create_audit_log
    from app.rbac.schemas.audit_log import AuditLogCreate

    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Site Lead")
    actor.permissions = ["audit:view"]  # holds the new list permission, NOT Super Admin

    with pytest.raises(HTTPException) as exc_info:
        await create_audit_log(
            AuditLogCreate(action="test.action", entity_type="test", entity_id="1"),
            service=service,
            current_user=actor,
        )
    assert exc_info.value.status_code == 403


async def test_get_audit_log_and_get_user_audit_logs_still_audit_view_gated(db_session):
    """Confirms this phase didn't touch the two sibling routes that
    were already correctly audit:view-gated before Phase 6."""

    from app.rbac.api.v1.audit_logs import get_audit_log, get_user_audit_logs

    service = _build_service(db_session)
    actor = await _get_user_by_role(db_session, "Team Lead")
    actor.permissions = []

    with pytest.raises(HTTPException) as exc_info:
        await get_audit_log(uuid.uuid4(), service=service, current_user=actor)
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        await get_user_audit_logs(uuid.uuid4(), service=service, current_user=actor)
    assert exc_info.value.status_code == 403
