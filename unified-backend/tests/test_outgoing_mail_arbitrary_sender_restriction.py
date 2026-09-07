# test_outgoing_mail_arbitrary_sender_restriction.py
#
# Phase 2E — BD-16 interim security mitigation (RBAC Enforcement
# Audit). POST /api/mail/outgoing's arbitrary-from_email branch
# (client_id omitted) previously had no authorization check of any
# kind — any authenticated internal agent could dispatch as an
# arbitrary, syntactically-valid address with zero ownership concept
# to check it against (Phase 2D's own discovery: no existing
# permission represents "send as an arbitrary address," since the
# branch has no client/category object to scope against). This is a
# TEMPORARY role-based restriction, not a permission — reuses the
# existing GLOBAL_INBOX_ROLE_NAMES constant ({Site Lead, Super Admin})
# verbatim, the same set already used elsewhere in this codebase for
# "company-wide mail oversight, no per-client ownership concept."
# Retirement of the branch entirely remains the recommended long-term
# direction (BD-16 stays open).
#
# No real email is sent: mail_provider_client is an AsyncMock
# throughout. Client rows are real (seeded/throwaway) only where the
# client_id-branch spot-check needs one, inside a transaction that is
# always rolled back. Run this file individually (DB-touching test
# caveat).

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.models.client import Client
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.schemas.mail_integration import OutgoingEmailRequest
from app.ticketing.services import outgoing_mail_service as outgoing_mail_service_module
from app.ticketing.services.outgoing_mail_service import OutgoingMailService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


@pytest.fixture(autouse=True)
def _skip_real_recipient_validation(monkeypatch):
    # These tests are about authorization, not deliverability — no
    # real DNS query, matching this module's own established
    # convention (see test_outgoing_mail_service_recipient_
    # validation.py / test_outgoing_mail_client_id_authorization.py).
    monkeypatch.setattr(
        outgoing_mail_service_module, "ensure_recipients_are_valid", AsyncMock(return_value=None)
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


def _build_service(session, mail_provider_client) -> OutgoingMailService:
    return OutgoingMailService(
        client_repository=ClientRepository(session),
        mail_provider_client=mail_provider_client,
    )


def _request(*, client_id=None, from_email=None) -> OutgoingEmailRequest:
    return OutgoingEmailRequest(
        client_id=client_id,
        from_email=from_email,
        to_email="patient@example.com",
        cc=[],
        bcc=[],
        subject="Hello",
        body="Hi there.",
    )


# ---------------------------------------------------------
# Allowed: Super Admin, Site Lead
# ---------------------------------------------------------


async def test_super_admin_can_use_arbitrary_from_email(db_session):
    actor = await _get_user_by_role(db_session, "Super Admin")
    actor.permissions = []  # role-gated, not permission-gated — deliberately empty

    mail_provider_client = AsyncMock()
    mail_provider_client.send_email.return_value = AsyncMock(
        provider_message_id="mock-sa", status="SENT"
    )
    service = _build_service(db_session, mail_provider_client)

    result = await service.send_email(_request(from_email="ops@example.com"), actor)

    assert result.status == "SENT"
    mail_provider_client.send_email.assert_awaited_once()


async def test_site_lead_can_use_arbitrary_from_email(db_session):
    actor = await _get_user_by_role(db_session, "Site Lead")
    actor.permissions = []

    mail_provider_client = AsyncMock()
    mail_provider_client.send_email.return_value = AsyncMock(
        provider_message_id="mock-sl", status="SENT"
    )
    service = _build_service(db_session, mail_provider_client)

    result = await service.send_email(_request(from_email="ops@example.com"), actor)

    assert result.status == "SENT"
    mail_provider_client.send_email.assert_awaited_once()


# ---------------------------------------------------------
# Denied: Account Manager, Team Lead, Staff
# ---------------------------------------------------------


@pytest.mark.parametrize("role_name", ["Account Manager", "Team Lead", "Staff"])
async def test_role_is_denied_arbitrary_from_email(db_session, role_name):
    actor = await _get_user_by_role(db_session, role_name)
    actor.permissions = []

    mail_provider_client = AsyncMock()
    service = _build_service(db_session, mail_provider_client)

    with pytest.raises(HTTPException) as exc_info:
        await service.send_email(_request(from_email="ops@example.com"), actor)
    assert exc_info.value.status_code == 403
    mail_provider_client.send_email.assert_not_called()


async def test_unrelated_permission_does_not_bypass_the_role_restriction(db_session):
    """This branch is role-gated, not permission-gated — holding even
    a broad, seemingly-relevant permission (communication:reply_
    external, the permission the client_id branch actually checks)
    must not let a non-approved role through."""

    actor = await _get_user_by_role(db_session, "Account Manager")
    actor.permissions = ["communication:reply_external", "client:view"]

    mail_provider_client = AsyncMock()
    service = _build_service(db_session, mail_provider_client)

    with pytest.raises(HTTPException) as exc_info:
        await service.send_email(_request(from_email="ops@example.com"), actor)
    assert exc_info.value.status_code == 403
    mail_provider_client.send_email.assert_not_called()


# ---------------------------------------------------------
# Regression: the client_id branch (Phase 2C) is completely unaffected
# by this phase's change — different branch, different gate.
# ---------------------------------------------------------


async def test_client_id_branch_still_uses_phase_2c_authorization_unaffected(db_session):
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    account_manager.permissions = ["communication:reply_external"]

    unique = uuid.uuid4().hex[:10]
    client = Client(
        client_id=uuid.uuid4(),
        name=f"Throwaway Phase 2E Regression Client {unique}",
        inbox_email=f"throwaway-2e-{unique}@example.com",
        account_manager_id=account_manager.user_id,
        is_active=True,
    )
    db_session.add(client)
    await db_session.flush()

    mail_provider_client = AsyncMock()
    mail_provider_client.send_email.return_value = AsyncMock(
        provider_message_id="mock-client-id", status="SENT"
    )
    service = _build_service(db_session, mail_provider_client)

    # An Account Manager (denied on the arbitrary-from_email branch
    # above) can still send for their OWN client via client_id, exactly
    # as Phase 2C established — this phase changed only the other
    # branch.
    result = await service.send_email(_request(client_id=client.client_id), account_manager)
    assert result.status == "SENT"


async def test_cross_client_send_via_client_id_still_denied(db_session):
    owner = await _get_user_by_role(db_session, "Account Manager")
    other_am_result = await db_session.execute(
        select(User)
        .options(joinedload(User.role))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Account Manager", User.is_active.is_(True), User.user_id != owner.user_id)
    )
    other_am = other_am_result.unique().scalars().first()
    if other_am is None:
        pytest.skip("Need at least 2 active seeded Account Managers for this test.")
    other_am.permissions = ["communication:reply_external"]

    unique = uuid.uuid4().hex[:10]
    client = Client(
        client_id=uuid.uuid4(),
        name=f"Throwaway Phase 2E Cross-Client Test {unique}",
        inbox_email=f"throwaway-2e-cross-{unique}@example.com",
        account_manager_id=owner.user_id,
        is_active=True,
    )
    db_session.add(client)
    await db_session.flush()

    mail_provider_client = AsyncMock()
    service = _build_service(db_session, mail_provider_client)

    with pytest.raises(HTTPException) as exc_info:
        await service.send_email(_request(client_id=client.client_id), other_am)
    assert exc_info.value.status_code == 403
    mail_provider_client.send_email.assert_not_called()
