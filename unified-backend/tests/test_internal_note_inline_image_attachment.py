# test_internal_note_inline_image_attachment.py
#
# Regression coverage for a real bug: POST /tickets/{ticket_id}/notes
# (api/ticket.py's add_internal_note route) built its InteractionService
# without attachment_repository/storage_service, so
# InteractionService.add_internal_note's own call to
# _reassign_inline_image_interactions silently no-oped (that method
# returns [] immediately when self.attachment_repository is None) for
# every internal note, regardless of what inline_image_interaction_ids
# the frontend sent. A pasted screenshot's Attachment row was therefore
# never moved off its staging ATTACHMENT interaction onto the note's own
# interaction_id — the note's body_html still referenced the image via
# cid:{content_id}, but the note's own `.attachments` stayed empty, so
# the frontend's resolveCidImagesForDisplay() had nothing to match the
# cid: against and rendered "[image unavailable]" wherever the note was
# read back (Interaction Details drawer, Full Interaction page).
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_internal_note_recipients.py / test_escalation_read_only_access.py.
# Run this file in isolation rather than alongside other DB-touching
# test files in the same pytest process (pre-existing pytest-asyncio
# event-loop issue documented in the root CLAUDE.md).

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import TicketPriority
from app.ticketing.models.attachment import Attachment
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.attachment import AttachmentCreate
from app.ticketing.schemas.interaction import InteractionCreate
from app.ticketing.schemas.note import InternalNoteCreate
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.enums import InteractionDirection, InteractionStatus


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


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


async def _make_ticket_for_sender(session, sender: User) -> Ticket:
    client = Client(
        client_id=uuid.uuid4(),
        name=f"Inline Image Note Test Client {uuid.uuid4().hex[:8]}",
        inbox_email=f"inline-note-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=sender.user_id,
        is_active=True,
    )
    session.add(client)

    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client.client_id,
        agent_id=sender.user_id,
        title="Internal Note inline image test ticket",
        ticket_type="Eligibility",
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()
    return ticket


async def _stage_pasted_image(session, ticket: Ticket, sender: User):
    """
    Mirrors what AttachmentService.upload_inline_image (the real
    POST /tickets/{id}/attachments/inline-image endpoint) does at
    paste time: a standalone ATTACHMENT interaction holding one
    is_inline=True Attachment row with a real content_id, exactly the
    shape a composer's inline_image_interaction_ids entry points at.
    """

    interaction_repository = InteractionRepository(session)
    attachment_repository = AttachmentRepository(session)

    staging_interaction = await interaction_repository.create(
        InteractionCreate(
            ticket_id=ticket.ticket_id,
            interaction_type="ATTACHMENT",
            direction=InteractionDirection.INTERNAL,
            status=InteractionStatus.ASSIGNED,
            performed_by=sender.user_id,
            payload={"file_count": 1, "is_inline": True},
            is_visible=True,
        )
    )

    content_id = uuid.uuid4().hex
    attachment = await attachment_repository.create(
        AttachmentCreate(
            interaction_id=staging_interaction.interaction_id,
            filename="screenshot.png",
            mime_type="image/png",
            size_bytes=1234,
            storage_key=f"test/{uuid.uuid4().hex}.png",
            bucket_name="test-bucket",
            content_id=content_id,
            is_inline=True,
        )
    )

    return staging_interaction, attachment


async def test_internal_note_reassigns_pasted_image_when_attachment_repository_is_wired(db_session):
    """
    This is the FIXED shape: InteractionService constructed with
    attachment_repository set, exactly like api/ticket.py's
    add_internal_note route now builds it. The pasted image's
    Attachment row must end up on the note's own interaction_id, and
    the staging interaction must be hidden — otherwise cid: resolution
    on read-back has nothing to match.
    """

    sender = await _get_user_by_role(db_session, "Account Manager")
    sender.permissions = ["ticket:reply", "communication:reply_internal", "ticket:editown_ticket"]
    ticket = await _make_ticket_for_sender(db_session, sender)

    staging_interaction, attachment = await _stage_pasted_image(db_session, ticket, sender)

    service = InteractionService(
        interaction_repository=InteractionRepository(db_session),
        ticket_repository=TicketRepository(db_session),
        user_repository=UserRepository(db_session),
        client_repository=ClientRepository(db_session),
        attachment_repository=AttachmentRepository(db_session),
        storage_service=None,
    )

    response = await service.add_internal_note(
        ticket.ticket_id,
        InternalNoteCreate(
            subject="Screenshot attached",
            note="See attached.",
            body_html=f'<p><img src="cid:{attachment.content_id}"></p>',
            inline_image_interaction_ids=[staging_interaction.interaction_id],
        ),
        sender,
    )

    attachment_repository = AttachmentRepository(db_session)

    reassigned = await attachment_repository.list_by_interaction_id(response.interaction_id)
    assert len(reassigned) == 1
    assert reassigned[0].attachment_id == attachment.attachment_id
    assert reassigned[0].content_id == attachment.content_id

    still_on_staging = await attachment_repository.list_by_interaction_id(
        staging_interaction.interaction_id
    )
    assert still_on_staging == []

    interaction_repository = InteractionRepository(db_session)
    refreshed_staging = await interaction_repository.get_by_id(staging_interaction.interaction_id)
    assert refreshed_staging.is_visible is False


async def test_internal_note_silently_drops_pasted_image_without_attachment_repository(db_session):
    """
    Documents the actual bug being fixed: with attachment_repository
    omitted (the pre-fix shape of the /notes route's InteractionService
    construction), _reassign_inline_image_interactions short-circuits
    to a no-op — the note is still created successfully (no error
    surfaced to the caller), but the pasted image's Attachment row is
    silently left on its staging interaction, orphaned from the note
    that references it via cid:.
    """

    sender = await _get_user_by_role(db_session, "Account Manager")
    sender.permissions = ["ticket:reply", "communication:reply_internal", "ticket:editown_ticket"]
    ticket = await _make_ticket_for_sender(db_session, sender)

    staging_interaction, attachment = await _stage_pasted_image(db_session, ticket, sender)

    broken_service = InteractionService(
        interaction_repository=InteractionRepository(db_session),
        ticket_repository=TicketRepository(db_session),
        user_repository=UserRepository(db_session),
        client_repository=ClientRepository(db_session),
        # attachment_repository intentionally omitted — the pre-fix shape.
    )

    response = await broken_service.add_internal_note(
        ticket.ticket_id,
        InternalNoteCreate(
            subject="Screenshot attached",
            note="See attached.",
            body_html=f'<p><img src="cid:{attachment.content_id}"></p>',
            inline_image_interaction_ids=[staging_interaction.interaction_id],
        ),
        sender,
    )

    attachment_repository = AttachmentRepository(db_session)

    on_note = await attachment_repository.list_by_interaction_id(response.interaction_id)
    assert on_note == [], "bug reproduction: note ends up with no reassigned attachment"

    still_on_staging = await attachment_repository.list_by_interaction_id(
        staging_interaction.interaction_id
    )
    assert len(still_on_staging) == 1, "attachment is orphaned on its staging interaction"
