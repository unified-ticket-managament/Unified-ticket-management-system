# test_user_creation_role_matrix.py
#
# Coverage for the role-aware Create User security fix:
#
#   - access_control.ensure_can_create_role — pure-logic tests, no DB
#     (only ever reads actor.role.name), covering the exact matrix:
#     Super Admin/Site Lead unrestricted, Account Manager limited to
#     {Team Lead, Staff, Client}, and denial for every other actor.
#   - UserService.create_user now calls ensure_can_create_role before
#     doing anything else — a crafted request that used to succeed
#     (e.g. an Account Manager assigning Super Admin) now 403s. These
#     run against the real (dev) database inside a transaction that is
#     always rolled back at the end, mirroring
#     test_user_listing_hierarchy.py's own convention.
#   - Designation/Personal Email/Reporting Manager required-ness for
#     the five internal roles, and Client's own contact-email
#     requirements (min 1, no duplicates, written to `clients`/
#     `client_contacts`, never `users`).
#
# Per this repo's own documented pytest-asyncio caveat (see root
# CLAUDE.md's "SLA & Escalation" section), DB-touching test files can
# hang if run in the same process as other DB-touching files — run
# this file individually if the full suite misbehaves.

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.category_repository import CategoryRepository
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.user import UserCreate
from app.rbac.services import access_control
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.organization_service import OrganizationService
from app.rbac.services.user_service import UserService
from app.ticketing.models.client import Client
from app.ticketing.models.client_contact import ClientContact
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.user_repository import UserRepository as TicketingUserRepository
from app.ticketing.services.client_service import ClientService


# --------------------------------------------------------------------
# Pure-logic: ensure_can_create_role — no DB needed.
# --------------------------------------------------------------------

def _actor(role_name: str):
    return SimpleNamespace(role=SimpleNamespace(name=role_name))


@pytest.mark.parametrize(
    "target_role_name",
    ["Super Admin", "Site Lead", "Account Manager", "Team Lead", "Staff", "Client"],
)
def test_super_admin_can_create_every_role(target_role_name):
    access_control.ensure_can_create_role(_actor("Super Admin"), target_role_name)


@pytest.mark.parametrize(
    "target_role_name",
    ["Super Admin", "Site Lead", "Account Manager", "Team Lead", "Staff", "Client"],
)
def test_site_lead_can_create_every_role(target_role_name):
    access_control.ensure_can_create_role(_actor("Site Lead"), target_role_name)


@pytest.mark.parametrize("target_role_name", ["Team Lead", "Staff", "Client"])
def test_account_manager_can_create_allowed_roles(target_role_name):
    access_control.ensure_can_create_role(_actor("Account Manager"), target_role_name)


@pytest.mark.parametrize("target_role_name", ["Super Admin", "Site Lead", "Account Manager"])
def test_account_manager_cannot_create_disallowed_roles(target_role_name):
    with pytest.raises(HTTPException) as exc_info:
        access_control.ensure_can_create_role(_actor("Account Manager"), target_role_name)
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("actor_role_name", ["Team Lead", "Staff", "Client"])
def test_non_creator_roles_cannot_create_anyone(actor_role_name):
    with pytest.raises(HTTPException) as exc_info:
        access_control.ensure_can_create_role(_actor(actor_role_name), "Staff")
    assert exc_info.value.status_code == 403


# --------------------------------------------------------------------
# DB-backed: UserService.create_user end-to-end, real seeded data,
# always rolled back.
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
        password="password123",
        role_id=role_id,
        is_active=True,
    )
    base.update(overrides)
    return UserCreate(**base)


@pytest.mark.parametrize("target_role_name", ["Super Admin", "Site Lead", "Account Manager"])
async def test_account_manager_cannot_create_disallowed_roles_via_service(db_session, target_role_name):
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    target_role = await _get_role(db_session, target_role_name)

    service = _build_user_service(db_session)
    user_data = _minimal_user_create(target_role.role_id)

    with pytest.raises(HTTPException) as exc_info:
        await service.create_user(user_data, actor=account_manager)

    assert exc_info.value.status_code == 403


async def test_account_manager_can_create_team_lead_up_to_field_validation(db_session):
    """
    Confirms the 403 is gone for an allowed target role — the request
    should get past ensure_can_create_role and fail (if at all) on an
    unrelated field-validation reason (missing category/designation),
    never on the role-matrix check itself.
    """

    account_manager = await _get_user_by_role(db_session, "Account Manager")
    team_lead_role = await _get_role(db_session, "Team Lead")

    service = _build_user_service(db_session)
    user_data = _minimal_user_create(team_lead_role.role_id)

    with pytest.raises(HTTPException) as exc_info:
        await service.create_user(user_data, actor=account_manager)

    # Category is required for Team Lead and wasn't supplied — this is
    # the expected failure reason, not a 403 from the role matrix.
    assert exc_info.value.status_code == 400
    assert "Category" in exc_info.value.detail


async def test_missing_designation_rejected_for_internal_role(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    site_lead_role = await _get_role(db_session, "Site Lead")

    service = _build_user_service(db_session)
    # Site Lead needs no category/manager/teamlead, so omitting
    # designation is the only thing that should trip here.
    user_data = _minimal_user_create(site_lead_role.role_id)

    with pytest.raises(HTTPException) as exc_info:
        await service.create_user(user_data, actor=super_admin)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Designation is required."


async def test_reporting_manager_required_for_account_manager_role(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    account_manager_role = await _get_role(db_session, "Account Manager")

    service = _build_user_service(db_session)
    user_data = _minimal_user_create(
        account_manager_role.role_id,
        designation="Account Manager - AR",
        alternate_email="personal@example.com",
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.create_user(user_data, actor=super_admin)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Reporting Manager is required."


async def test_site_lead_can_be_created_without_reporting_manager(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    site_lead_role = await _get_role(db_session, "Site Lead")

    service = _build_user_service(db_session)
    user_data = _minimal_user_create(
        site_lead_role.role_id,
        designation="Site Lead - Operations",
        alternate_email="personal@example.com",
        # reporting_manager_id deliberately omitted — must succeed.
    )

    created = await service.create_user(user_data, actor=super_admin)

    assert created.role_id == site_lead_role.role_id
    assert created.reporting_manager_id is None
    # Regression check: designation/alternate_email must actually be
    # persisted on the row, not just validated as present on the
    # incoming request and then silently dropped.
    assert created.designation == "Site Lead - Operations"
    assert created.alternate_email == "personal@example.com"


async def test_client_requires_at_least_one_contact_email(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    client_role = await _get_role(db_session, "Client")

    service = _build_user_service(db_session)
    user_data = _minimal_user_create(
        client_role.role_id,
        manager_id=account_manager.user_id,
        contact_emails=[],
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.create_user(user_data, actor=super_admin)

    assert exc_info.value.status_code == 400
    assert "contact email" in exc_info.value.detail.lower()


async def test_client_rejects_duplicate_contact_emails(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    client_role = await _get_role(db_session, "Client")

    service = _build_user_service(db_session)
    user_data = _minimal_user_create(
        client_role.role_id,
        manager_id=account_manager.user_id,
        contact_emails=["kiran@hospital.com", "Kiran@Hospital.com"],
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.create_user(user_data, actor=super_admin)

    assert exc_info.value.status_code == 400
    assert "duplicate" in exc_info.value.detail.lower()


async def test_client_creates_client_and_contacts_not_users_row(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    client_role = await _get_role(db_session, "Client")

    service = _build_user_service(db_session)
    unique = uuid.uuid4().hex[:10]
    contact_emails = [f"kiran-{unique}@hospital.com", f"ravi-{unique}@hospital.com"]
    user_data = _minimal_user_create(
        client_role.role_id,
        manager_id=account_manager.user_id,
        contact_emails=contact_emails,
    )

    result = await service.create_user(user_data, actor=super_admin)
    client_id = result["user_id"]

    # Not created in `users` at all.
    assert await UserRepository(db_session).get_by_id(client_id) is None

    # Created in `clients`.
    client_row = await ClientRepository(db_session).get_by_id(client_id)
    assert client_row is not None
    assert client_row.account_manager_id == account_manager.user_id

    # Contacts created in `client_contacts`, matching what was submitted.
    contacts_result = await db_session.execute(
        select(ClientContact).where(ClientContact.client_id == client_id)
    )
    stored_emails = {c.email for c in contacts_result.scalars().all()}
    assert stored_emails == {email.lower() for email in contact_emails}
