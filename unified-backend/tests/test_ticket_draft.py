# test_ticket_draft.py
#
# Regression coverage for Issue 2 (Save Draft for Ticket Reply and
# Internal Note — previously there was no server-side draft
# architecture for anything already attached to a ticket at all).
# InteractionService.save_ticket_reply_draft/get_ticket_reply_draft/
# discard_ticket_reply_draft/send_ticket_reply_draft and their
# Internal-Note siblings are a deliberate sibling to the pre-ticket
# Mail draft architecture, not a branch of it — a ticket draft has no
# thread root to attach a child row to, so it's its own row: ticket_id
# set, parent_interaction_id NULL, is_draft=True, uniquely keyed per
# (ticket_id, performed_by, interaction_type) by the new
# ix_interactions_one_ticket_draft_per_agent_per_type index.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_ticket_status_on_assignment.py, whose fixtures/helpers this
# file reuses the shape of.

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.ticket_draft import (
    TicketNoteDraftSaveRequest,
    TicketReplyDraftSaveRequest,
)
from app.ticketing.services.interaction_service import InteractionService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _find_team_lead_with_staff(session, staff_count: int = 1):
    team_lead_result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category), joinedload(User.categories))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Team Lead", User.is_active.is_(True))
    )
    team_leads = [
        user for user in team_lead_result.unique().scalars().all() if user.category is not None
    ]

    staff_result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category), joinedload(User.categories))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Staff", User.is_active.is_(True))
    )
    staff_by_category: dict = {}
    for user in staff_result.unique().scalars().all():
        if user.category is None:
            continue
        staff_by_category.setdefault(user.category.category_name, []).append(user)

    for team_lead in team_leads:
        candidates = staff_by_category.get(team_lead.category.category_name, [])
        if len(candidates) >= staff_count:
            return team_lead, candidates[:staff_count]

    pytest.skip(
        f"No category currently has both an active Team Lead and {staff_count} "
        "active Staff in the connected database."
    )


async def _make_ticket(session, *, account_manager_id, ticket_type, agent_id=None):
    client = Client(
        client_id=uuid.uuid4(),
        name="Ticket-draft Test Client",
        inbox_email=f"ticket-draft-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=agent_id,
        title="Ticket-draft regression test ticket",
        ticket_type=ticket_type,
        current_status="IN_PROGRESS",
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()
    return client, ticket


def _build_service(session) -> InteractionService:
    return InteractionService(
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        client_repository=ClientRepository(session),
    )


async def _staff_with_reply_permissions(session):
    team_lead, [staff] = await _find_team_lead_with_staff(session, 1)
    staff.permissions = [
        "ticket:reply",
        "ticket:editown_ticket",
        "communication:reply_external",
        "communication:reply_internal",
    ]
    return team_lead, staff


# ---------------------------------------------------------------
# Ticket Reply drafts
# ---------------------------------------------------------------


async def test_save_ticket_reply_draft_creates_then_updates_in_place(db_session):
    team_lead, staff = await _staff_with_reply_permissions(db_session)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=staff.category.category_name,
        agent_id=staff.user_id,
    )

    service = _build_service(db_session)

    created = await service.save_ticket_reply_draft(
        ticket.ticket_id, staff, TicketReplyDraftSaveRequest(message="First draft body")
    )
    assert created.message == "First draft body"
    assert created.ticket_id == ticket.ticket_id

    updated = await service.save_ticket_reply_draft(
        ticket.ticket_id,
        staff,
        TicketReplyDraftSaveRequest(
            message="Updated draft body", cc=["cc@example.com"], to_emails=["a@example.com"]
        ),
    )
    # Same row, upserted in place — not a second draft.
    assert updated.interaction_id == created.interaction_id
    assert updated.message == "Updated draft body"
    assert updated.cc == ["cc@example.com"]
    assert updated.to_emails == ["a@example.com"]

    fetched = await service.get_ticket_reply_draft(ticket.ticket_id, staff)
    assert fetched.interaction_id == created.interaction_id
    assert fetched.message == "Updated draft body"


async def test_get_ticket_reply_draft_404s_when_none_exists(db_session):
    team_lead, staff = await _staff_with_reply_permissions(db_session)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=staff.category.category_name,
        agent_id=staff.user_id,
    )

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.get_ticket_reply_draft(ticket.ticket_id, staff)
    assert exc_info.value.status_code == 404


async def test_discard_ticket_reply_draft_deletes_the_row(db_session):
    team_lead, staff = await _staff_with_reply_permissions(db_session)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=staff.category.category_name,
        agent_id=staff.user_id,
    )

    service = _build_service(db_session)
    await service.save_ticket_reply_draft(
        ticket.ticket_id, staff, TicketReplyDraftSaveRequest(message="To be discarded")
    )

    response = await service.discard_ticket_reply_draft(ticket.ticket_id, staff)
    assert response.message == "Draft discarded."

    with pytest.raises(HTTPException) as exc_info:
        await service.get_ticket_reply_draft(ticket.ticket_id, staff)
    assert exc_info.value.status_code == 404


async def test_send_ticket_reply_draft_delegates_to_add_reply_and_deletes_draft(db_session):
    """
    Mirrors send_draft/send_compose_draft's own established pattern:
    the actual send is delegated to the real add_reply, then the
    draft row is deleted. add_reply is monkeypatched here (this test
    is about delegation/cleanup, not the full envelope/dispatch
    pipeline, already covered elsewhere).
    """

    team_lead, staff = await _staff_with_reply_permissions(db_session)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=staff.category.category_name,
        agent_id=staff.user_id,
    )

    service = _build_service(db_session)
    draft = await service.save_ticket_reply_draft(
        ticket.ticket_id,
        staff,
        TicketReplyDraftSaveRequest(message="Ready to send", to_emails=["client@example.com"]),
    )

    captured = []

    async def _fake_add_reply(ticket_id, request, current_user):
        captured.append(request)
        from app.ticketing.schemas.ticket_action import TicketActionResponse

        return TicketActionResponse(
            interaction_id=uuid.uuid4(),
            ticket_id=ticket_id,
            message="Reply sent.",
            created_at=datetime.now(timezone.utc),
        )

    service.add_reply = _fake_add_reply

    response = await service.send_ticket_reply_draft(ticket.ticket_id, staff)

    assert response.message == "Reply sent."
    assert len(captured) == 1
    assert captured[0].message == "Ready to send"
    assert captured[0].to_emails == ["client@example.com"]

    with pytest.raises(HTTPException) as exc_info:
        await service.get_ticket_reply_draft(ticket.ticket_id, staff)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------
# Internal Note drafts
# ---------------------------------------------------------------


async def test_save_ticket_note_draft_creates_then_updates_in_place(db_session):
    team_lead, staff = await _staff_with_reply_permissions(db_session)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=staff.category.category_name,
        agent_id=staff.user_id,
    )

    service = _build_service(db_session)
    created = await service.save_ticket_note_draft(
        ticket.ticket_id,
        staff,
        TicketNoteDraftSaveRequest(subject="Draft subject", note="Draft note body"),
    )
    assert created.subject == "Draft subject"
    assert created.note == "Draft note body"

    updated = await service.save_ticket_note_draft(
        ticket.ticket_id,
        staff,
        TicketNoteDraftSaveRequest(
            subject="Updated subject",
            note="Updated note body",
            recipient_user_ids=[team_lead.user_id],
        ),
    )
    assert updated.interaction_id == created.interaction_id
    assert updated.subject == "Updated subject"
    assert updated.recipient_user_ids == [team_lead.user_id]


def test_ticket_note_draft_schema_has_no_email_field():
    """
    The structural guarantee behind Internal Note staying internal-
    only: there is no email-typed (or even plain string free-text
    recipient) field on this schema at all, only recipient_user_ids —
    identical in shape to InternalNoteCreate's own real-send schema.
    """

    fields = TicketNoteDraftSaveRequest.model_fields
    assert "recipient_user_ids" in fields
    assert not any("email" in name for name in fields)


async def test_send_ticket_note_draft_delegates_to_add_internal_note_and_deletes_draft(
    db_session,
):
    team_lead, staff = await _staff_with_reply_permissions(db_session)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=staff.category.category_name,
        agent_id=staff.user_id,
    )

    service = _build_service(db_session)
    await service.save_ticket_note_draft(
        ticket.ticket_id,
        staff,
        TicketNoteDraftSaveRequest(
            subject="Ready subject", note="Ready note", recipient_user_ids=[team_lead.user_id]
        ),
    )

    captured = []

    async def _fake_add_internal_note(ticket_id, request, current_user):
        captured.append(request)
        from app.ticketing.schemas.note import InternalNoteResponse

        return InternalNoteResponse(
            interaction_id=uuid.uuid4(),
            ticket_id=ticket_id,
            message="Internal note added successfully.",
            created_at=datetime.now(timezone.utc),
            recipient_user_ids=request.recipient_user_ids,
            recipient_names=[],
        )

    service.add_internal_note = _fake_add_internal_note

    response = await service.send_ticket_note_draft(ticket.ticket_id, staff)

    assert response.message == "Internal note added successfully."
    assert len(captured) == 1
    assert captured[0].subject == "Ready subject"
    assert captured[0].note == "Ready note"
    assert captured[0].recipient_user_ids == [team_lead.user_id]

    with pytest.raises(HTTPException) as exc_info:
        await service.get_ticket_note_draft(ticket.ticket_id, staff)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------
# Reply and Note drafts on the same ticket are independent
# ---------------------------------------------------------------


async def test_reply_and_note_drafts_on_same_ticket_do_not_collide(db_session):
    team_lead, staff = await _staff_with_reply_permissions(db_session)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=staff.category.category_name,
        agent_id=staff.user_id,
    )

    service = _build_service(db_session)
    reply_draft = await service.save_ticket_reply_draft(
        ticket.ticket_id, staff, TicketReplyDraftSaveRequest(message="Reply draft")
    )
    note_draft = await service.save_ticket_note_draft(
        ticket.ticket_id, staff, TicketNoteDraftSaveRequest(subject="s", note="Note draft")
    )

    assert reply_draft.interaction_id != note_draft.interaction_id

    fetched_reply = await service.get_ticket_reply_draft(ticket.ticket_id, staff)
    fetched_note = await service.get_ticket_note_draft(ticket.ticket_id, staff)
    assert fetched_reply.message == "Reply draft"
    assert fetched_note.note == "Note draft"


# ---------------------------------------------------------------
# DB-level: the real unique index (ix_interactions_one_ticket_draft_
# per_agent_per_type) actually exists and enforces uniqueness.
# ---------------------------------------------------------------


async def test_unique_index_prevents_a_second_active_reply_draft(db_session):
    team_lead, staff = await _staff_with_reply_permissions(db_session)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=staff.category.category_name,
        agent_id=staff.user_id,
    )

    from app.ticketing.enums import InteractionDirection
    from app.ticketing.models.interaction import Interaction
    from sqlalchemy.exc import IntegrityError

    first = Interaction(
        interaction_id=uuid.uuid4(),
        ticket_id=ticket.ticket_id,
        interaction_type="REPLY",
        direction=InteractionDirection.OUTBOUND,
        performed_by=staff.user_id,
        payload={"message": "first"},
        is_draft=True,
        is_visible=True,
    )
    db_session.add(first)
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            second = Interaction(
                interaction_id=uuid.uuid4(),
                ticket_id=ticket.ticket_id,
                interaction_type="REPLY",
                direction=InteractionDirection.OUTBOUND,
                performed_by=staff.user_id,
                payload={"message": "second"},
                is_draft=True,
                is_visible=True,
            )
            db_session.add(second)
            await db_session.flush()
