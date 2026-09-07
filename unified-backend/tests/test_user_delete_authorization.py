# test_user_delete_authorization.py
#
# Phase 2A P0 fix: DELETE /users/{user_id} previously had no backend
# authorization check at all (every sibling route on this same file —
# create/list/get/update/activate/deactivate — already called
# ensure_has_permission; delete alone did not). This file covers the
# added `ensure_has_permission(current_user, "user:delete")` check in
# app.rbac.api.v1.users.delete_user.
#
# Calls the route function directly (bypassing FastAPI's HTTP layer,
# not the check itself — the check lives in the route, same place
# every sibling route's check already lives), mirroring the existing
# convention in test_user_creation_role_matrix.py /
# test_view_escalated_permission.py: real seeded users from the dev
# DB, `.permissions` set explicitly per test (the JWT-derived
# attribute `has_permission` reads — see access_control.py), inside a
# transaction that is always rolled back.
#
# Per this repo's own documented pytest-asyncio caveat (root
# CLAUDE.md's "SLA & Escalation" section), DB-touching test files can
# hang if run in the same process as other DB-touching files — run
# this file individually.

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.rbac.api.v1.users import delete_user
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.category_repository import CategoryRepository
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.user import UserCreate
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.organization_service import OrganizationService
from app.rbac.services.user_service import UserService
from app.ticketing.models.client import Client
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.user_repository import UserRepository as TicketingUserRepository
from app.ticketing.services.client_service import ClientService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _build_user_service(session) -> UserService:
    user_repository = UserRepository(session)
    role_repository = RoleRepository(session)
    return UserService(
        user_repository=user_repository,
        role_repository=role_repository,
        category_repository=CategoryRepository(session),
        audit_log_service=AuditLogService(audit_log_repository=AuditLogRepository(session)),
        client_repository=ClientRepository(session),
        client_service=ClientService(
            client_repository=ClientRepository(session),
            user_repository=TicketingUserRepository(session),
        ),
        organization_service=OrganizationService(
            user_repository=user_repository,
            role_repository=role_repository,
            reporting_manager_repository=ReportingManagerRepository(session),
        ),
    )


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


async def _make_throwaway_user(session, service, *, role_name: str = "Site Lead") -> User:
    """A real, freshly-created target user — never one of the real
    seeded accounts — so delete tests never touch production data even
    inside a rolled-back transaction. Defaults to Site Lead: per
    test_user_creation_role_matrix.py, the only internal role needing
    no category/manager/reporting-manager, keeping this helper minimal
    and unrelated to the authorization behavior under test."""

    target_role = await _get_role(session, role_name)
    unique = uuid.uuid4().hex[:10]
    creator = await _get_user_by_role(session, "Super Admin")

    created = await service.create_user(
        UserCreate(
            name=f"Throwaway Delete-Target {unique}",
            email=f"throwaway-delete-{unique}@example.com",
            password="password123",
            role_id=target_role.role_id,
            is_active=True,
            designation="Test",
            alternate_email=f"throwaway-delete-alt-{unique}@example.com",
            employee_number=f"TEST-DEL-{unique}",
        ),
        actor=creator,
    )
    return await UserRepository(session).get_by_id(created["user_id"] if isinstance(created, dict) else created.user_id)


# ---------------------------------------------------------
# Regression: seed grants unchanged (Super Admin / Site Lead already
# hold user:delete — this fix must not depend on widening either)
# ---------------------------------------------------------


async def test_super_admin_role_holds_user_delete(db_session):
    role = await _get_role(db_session, "Super Admin")
    if role.name != "Super Admin":
        pytest.skip("unexpected role")
    # Super Admin's grant is seed.py's literal "all" — spot-check via
    # the role-permission table directly rather than assuming.
    names = {
        p.permission_name
        for p in await RolePermissionRepository(db_session).get_permissions_by_role(role.role_id)
    }
    assert "user:delete" in names


async def test_site_lead_role_holds_user_delete(db_session):
    role = await _get_role(db_session, "Site Lead")
    names = {
        p.permission_name
        for p in await RolePermissionRepository(db_session).get_permissions_by_role(role.role_id)
    }
    assert "user:delete" in names


# ---------------------------------------------------------
# Positive: holding user:delete succeeds
# ---------------------------------------------------------


async def test_actor_with_user_delete_permission_can_delete(db_session):
    service = _build_user_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["user:delete"]

    target = await _make_throwaway_user(db_session, service)

    await delete_user(target.user_id, service=service, current_user=actor)

    assert await UserRepository(db_session).get_by_id(target.user_id) is None


# ---------------------------------------------------------
# Negative: every role without user:delete is rejected, and the
# target survives (proves the check runs before the destructive call)
# ---------------------------------------------------------


@pytest.mark.parametrize("actor_role_name", ["Account Manager", "Team Lead", "Staff"])
async def test_actor_without_user_delete_permission_is_denied(db_session, actor_role_name):
    service = _build_user_service(db_session)
    actor = await _get_user_by_role(db_session, actor_role_name)
    actor.permissions = []  # explicitly holds nothing, regardless of real seed grant

    target = await _make_throwaway_user(db_session, service)

    with pytest.raises(HTTPException) as exc_info:
        await delete_user(target.user_id, service=service, current_user=actor)
    assert exc_info.value.status_code == 403

    # The destructive call never ran.
    assert await UserRepository(db_session).get_by_id(target.user_id) is not None


async def test_actor_with_unrelated_permissions_is_still_denied(db_session):
    """Holding other user:* permissions (e.g. user:update) must not
    imply user:delete — the two are deliberately separate grants."""

    service = _build_user_service(db_session)
    actor = await _get_user_by_role(db_session, "Team Lead")
    actor.permissions = ["user:view", "user:update"]

    target = await _make_throwaway_user(db_session, service)

    with pytest.raises(HTTPException) as exc_info:
        await delete_user(target.user_id, service=service, current_user=actor)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------
# Regression: existing client-deactivate business rule (not a hard
# delete) still fires for a Client-role target, once authorized —
# proves the new check is layered before existing logic, not in place
# of it.
# ---------------------------------------------------------


async def test_authorized_delete_of_client_role_deactivates_not_hard_deletes(db_session):
    account_manager = await _get_user_by_role(db_session, "Account Manager")

    unique = uuid.uuid4().hex[:8]
    client = Client(
        client_id=uuid.uuid4(),
        name=f"Throwaway Delete-Target Client {unique}",
        inbox_email=f"throwaway-client-delete-{unique}@example.com",
        account_manager_id=account_manager.user_id,
        is_active=True,
    )
    db_session.add(client)
    await db_session.flush()

    service = _build_user_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["user:delete"]

    await delete_user(client.client_id, service=service, current_user=actor)

    reloaded = await ClientRepository(db_session).get_by_id(client.client_id)
    assert reloaded is not None  # not hard-deleted
    assert reloaded.is_active is False  # existing deactivate-on-delete rule preserved
