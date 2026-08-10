# test_ticket_attachments.py
#
# Regression coverage for "all ticket attachments must be visible"
# (UTMS ticketing/mail bug-fix pass). Root cause (see
# InteractionService.get_ticket_interactions's own comment): that
# method deliberately always returns `attachments: []` per interaction
# row, a performance optimization for the Timeline tab — but the
# frontend's Attachments tab used to derive its list from that exact
# same response, so real, correctly-stored attachments never showed up
# there regardless of interaction type.
#
# Fixed with a dedicated InteractionService.get_ticket_attachments
# method (GET /tickets/{id}/attachments) that batch-fetches every
# attachment across every interaction on the ticket, reusing the exact
# same AttachmentRepository.list_by_interaction_ids + attachments_to_metadata
# pattern get_thread already uses for one conversation's attachments.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_transfer_agent_ownership.py.

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, TicketPriority
from app.ticketing.models.attachment import Attachment
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.storage.base import StorageService


class FakeStorageService(StorageService):
    """
    Minimal in-memory stand-in — the tests below only ever exercise
    the read/download-URL-signing path (attachments_to_metadata),
    never upload/download/delete/exists, so those raise if reached.
    """

    async def upload(self, *, data: bytes, object_key: str, content_type: str) -> None:
        raise NotImplementedError

    async def download(self, *, object_key: str) -> bytes:
        raise NotImplementedError

    async def delete(self, *, object_key: str) -> None:
        raise NotImplementedError

    async def exists(self, *, object_key: str) -> bool:
        raise NotImplementedError

    async def presigned_get_url(
        self, *, object_key: str, filename: str, inline: bool = False
    ) -> str:
        return f"https://fake-storage.test/{object_key}"


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _find_team_lead_with_staff(session, staff_count: int) -> tuple[User, list[User]]:
    team_lead_result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Team Lead", User.is_active.is_(True))
    )
    team_leads = [
        user for user in team_lead_result.unique().scalars().all() if user.category is not None
    ]

    staff_result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Staff", User.is_active.is_(True))
    )
    staff_by_category: dict[str, list[User]] = {}
    for user in staff_result.unique().scalars().all():
        if user.category is None:
            continue
        staff_by_category.setdefault(user.category.category_name.value, []).append(user)

    for team_lead in team_leads:
        candidates = staff_by_category.get(team_lead.category.category_name.value, [])
        if len(candidates) >= staff_count:
            return team_lead, candidates[:staff_count]

    pytest.skip(
        f"No category currently has both an active Team Lead and {staff_count} "
        "active Staff in the connected database."
    )


async def _get_account_manager(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Account Manager", User.is_active.is_(True))
    )
    users = result.unique().scalars().all()
    if users:
        return users[0]
    pytest.skip("No active seeded Account Manager found.")


async def _make_ticket(session, *, account_manager_id, ticket_type, agent_id=None):
    client = Client(
        client_id=uuid.uuid4(),
        name="Attachments Test Client",
        inbox_email=f"attachments-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=agent_id,
        title="Attachments regression test ticket",
        ticket_type=ticket_type,
        current_status="IN_PROGRESS",
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()
    return client, ticket


async def _add_interaction_with_attachment(
    session,
    *,
    ticket_id,
    interaction_type,
    direction,
    performed_by=None,
    filename="file.pdf",
):
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        ticket_id=ticket_id,
        interaction_type=interaction_type,
        direction=direction,
        performed_by=performed_by,
        payload={},
        created_at=datetime.now(timezone.utc),
    )
    session.add(interaction)
    await session.flush()

    attachment = Attachment(
        attachment_id=uuid.uuid4(),
        interaction_id=interaction.interaction_id,
        filename=filename,
        mime_type="application/pdf",
        size_bytes=1024,
        storage_key=f"tickets/{ticket_id}/{uuid.uuid4().hex}.pdf",
        bucket_name="test-bucket",
    )
    session.add(attachment)
    await session.flush()
    return interaction, attachment


def _build_service(session) -> InteractionService:
    return InteractionService(
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        client_repository=ClientRepository(session),
        attachment_repository=AttachmentRepository(session),
        storage_service=FakeStorageService(),
    )


# ---------------------------------------------------------------
# 1-4: one attachment per interaction type is returned.
# ---------------------------------------------------------------


async def test_inbound_email_attachment_is_returned(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )
    _interaction, attachment = await _add_interaction_with_attachment(
        db_session,
        ticket_id=ticket.ticket_id,
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        filename="inbound.pdf",
    )

    service = _build_service(db_session)
    rows = await service.get_ticket_attachments(ticket.ticket_id, team_lead)

    assert len(rows) == 1
    assert rows[0].id == attachment.attachment_id
    assert rows[0].filename == "inbound.pdf"
    assert rows[0].interaction_type == "EMAIL"


async def test_outbound_email_attachment_is_returned(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )
    _interaction, attachment = await _add_interaction_with_attachment(
        db_session,
        ticket_id=ticket.ticket_id,
        interaction_type="REPLY",
        direction=InteractionDirection.OUTBOUND,
        performed_by=staff.user_id,
        filename="outbound-reply.pdf",
    )

    service = _build_service(db_session)
    rows = await service.get_ticket_attachments(ticket.ticket_id, team_lead)

    assert len(rows) == 1
    assert rows[0].id == attachment.attachment_id
    assert rows[0].performed_by == staff.user_id
    assert rows[0].performed_by_name == staff.name


async def test_internal_note_attachment_is_returned(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )
    _interaction, attachment = await _add_interaction_with_attachment(
        db_session,
        ticket_id=ticket.ticket_id,
        interaction_type="INTERNAL_NOTE",
        direction=InteractionDirection.INTERNAL,
        performed_by=team_lead.user_id,
        filename="internal-note-file.pdf",
    )

    service = _build_service(db_session)
    rows = await service.get_ticket_attachments(ticket.ticket_id, team_lead)

    assert len(rows) == 1
    assert rows[0].id == attachment.attachment_id
    assert rows[0].interaction_type == "INTERNAL_NOTE"


async def test_direct_ticket_upload_attachment_is_returned(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )
    _interaction, attachment = await _add_interaction_with_attachment(
        db_session,
        ticket_id=ticket.ticket_id,
        interaction_type="ATTACHMENT",
        direction=InteractionDirection.INTERNAL,
        performed_by=staff.user_id,
        filename="direct-upload.png",
    )

    service = _build_service(db_session)
    rows = await service.get_ticket_attachments(ticket.ticket_id, team_lead)

    assert len(rows) == 1
    assert rows[0].id == attachment.attachment_id
    assert rows[0].interaction_type == "ATTACHMENT"


# ---------------------------------------------------------------
# 5. Multiple attachment types together — every one is aggregated.
# ---------------------------------------------------------------


async def test_multiple_attachment_types_are_all_aggregated(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )

    expected_ids = set()
    for interaction_type, direction, performer in [
        ("EMAIL", InteractionDirection.INBOUND, None),
        ("REPLY", InteractionDirection.OUTBOUND, staff.user_id),
        ("INTERNAL_NOTE", InteractionDirection.INTERNAL, team_lead.user_id),
        ("ATTACHMENT", InteractionDirection.INTERNAL, staff.user_id),
    ]:
        _interaction, attachment = await _add_interaction_with_attachment(
            db_session,
            ticket_id=ticket.ticket_id,
            interaction_type=interaction_type,
            direction=direction,
            performed_by=performer,
            filename=f"{interaction_type.lower()}.pdf",
        )
        expected_ids.add(attachment.attachment_id)

    service = _build_service(db_session)
    rows = await service.get_ticket_attachments(ticket.ticket_id, team_lead)

    assert {row.id for row in rows} == expected_ids
    assert len(rows) == 4


# ---------------------------------------------------------------
# 6. An attachment belonging to another ticket is excluded.
# ---------------------------------------------------------------


async def test_attachment_from_another_ticket_is_excluded(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client_a, ticket_a = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )
    _client_b, ticket_b = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )

    _interaction_a, attachment_a = await _add_interaction_with_attachment(
        db_session,
        ticket_id=ticket_a.ticket_id,
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        filename="ticket-a-file.pdf",
    )
    await _add_interaction_with_attachment(
        db_session,
        ticket_id=ticket_b.ticket_id,
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        filename="ticket-b-file.pdf",
    )

    service = _build_service(db_session)
    rows = await service.get_ticket_attachments(ticket_a.ticket_id, team_lead)

    assert len(rows) == 1
    assert rows[0].id == attachment_a.attachment_id
    assert rows[0].filename == "ticket-a-file.pdf"


# ---------------------------------------------------------------
# 7. Duplicate attachments are not returned.
# ---------------------------------------------------------------


async def test_no_duplicate_attachments_for_repeated_calls_or_multiple_files(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )

    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        ticket_id=ticket.ticket_id,
        interaction_type="ATTACHMENT",
        direction=InteractionDirection.INTERNAL,
        performed_by=staff.user_id,
        payload={},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(interaction)
    await db_session.flush()

    attachment_ids = set()
    for i in range(3):
        attachment = Attachment(
            attachment_id=uuid.uuid4(),
            interaction_id=interaction.interaction_id,
            filename=f"multi-{i}.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            storage_key=f"tickets/{ticket.ticket_id}/{uuid.uuid4().hex}.pdf",
            bucket_name="test-bucket",
        )
        db_session.add(attachment)
        attachment_ids.add(attachment.attachment_id)
    await db_session.flush()

    service = _build_service(db_session)
    rows = await service.get_ticket_attachments(ticket.ticket_id, team_lead)
    assert {row.id for row in rows} == attachment_ids
    assert len(rows) == 3

    # Calling again returns the identical set, not a growing one —
    # this is a pure read, nothing is created/duplicated as a side
    # effect of listing.
    rows_again = await service.get_ticket_attachments(ticket.ticket_id, team_lead)
    assert {row.id for row in rows_again} == attachment_ids
    assert len(rows_again) == 3


# ---------------------------------------------------------------
# 8. RBAC restrictions remain enforced.
# ---------------------------------------------------------------


async def test_account_manager_cannot_view_attachments_for_another_clients_ticket(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)
    other_account_manager = await _get_account_manager(db_session)

    _client, ticket = await _make_ticket(
        db_session,
        # Owned by a *different* Account Manager than the one making
        # the request below.
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )
    await _add_interaction_with_attachment(
        db_session,
        ticket_id=ticket.ticket_id,
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        filename="restricted.pdf",
    )

    if other_account_manager.user_id == (team_lead.manager_id or team_lead.user_id):
        pytest.skip("Need an Account Manager who does not own this ticket's client.")

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.get_ticket_attachments(ticket.ticket_id, other_account_manager)
    assert exc_info.value.status_code == 403


async def test_team_lead_outside_category_cannot_view_attachments(db_session):
    team_lead, [staff] = await _find_team_lead_with_staff(db_session, 1)

    # Find a second Team Lead in a *different* category, if one
    # exists in the connected database.
    result = await db_session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Team Lead", User.is_active.is_(True))
    )
    other_team_lead = None
    for candidate in result.unique().scalars().all():
        if (
            candidate.category is not None
            and candidate.category.category_name.value != team_lead.category.category_name.value
        ):
            other_team_lead = candidate
            break
    if other_team_lead is None:
        pytest.skip("No Team Lead in a different category exists in the connected database.")

    _client, ticket = await _make_ticket(
        db_session,
        account_manager_id=team_lead.manager_id or team_lead.user_id,
        ticket_type=team_lead.category.category_name.value,
        agent_id=staff.user_id,
    )
    await _add_interaction_with_attachment(
        db_session,
        ticket_id=ticket.ticket_id,
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        filename="category-restricted.pdf",
    )

    service = _build_service(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await service.get_ticket_attachments(ticket.ticket_id, other_team_lead)
    assert exc_info.value.status_code == 403
