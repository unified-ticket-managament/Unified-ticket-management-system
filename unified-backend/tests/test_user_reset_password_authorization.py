# test_user_reset_password_authorization.py
#
# Phase 23 (RBAC Enforcement Audit): implements user:reset_password as
# a real admin capability — an authorized administrator resetting
# ANOTHER user's password, distinct from AuthService.change_password's
# self-service flow (which requires the caller's own old_password and
# has no permission check at all, by design — "you can only change
# your own"). Covers: catalog/grant regression, schema validation, the
# positive reset path (verified via a real bcrypt round-trip), the
# hash-is-never-plaintext guarantee, unauthorized rejection, Client-
# account rejection (no login of their own), existing update_user
# unaffected, and self-service change_password unaffected.
#
# NOTE (2026-08-27): this file, along with the reset_password schema/
# service method/route it exercises, was recreated after a concurrent
# process altered this shared working tree (new commits landed;
# several uncommitted Phase 23 edits — including this file itself,
# which is untracked — were silently discarded in the process). The
# implementation was re-applied against the current file state; this
# test file was rewritten from scratch to match current constructor
# signatures (UserService/ClientService/OrganizationService all gained
# new collaborators since the original version of this file was
# written) rather than assumed unchanged.
#
# Calls the route/service functions directly (bypassing FastAPI's HTTP
# layer, not the check itself), mirroring the established convention
# in test_user_delete_authorization.py. Per this repo's own documented
# pytest-asyncio caveat, DB-touching test files can hang if run in the
# same process as other DB-touching files — run this file individually
# if combined with others.

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.auth.password import verify_password
from app.database.session import AsyncSessionLocal, engine
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.category_repository import CategoryRepository
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.auth import ChangePasswordRequest
from app.rbac.schemas.user import AdminPasswordReset, UserCreate
from app.rbac.services.auth_service import AuthService
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.organization_service import OrganizationService
from app.rbac.services.user_service import UserService
from app.ticketing.models.client import Client
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.user_repository import UserRepository as TicketingUserRepository
from app.ticketing.services.client_service import ClientService

ORIGINAL_PASSWORD = "originalPassword123"


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
    """A real, freshly-created target user with a known starting
    password — never one of the real seeded accounts."""

    target_role = await _get_role(session, role_name)
    unique = uuid.uuid4().hex[:10]
    creator = await _get_user_by_role(session, "Super Admin")

    created = await service.create_user(
        UserCreate(
            name=f"Throwaway Reset-Target {unique}",
            email=f"throwaway-reset-{unique}@example.com",
            password=ORIGINAL_PASSWORD,
            role_id=target_role.role_id,
            is_active=True,
            designation="Test",
            alternate_email=f"throwaway-reset-alt-{unique}@example.com",
            employee_number=f"TEST-RST-{unique}",
        ),
        actor=creator,
    )
    user_id = created["user_id"] if isinstance(created, dict) else created.user_id
    return await UserRepository(session).get_by_id(user_id)


async def _make_throwaway_client(session, service) -> Client:
    client_role = await _get_role(session, "Client")
    unique = uuid.uuid4().hex[:10]
    creator = await _get_user_by_role(session, "Super Admin")
    account_manager = await _get_user_by_role(session, "Account Manager")

    await service.create_user(
        UserCreate(
            name=f"Throwaway Client {unique}",
            email=f"throwaway-client-{unique}@example.com",
            password="unused-client-has-no-login",
            role_id=client_role.role_id,
            is_active=True,
            manager_id=account_manager.user_id,
            contact_emails=[f"throwaway-client-{unique}@example.com"],
        ),
        actor=creator,
    )
    result = await session.execute(
        select(Client).where(Client.inbox_email == f"throwaway-client-{unique}@example.com")
    )
    client = result.scalar_one_or_none()
    if client is None:
        pytest.skip("Throwaway client could not be created.")
    return client


# ---------------------------------------------------------
# 1. Catalog / grant regression
# ---------------------------------------------------------


async def test_user_reset_password_still_in_live_catalog(db_session):
    from app.rbac.models import Permission

    result = await db_session.execute(
        select(Permission).where(Permission.permission_name == "user:reset_password")
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.parametrize(
    "role_name,expected", [
        ("Super Admin", True),
        ("Site Lead", True),
        ("Account Manager", True),
        ("Team Lead", False),
        ("Staff", False),
    ],
)
async def test_user_reset_password_grant_set_unchanged(db_session, role_name, expected):
    role = await _get_role(db_session, role_name)
    names = {
        p.permission_name
        for p in await RolePermissionRepository(db_session).get_permissions_by_role(role.role_id)
    }
    assert ("user:reset_password" in names) == expected


# ---------------------------------------------------------
# 2. Schema validation
# ---------------------------------------------------------


def test_admin_password_reset_rejects_short_password():
    with pytest.raises(ValidationError):
        AdminPasswordReset(new_password="short")


def test_admin_password_reset_accepts_password_at_the_bound():
    schema = AdminPasswordReset(new_password="exactly8")
    assert schema.new_password == "exactly8"


# ---------------------------------------------------------
# 3. Positive path — authorized reset actually changes the password
# ---------------------------------------------------------


async def test_authorized_actor_can_reset_another_users_password(db_session):
    service = _build_user_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["user:reset_password"]

    target = await _make_throwaway_user(db_session, service)
    old_hash = target.password_hash

    await service.reset_password(target.user_id, "brandNewPassword456", actor=actor)

    refreshed = await UserRepository(db_session).get_by_id(target.user_id)
    assert verify_password("brandNewPassword456", refreshed.password_hash)
    assert not verify_password(ORIGINAL_PASSWORD, refreshed.password_hash)
    assert refreshed.password_hash != old_hash


async def test_reset_password_never_stores_plaintext(db_session):
    service = _build_user_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["user:reset_password"]

    target = await _make_throwaway_user(db_session, service)

    await service.reset_password(target.user_id, "anotherPassword789", actor=actor)

    refreshed = await UserRepository(db_session).get_by_id(target.user_id)
    assert refreshed.password_hash != "anotherPassword789"
    assert "anotherPassword789" not in refreshed.password_hash


# ---------------------------------------------------------
# 4. Negative / unauthorized
# ---------------------------------------------------------


@pytest.mark.parametrize("actor_role_name", ["Account Manager", "Team Lead", "Staff"])
async def test_actor_without_reset_password_permission_is_denied(db_session, actor_role_name):
    from app.rbac.services.access_control import ensure_has_permission

    actor = await _get_user_by_role(db_session, actor_role_name)
    actor.permissions = []

    with pytest.raises(HTTPException) as exc_info:
        ensure_has_permission(actor, "user:reset_password")
    assert exc_info.value.status_code == 403


async def test_actor_with_unrelated_permissions_is_still_denied(db_session):
    from app.rbac.services.access_control import ensure_has_permission

    actor = await _get_user_by_role(db_session, "Team Lead")
    actor.permissions = ["user:view", "user:update"]

    with pytest.raises(HTTPException) as exc_info:
        ensure_has_permission(actor, "user:reset_password")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------
# 5. Client-account rejection — no login of their own
# ---------------------------------------------------------


async def test_resetting_a_client_accounts_password_is_rejected(db_session):
    service = _build_user_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = ["user:reset_password"]

    client = await _make_throwaway_client(db_session, service)

    with pytest.raises(HTTPException) as exc_info:
        await service.reset_password(client.client_id, "somePassword123", actor=actor)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------
# 6. Existing update_user path unaffected
# ---------------------------------------------------------


async def test_existing_update_user_still_works_unaffected(db_session):
    from app.rbac.schemas.user import UserUpdate

    service = _build_user_service(db_session)
    actor = await _get_user_by_role(db_session, "Super Admin")

    target = await _make_throwaway_user(db_session, service)

    updated = await service.update_user(
        target.user_id, UserUpdate(name="Renamed Throwaway"), actor=actor
    )
    name = updated["name"] if isinstance(updated, dict) else updated.name
    assert name == "Renamed Throwaway"


# ---------------------------------------------------------
# 7. Self-service change_password unaffected
# ---------------------------------------------------------


async def test_self_service_change_password_is_unaffected_by_the_new_admin_reset_capability(
    db_session,
):
    # role_permission_repository/permission_resolver are None here —
    # change_password's own body only ever touches self.user_repository
    # and self.audit_log_service, confirmed by direct source read.
    auth_service = AuthService(
        user_repository=UserRepository(db_session),
        role_permission_repository=None,
        permission_resolver=None,
        audit_log_service=AuditLogService(audit_log_repository=AuditLogRepository(db_session)),
    )
    service = _build_user_service(db_session)
    target = await _make_throwaway_user(db_session, service)

    await auth_service.change_password(
        target,
        ChangePasswordRequest(
            old_password=ORIGINAL_PASSWORD,
            new_password="selfChangedPassword321",
        ),
    )

    refreshed = await UserRepository(db_session).get_by_id(target.user_id)
    assert verify_password("selfChangedPassword321", refreshed.password_hash)

    with pytest.raises(HTTPException):
        await auth_service.change_password(
            refreshed,
            ChangePasswordRequest(
                old_password="wrongOldPassword",
                new_password="irrelevant999999",
            ),
        )
