# test_user_reset_password.py
#
# Coverage for the Super Admin "Change Password" backend feature:
#
#   - UserService.reset_password (POST /users/{id}/reset-password's
#     service layer) — hashes via the existing app.auth.password
#     helpers (never plaintext), writes a user.password_reset audit
#     row with no old_value/new_value (the password itself must never
#     be logged), and rejects a Client-role target (Clients have no
#     password_hash at all).
#   - The route's permission gate, `user:reset_password` — seeded
#     (scripts/rbac_seed/seed.py) but previously unenforced anywhere.
#     Exercised via access_control.ensure_has_permission directly,
#     since this codebase's tests call service/access-control methods
#     rather than driving real HTTP requests (see
#     test_user_creation_role_matrix.py, the template this file
#     follows).
#   - ResetPasswordRequest's schema-level validation (non-empty,
#     min 8 chars).
#
# Per this repo's own documented pytest-asyncio caveat (root
# CLAUDE.md's "SLA & Escalation" section), DB-touching test files can
# hang if run in the same process as other DB-touching files — run
# this file individually if the full suite misbehaves.

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
from app.rbac.repositories.permission_override_repository import (
    PermissionOverrideRepository,
)
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.auth import LoginRequest
from app.rbac.schemas.user import ResetPasswordRequest, UserCreate
from app.rbac.services import access_control
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.auth_service import AuthService
from app.rbac.services.organization_service import OrganizationService
from app.rbac.services.permission_resolver import PermissionResolverService
from app.rbac.services.user_service import UserService
from app.ticketing.models.client import Client
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.user_repository import UserRepository as TicketingUserRepository
from app.ticketing.services.client_service import ClientService

OLD_PASSWORD = "OldPassword123"
NEW_PASSWORD = "NewPassword456"


# --------------------------------------------------------------------
# Pure schema validation — no DB needed.
# --------------------------------------------------------------------

def test_reset_password_schema_rejects_short_password():
    with pytest.raises(ValidationError):
        ResetPasswordRequest(new_password="short")


def test_reset_password_schema_rejects_empty_password():
    with pytest.raises(ValidationError):
        ResetPasswordRequest(new_password="")


def test_reset_password_schema_accepts_valid_password():
    request = ResetPasswordRequest(new_password=NEW_PASSWORD)
    assert request.new_password == NEW_PASSWORD


# --------------------------------------------------------------------
# DB-backed: real seeded data, always rolled back (never committed).
# --------------------------------------------------------------------

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


def _build_auth_service(session) -> AuthService:
    role_permission_repository = RolePermissionRepository(session)
    return AuthService(
        user_repository=UserRepository(session),
        role_permission_repository=role_permission_repository,
        permission_resolver=PermissionResolverService(
            role_permission_repository=role_permission_repository,
            permission_override_repository=PermissionOverrideRepository(session),
        ),
        audit_log_service=AuditLogService(audit_log_repository=AuditLogRepository(session)),
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


def _minimal_user_create(role_id, **overrides) -> UserCreate:
    unique = uuid.uuid4().hex[:10]
    base = dict(
        name=f"Throwaway {unique}",
        email=f"throwaway-{unique}@example.com",
        password=OLD_PASSWORD,
        role_id=role_id,
        is_active=True,
        # Site Lead is the one internal role that needs neither a
        # category nor a Reporting Manager (see
        # DESIGNATION_REQUIRED_ROLE_NAMES/
        # REPORTING_MANAGER_OPTIONAL_ROLE_NAMES in user_service.py) —
        # the simplest internal role to stand up a throwaway user for.
        designation="Throwaway - Test",
        alternate_email=f"throwaway-alt-{unique}@example.com",
        employee_number=f"TEST-{unique}",
    )
    base.update(overrides)
    return UserCreate(**base)


async def _create_throwaway_internal_user(session, actor) -> User:
    site_lead_role = await _get_role(session, "Site Lead")
    service = _build_user_service(session)
    return await service.create_user(_minimal_user_create(site_lead_role.role_id), actor=actor)


async def _attach_effective_permissions(session, user: User) -> User:
    """
    Bolts a transient `.permissions` list onto a real fetched User —
    the same "reconstruct what the JWT claim would carry" pattern
    production code uses (see access_control.has_permission's own
    docstring) — so ensure_has_permission can be exercised against a
    real role's actual seeded grants without a real login/JWT round
    trip.
    """

    permissions, _, _ = await PermissionResolverService(
        role_permission_repository=RolePermissionRepository(session),
        permission_override_repository=PermissionOverrideRepository(session),
    ).get_effective_permissions(user)

    user.permissions = permissions
    return user


# --------------------------------------------------------------------
# Permission gate — user:reset_password (seeded for Super Admin/
# Account Manager, per scripts/rbac_seed/seed.py; nobody else).
# --------------------------------------------------------------------

async def test_super_admin_holds_reset_password_permission(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    await _attach_effective_permissions(db_session, super_admin)

    # Should not raise.
    access_control.ensure_has_permission(super_admin, "user:reset_password")


async def test_staff_cannot_reset_password(db_session):
    staff = await _get_user_by_role(db_session, "Staff")
    await _attach_effective_permissions(db_session, staff)

    with pytest.raises(HTTPException) as exc_info:
        access_control.ensure_has_permission(staff, "user:reset_password")

    assert exc_info.value.status_code == 403


async def test_team_lead_cannot_reset_password(db_session):
    team_lead = await _get_user_by_role(db_session, "Team Lead")
    await _attach_effective_permissions(db_session, team_lead)

    with pytest.raises(HTTPException) as exc_info:
        access_control.ensure_has_permission(team_lead, "user:reset_password")

    assert exc_info.value.status_code == 403


# --------------------------------------------------------------------
# UserService.reset_password — hashing, login round trip, errors.
# --------------------------------------------------------------------

async def test_super_admin_can_reset_another_users_password(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    target = await _create_throwaway_internal_user(db_session, super_admin)

    service = _build_user_service(db_session)
    await service.reset_password(target.user_id, NEW_PASSWORD, actor=super_admin)

    stored = await UserRepository(db_session).get_by_id(target.user_id)

    # Hashed, not plaintext.
    assert stored.password_hash != NEW_PASSWORD
    assert verify_password(NEW_PASSWORD, stored.password_hash)
    assert not verify_password(OLD_PASSWORD, stored.password_hash)


async def test_user_can_login_with_new_password_after_reset(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    target = await _create_throwaway_internal_user(db_session, super_admin)

    service = _build_user_service(db_session)
    await service.reset_password(target.user_id, NEW_PASSWORD, actor=super_admin)

    auth_service = _build_auth_service(db_session)
    token_response = await auth_service.login(
        LoginRequest(email=target.email, password=NEW_PASSWORD)
    )

    assert token_response.access_token
    assert token_response.refresh_token


async def test_old_password_no_longer_works_after_reset(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    target = await _create_throwaway_internal_user(db_session, super_admin)

    service = _build_user_service(db_session)
    await service.reset_password(target.user_id, NEW_PASSWORD, actor=super_admin)

    auth_service = _build_auth_service(db_session)

    with pytest.raises(HTTPException) as exc_info:
        await auth_service.login(LoginRequest(email=target.email, password=OLD_PASSWORD))

    assert exc_info.value.status_code == 401


async def test_reset_password_nonexistent_user_returns_404(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    service = _build_user_service(db_session)

    with pytest.raises(HTTPException) as exc_info:
        await service.reset_password(uuid.uuid4(), NEW_PASSWORD, actor=super_admin)

    assert exc_info.value.status_code == 404


async def test_reset_password_rejects_client_target(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    client_role = await _get_role(db_session, "Client")

    service = _build_user_service(db_session)
    unique = uuid.uuid4().hex[:10]
    created = await service.create_user(
        _minimal_user_create(
            client_role.role_id,
            manager_id=account_manager.user_id,
            contact_emails=[f"client-{unique}@hospital.com"],
        ),
        actor=super_admin,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.reset_password(created["user_id"], NEW_PASSWORD, actor=super_admin)

    assert exc_info.value.status_code == 400
    assert "password" in exc_info.value.detail.lower()


async def test_reset_password_never_logs_the_password(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    target = await _create_throwaway_internal_user(db_session, super_admin)

    service = _build_user_service(db_session)
    await service.reset_password(target.user_id, NEW_PASSWORD, actor=super_admin)

    logs = await AuditLogRepository(db_session).get_user_logs(super_admin.user_id)
    reset_logs = [log for log in logs if log.entity_id == str(target.user_id) and log.action == "user.password_reset"]

    assert len(reset_logs) == 1
    log = reset_logs[0]
    assert log.old_value is None
    assert log.new_value is None
    # Belt-and-suspenders: the password must not appear anywhere in
    # the row, under any field, even accidentally.
    assert NEW_PASSWORD not in str(log.__dict__)
    assert OLD_PASSWORD not in str(log.__dict__)
