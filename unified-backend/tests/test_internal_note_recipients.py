# test_internal_note_recipients.py
#
# Coverage for the Internal Note recipient-selection/delivery change:
# the "To" field is no longer UI-only cosmetic (see TicketComposer.tsx
# and InternalNoteCreate.recipient_user_ids) — any active platform
# user, regardless of role/reporting-hierarchy/department/team/
# category, can be selected, and selecting them actually delivers the
# note to their Mail > System while it remains the ticket's own single
# Timeline/Interaction record.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_escalation_read_only_access.py. Per that file's own note (and
# the root CLAUDE.md's "parallel-track integration pass" section), run
# this file in isolation rather than alongside other DB-touching test
# files in the same pytest process (a pre-existing pytest-asyncio
# event-loop issue, not introduced here).

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.notifications.models import Notification
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.ticketing.enums import TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.note import InternalNoteCreate
from app.ticketing.services.interaction_service import InteractionService

CATEGORY_SCOPED_ROLE_NAMES = {"Team Lead", "Staff"}


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _build_interaction_service(session) -> InteractionService:
    return InteractionService(
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        client_repository=ClientRepository(session),
        notification_service=NotificationService(NotificationRepository(session)),
    )


async def _get_user_by_role(session, role_name: str) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == role_name, User.is_active.is_(True))
    )
    user = result.unique().scalars().first()
    if user is None:
        pytest.skip(f"No active seeded {role_name!r} user found.")
    return user


async def _get_two_users_by_role(session, role_name: str) -> tuple[User, User]:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == role_name, User.is_active.is_(True))
    )
    users = result.unique().scalars().all()
    if len(users) < 2:
        pytest.skip(f"Need at least two active seeded {role_name!r} users.")
    return users[0], users[1]


def _ticket_type_for(user: User) -> str:
    # Team Lead/Staff are category-scoped (ensure_agent_can_view_ticket)
    # — the ticket has to be filed under their own category or they'd
    # 403 on their own ticket. Every other role is unrestricted, so any
    # real category name works.
    if user.role.name in CATEGORY_SCOPED_ROLE_NAMES and user.category is not None:
        return user.category.category_name.value
    return "Eligibility"


async def _make_ticket_for_sender(session, sender: User) -> tuple[Client, Ticket]:
    client = Client(
        client_id=uuid.uuid4(),
        name=f"Internal Note Test Client {uuid.uuid4().hex[:8]}",
        inbox_email=f"note-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=sender.user_id,
        is_active=True,
    )
    session.add(client)

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=sender.user_id,
        title="Internal Note recipient test ticket",
        ticket_type=_ticket_type_for(sender),
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()
    return client, ticket


async def _notifications_for(session, user_id, ticket_id) -> list[Notification]:
    result = await session.execute(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.notification_type == "INTERNAL_NOTE_ADDED",
            Notification.related_entity_id == ticket_id,
        )
    )
    return list(result.scalars().all())


async def _send_note(session, ticket: Ticket, sender: User, recipients: list[User], *, note="Please review the eligibility issue for this ticket."):
    # ticket:editown_ticket is needed on top of reply/internal-note
    # permissions whenever the sender isn't a supervisor role (Staff,
    # mainly) and the ticket happens to be assigned to them — every
    # scenario here assigns the ticket to its own sender (see
    # _make_ticket_for_sender), so this always applies regardless of
    # the sender's actual role.
    sender.permissions = ["ticket:reply", "communication:reply_internal", "ticket:editown_ticket"]
    service = _build_interaction_service(session)
    response = await service.add_internal_note(
        ticket.ticket_id,
        InternalNoteCreate(
            subject="Eligibility issue",
            note=note,
            recipient_user_ids=[r.user_id for r in recipients],
        ),
        sender,
    )
    return service, response


async def _assert_delivered(session, ticket, sender, recipients, other_users=None):
    """
    One Internal Note interaction ends up on the ticket's own Timeline
    /Interaction history, and each selected recipient (and only them)
    gets exactly one System Mail (Notification) row pointing back at
    this same ticket.
    """

    service, response = await _send_note(session, ticket, sender, recipients)
    assert set(response.recipient_user_ids) == {r.user_id for r in recipients}

    interactions = await service.get_ticket_interactions(ticket.ticket_id, sender)
    notes = [i for i in interactions if i.interaction_type == "INTERNAL_NOTE"]
    assert len(notes) == 1, "expected exactly one Internal Note interaction on the ticket"
    note = notes[0]
    assert note.ticket_id == ticket.ticket_id
    assert set(note.payload.get("recipient_user_ids", [])) == {str(r.user_id) for r in recipients}

    for recipient in recipients:
        rows = await _notifications_for(session, recipient.user_id, ticket.ticket_id)
        assert len(rows) == 1, f"expected exactly one System Mail row for {recipient.user_id}"
        assert rows[0].related_entity_type == "ticket"
        assert rows[0].related_entity_id == ticket.ticket_id
        assert rows[0].is_read is False

    for other in other_users or []:
        rows = await _notifications_for(session, other.user_id, ticket.ticket_id)
        assert rows == [], f"unselected user {other.user_id} must not receive this note"

    return service, response, note


# ---------------------------------------------------------------
# 1-5: every direction the spec calls out explicitly, none blocked
# by reporting hierarchy.
# ---------------------------------------------------------------


async def test_staff_to_account_manager(db_session):
    staff = await _get_user_by_role(db_session, "Staff")
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    _client, ticket = await _make_ticket_for_sender(db_session, staff)
    await _assert_delivered(db_session, ticket, staff, [account_manager])


async def test_account_manager_to_staff(db_session):
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    staff = await _get_user_by_role(db_session, "Staff")
    _client, ticket = await _make_ticket_for_sender(db_session, account_manager)
    await _assert_delivered(db_session, ticket, account_manager, [staff])


async def test_team_lead_to_site_lead(db_session):
    team_lead = await _get_user_by_role(db_session, "Team Lead")
    site_lead = await _get_user_by_role(db_session, "Site Lead")
    _client, ticket = await _make_ticket_for_sender(db_session, team_lead)
    await _assert_delivered(db_session, ticket, team_lead, [site_lead])


async def test_site_lead_to_staff(db_session):
    site_lead = await _get_user_by_role(db_session, "Site Lead")
    staff = await _get_user_by_role(db_session, "Staff")
    _client, ticket = await _make_ticket_for_sender(db_session, site_lead)
    await _assert_delivered(db_session, ticket, site_lead, [staff])


async def test_super_admin_to_staff(db_session):
    super_admin = await _get_user_by_role(db_session, "Super Admin")
    staff = await _get_user_by_role(db_session, "Staff")
    _client, ticket = await _make_ticket_for_sender(db_session, super_admin)
    await _assert_delivered(db_session, ticket, super_admin, [staff])


# ---------------------------------------------------------------
# 6: multiple recipients — one Timeline/Interaction entry, one
# System Mail row per recipient.
# ---------------------------------------------------------------


async def test_multiple_recipients_single_timeline_entry(db_session):
    staff = await _get_user_by_role(db_session, "Staff")
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    team_lead = await _get_user_by_role(db_session, "Team Lead")
    site_lead = await _get_user_by_role(db_session, "Site Lead")
    _client, ticket = await _make_ticket_for_sender(db_session, staff)

    _service, response, _note = await _assert_delivered(
        db_session, ticket, staff, [account_manager, team_lead, site_lead]
    )
    assert len(response.recipient_user_ids) == 3


# ---------------------------------------------------------------
# 7: unrelated users never receive it.
# ---------------------------------------------------------------


async def test_unrelated_account_manager_does_not_receive(db_session):
    staff = await _get_user_by_role(db_session, "Staff")
    account_manager_a, account_manager_b = await _get_two_users_by_role(
        db_session, "Account Manager"
    )
    _client, ticket = await _make_ticket_for_sender(db_session, staff)
    await _assert_delivered(
        db_session, ticket, staff, [account_manager_a], other_users=[account_manager_b]
    )


# ---------------------------------------------------------------
# 8-9: ticket association + Timeline persistence across a fresh
# fetch (simulating "reload the ticket").
# ---------------------------------------------------------------


async def test_ticket_association_and_persists_on_reload(db_session):
    staff = await _get_user_by_role(db_session, "Staff")
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    _client, ticket = await _make_ticket_for_sender(db_session, staff)
    service, response, note = await _assert_delivered(db_session, ticket, staff, [account_manager])

    assert note.ticket_id == ticket.ticket_id
    assert response.ticket_id == ticket.ticket_id
    rows = await _notifications_for(db_session, account_manager.user_id, ticket.ticket_id)
    assert rows[0].related_entity_id == ticket.ticket_id

    # A second, independent fetch — the same thing a page reload would
    # trigger — must still show exactly one Internal Note.
    reloaded = await service.get_ticket_interactions(ticket.ticket_id, staff)
    reloaded_notes = [i for i in reloaded if i.interaction_type == "INTERNAL_NOTE"]
    assert len(reloaded_notes) == 1
    assert reloaded_notes[0].interaction_id == note.interaction_id


# ---------------------------------------------------------------
# 10: System Mail read/unread never affects the Timeline entry.
# ---------------------------------------------------------------


async def test_system_mail_read_state_does_not_affect_timeline(db_session):
    staff = await _get_user_by_role(db_session, "Staff")
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    _client, ticket = await _make_ticket_for_sender(db_session, staff)
    service, _response, note = await _assert_delivered(db_session, ticket, staff, [account_manager])

    rows = await _notifications_for(db_session, account_manager.user_id, ticket.ticket_id)
    notification = rows[0]
    assert notification.is_read is False
    notification.is_read = True
    await db_session.flush()

    reloaded = await service.get_ticket_interactions(ticket.ticket_id, staff)
    reloaded_notes = [i for i in reloaded if i.interaction_type == "INTERNAL_NOTE"]
    assert len(reloaded_notes) == 1
    assert reloaded_notes[0].interaction_id == note.interaction_id
    assert reloaded_notes[0].payload["note"] == note.payload["note"]


# ---------------------------------------------------------------
# Backward compatibility: no recipients falls back to the
# pre-existing stakeholder notification, unchanged.
# ---------------------------------------------------------------


async def test_no_recipients_preserves_existing_behavior(db_session):
    staff = await _get_user_by_role(db_session, "Staff")
    _client, ticket = await _make_ticket_for_sender(db_session, staff)
    staff.permissions = ["ticket:reply", "communication:reply_internal", "ticket:editown_ticket"]
    service = _build_interaction_service(db_session)

    response = await service.add_internal_note(
        ticket.ticket_id,
        InternalNoteCreate(subject="test", note="test note"),
        staff,
    )
    assert response.recipient_user_ids == []

    interactions = await service.get_ticket_interactions(ticket.ticket_id, staff)
    notes = [i for i in interactions if i.interaction_type == "INTERNAL_NOTE"]
    assert len(notes) == 1
    assert not notes[0].payload.get("recipient_user_ids")


# ---------------------------------------------------------------
# Eligibility rules that still apply: self-selection and inactive
# users are dropped, everyone else regardless of role is kept.
# ---------------------------------------------------------------


async def test_self_and_inactive_recipients_are_dropped(db_session):
    staff = await _get_user_by_role(db_session, "Staff")
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    _client, ticket = await _make_ticket_for_sender(db_session, staff)

    inactive_user = User(
        user_id=uuid.uuid4(),
        name="Inactive Test User",
        email=f"inactive-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role_id=account_manager.role_id,
        is_active=False,
    )
    db_session.add(inactive_user)
    await db_session.flush()

    _service, response = await _send_note(
        db_session, ticket, staff, [staff, account_manager, inactive_user]
    )
    assert response.recipient_user_ids == [account_manager.user_id]

    rows = await _notifications_for(db_session, inactive_user.user_id, ticket.ticket_id)
    assert rows == []
    rows = await _notifications_for(db_session, staff.user_id, ticket.ticket_id)
    assert rows == []


# ---------------------------------------------------------------
# Security: receiving a note grants no ticket access, and the
# sender still needs the pre-existing RBAC permissions — neither
# side of the existing security model changed.
# ---------------------------------------------------------------


async def test_receiving_note_does_not_grant_ticket_access(db_session):
    account_manager, other_account_manager = await _get_two_users_by_role(
        db_session, "Account Manager"
    )
    # Ticket belongs to `other_account_manager`'s client, not
    # `account_manager`'s.
    _client, ticket = await _make_ticket_for_sender(db_session, other_account_manager)

    await _send_note(db_session, ticket, other_account_manager, [account_manager])

    account_manager.permissions = ["ticket:reply", "communication:reply_internal"]
    service = _build_interaction_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.get_ticket_interactions(ticket.ticket_id, account_manager)
    assert exc_info.value.status_code == 403


async def test_sender_still_needs_permission_to_add_note(db_session):
    staff = await _get_user_by_role(db_session, "Staff")
    account_manager = await _get_user_by_role(db_session, "Account Manager")
    _client, ticket = await _make_ticket_for_sender(db_session, staff)

    # Missing communication:reply_internal specifically — ticket:editown_ticket
    # is present so the 403 below is guaranteed to come from the
    # intended ensure_has_permission check, not the unrelated
    # ownership gate.
    staff.permissions = ["ticket:reply", "ticket:editown_ticket"]
    service = _build_interaction_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.add_internal_note(
            ticket.ticket_id,
            InternalNoteCreate(
                subject="test", note="test note", recipient_user_ids=[account_manager.user_id]
            ),
            staff,
        )
    assert exc_info.value.status_code == 403
