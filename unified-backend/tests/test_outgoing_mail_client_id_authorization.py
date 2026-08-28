# test_outgoing_mail_client_id_authorization.py
#
# Phase 2C P0-4 fix (client_id branch only — see BD-15): POST
# /api/mail/outgoing's client_id branch previously did only an
# existence check on the named client, with no ownership/permission
# check of any kind — any authenticated agent could send (as the
# shared platform mailbox) referencing a client they don't own,
# bypassing communication:reply_external and Account-Manager-ownership
# scoping entirely. OutgoingMailService.send_email/_build_envelope now
# call the existing ensure_can_compose_for_client (the same check
# Compose already runs) at the point the client is resolved — reused
# verbatim, not duplicated.
#
# The arbitrary-from_email branch (client_id omitted) was explicitly
# OUT OF SCOPE for this phase (BD-16, unresolved at the time) — this
# file's one test for it originally proved the branch was genuinely
# untouched. BD-16 has since received a Phase 2E interim mitigation
# (Site Lead/Super Admin only); that test was updated in place to
# match, and test_outgoing_mail_arbitrary_sender_restriction.py has
# the full Phase 2E coverage.
#
# No real email is sent: mail_provider_client is an AsyncMock
# throughout, matching test_outgoing_mail_service_recipient_
# validation.py's own convention. Client rows are real (seeded/
# throwaway), inside a transaction that is always rolled back. Run
# this file individually (DB-touching test caveat).

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
    # These tests are about authorization, not deliverability — mocked
    # exactly like test_outgoing_mail_service_recipient_validation.py's
    # own convention, so nothing here makes a real DNS query.
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


async def _get_two_account_managers(session) -> tuple[User, User]:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Account Manager", User.is_active.is_(True))
    )
    users = result.unique().scalars().all()
    if len(users) < 2:
        pytest.skip("Need at least 2 active seeded Account Managers for this test.")
    return users[0], users[1]


async def _make_client(session, *, account_manager_id) -> Client:
    unique = uuid.uuid4().hex[:10]
    client = Client(
        client_id=uuid.uuid4(),
        name=f"Throwaway Outgoing-Mail Test Client {unique}",
        inbox_email=f"throwaway-outgoing-{unique}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()
    return client


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
# Positive: AM sending for their own client, with the permission
# ---------------------------------------------------------


async def test_account_manager_can_send_for_own_client(db_session):
    owner, _other = await _get_two_account_managers(db_session)
    owner.permissions = ["communication:reply_external"]
    client = await _make_client(db_session, account_manager_id=owner.user_id)

    mail_provider_client = AsyncMock()
    mail_provider_client.send_email.return_value = AsyncMock(
        provider_message_id="mock-1", status="SENT"
    )
    service = _build_service(db_session, mail_provider_client)

    result = await service.send_email(_request(client_id=client.client_id), owner)

    assert result.status == "SENT"
    mail_provider_client.send_email.assert_awaited_once()


# ---------------------------------------------------------
# Negative: AM sending for a DIFFERENT AM's client — the actual
# vulnerability this fix closes
# ---------------------------------------------------------


async def test_account_manager_cannot_send_for_another_clients_mailbox(db_session):
    owner, other_am = await _get_two_account_managers(db_session)
    other_am.permissions = ["communication:reply_external"]
    client = await _make_client(db_session, account_manager_id=owner.user_id)

    mail_provider_client = AsyncMock()
    service = _build_service(db_session, mail_provider_client)

    with pytest.raises(HTTPException) as exc_info:
        await service.send_email(_request(client_id=client.client_id), other_am)
    assert exc_info.value.status_code == 403

    # No partial/attempted dispatch — the check runs before the send.
    mail_provider_client.send_email.assert_not_called()


async def test_actor_without_permission_cannot_send_for_any_client(db_session):
    owner, _other = await _get_two_account_managers(db_session)
    staff = await _get_user_by_role(db_session, "Staff")
    staff.permissions = []  # holds nothing, regardless of real seed grant
    client = await _make_client(db_session, account_manager_id=owner.user_id)

    mail_provider_client = AsyncMock()
    service = _build_service(db_session, mail_provider_client)

    with pytest.raises(HTTPException) as exc_info:
        await service.send_email(_request(client_id=client.client_id), staff)
    assert exc_info.value.status_code == 403
    mail_provider_client.send_email.assert_not_called()


# ---------------------------------------------------------
# Regression: existing role bypasses (Site Lead/Super Admin) and
# existing ownership rule are preserved exactly as ensure_can_compose_
# for_client already defines them elsewhere — not re-implemented here.
# ---------------------------------------------------------


async def test_site_lead_can_send_for_any_client_regardless_of_ownership(db_session):
    owner, _other = await _get_two_account_managers(db_session)
    site_lead = await _get_user_by_role(db_session, "Site Lead")
    site_lead.permissions = ["communication:reply_external"]
    client = await _make_client(db_session, account_manager_id=owner.user_id)

    mail_provider_client = AsyncMock()
    mail_provider_client.send_email.return_value = AsyncMock(
        provider_message_id="mock-2", status="SENT"
    )
    service = _build_service(db_session, mail_provider_client)

    result = await service.send_email(_request(client_id=client.client_id), site_lead)
    assert result.status == "SENT"


async def test_unknown_client_id_still_404s_before_authorization_matters(db_session):
    """Existing not-found behavior (ValueError -> 404 at the route
    layer) is unaffected — confirmed the client lookup still runs and
    still raises for a nonexistent id, independent of this fix."""

    owner, _other = await _get_two_account_managers(db_session)
    owner.permissions = ["communication:reply_external"]

    mail_provider_client = AsyncMock()
    service = _build_service(db_session, mail_provider_client)

    with pytest.raises(ValueError, match="Client not found"):
        await service.send_email(_request(client_id=uuid.uuid4()), owner)


# ---------------------------------------------------------
# The arbitrary-from_email branch was genuinely untouched by THIS
# file's original Phase 2C fix (BD-16 was explicitly out of scope
# then) — confirmed at the time by a Staff actor with zero permissions
# still successfully dispatching. Phase 2E (RBAC Enforcement Audit,
# BD-16 interim mitigation) subsequently restricted this branch to
# Site Lead/Super Admin only. See
# test_outgoing_mail_arbitrary_sender_restriction.py for that phase's
# full coverage — this test is updated in place, not deleted, to
# assert the branch's current (Phase 2E) behavior rather than leave a
# stale assertion contradicting the real code.
# ---------------------------------------------------------


async def test_arbitrary_from_email_branch_now_requires_global_inbox_role(db_session):
    staff = await _get_user_by_role(db_session, "Staff")
    staff.permissions = []  # holds nothing at all — irrelevant here, this branch is role-gated, not permission-gated

    mail_provider_client = AsyncMock()
    service = _build_service(db_session, mail_provider_client)

    with pytest.raises(HTTPException) as exc_info:
        await service.send_email(_request(from_email="arbitrary@example.com"), staff)
    assert exc_info.value.status_code == 403
    mail_provider_client.send_email.assert_not_called()
