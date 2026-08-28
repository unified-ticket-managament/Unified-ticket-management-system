# test_internal_note_external_recipient_rejection.py
#
# Regression coverage for Issue 5 (Internal Note must never accept an
# external email address as a recipient). Investigated and found
# already correct in the current code — not reproducible — so this
# locks in the structural guarantee with tests rather than changing
# any production logic:
#
#   - InternalNoteCreate.recipient_user_ids is list[UUID] only; there
#     is no email-typed (or plain string free-text) field anywhere on
#     the schema an external address could travel through.
#   - InteractionService.add_internal_note resolves each id via
#     UserRepository.get_by_id and silently drops anything that isn't
#     a real, active platform user — an id that doesn't correspond to
#     an existing user (the closest a caller could get to "external")
#     is dropped, not rejected with an error, but never added either.
#   - The frontend's own UserMultiSelect.tsx (a closed-roster chip
#     picker) has no Enter/comma free-text-commit path at all — see
#     that component's own handleKeyDown, which only handles
#     Backspace-to-remove. If this is still observed live, it's far
#     more likely a stale/un-restarted backend process (a documented,
#     recurring gotcha in this repo) than a code bug.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention/helpers as
# test_ticket_draft.py.

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
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
from app.ticketing.schemas.note import InternalNoteCreate
from app.ticketing.services.interaction_service import InteractionService


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def test_internal_note_create_schema_has_no_email_field():
    """
    The structural guarantee itself: there is no email-typed (or
    plain string free-text) recipient field on this schema at all,
    only recipient_user_ids: list[UUID].
    """

    fields = InternalNoteCreate.model_fields
    assert "recipient_user_ids" in fields
    assert not any("email" in name for name in fields)


def test_internal_note_create_rejects_a_raw_email_string_as_a_recipient():
    """
    Even attempting to smuggle an external address into
    recipient_user_ids fails at construction time — list[UUID]
    rejects a non-UUID string before this ever reaches the service
    layer or the database.
    """

    with pytest.raises(ValidationError):
        InternalNoteCreate(
            subject="s",
            note="n",
            recipient_user_ids=["external-person@example.com"],
        )


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
        name="Internal-note-rejection Test Client",
        inbox_email=f"internal-note-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=agent_id,
        title="Internal-note-rejection regression test ticket",
        ticket_type=ticket_type,
        current_status="IN_PROGRESS",
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()
    return client, ticket


async def test_add_internal_note_silently_drops_a_nonexistent_recipient_id(db_session):
    """
    An id with no matching real user (the closest a caller could get
    to smuggling in "someone external", since the schema itself has
    no email field) is silently excluded from the note's recipients —
    never added, and never a crash/error either.
    """

    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    staff.permissions = ["communication:reply_internal", "ticket:editown_ticket"]
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=staff.category.category_name,
        agent_id=staff.user_id,
    )

    service = InteractionService(
        interaction_repository=InteractionRepository(db_session),
        ticket_repository=TicketRepository(db_session),
        user_repository=UserRepository(db_session),
        client_repository=ClientRepository(db_session),
    )

    nonexistent_id = uuid.uuid4()
    response = await service.add_internal_note(
        ticket.ticket_id,
        InternalNoteCreate(
            subject="Test subject",
            note="Test note body",
            recipient_user_ids=[nonexistent_id, team_lead.user_id],
        ),
        staff,
    )

    # The real user is kept, the nonexistent id is silently dropped —
    # not an error, and definitely not delivered to "someone external".
    assert nonexistent_id not in response.recipient_user_ids
    assert team_lead.user_id in response.recipient_user_ids
