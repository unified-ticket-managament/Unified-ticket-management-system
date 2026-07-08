from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent
from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.client_repository import ClientRepository
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.mail_folder_repository import MailFolderRepository
from app.repositories.ticket_repository import TicketRepository
from app.repositories.user_repository import UserRepository
from app.schemas.inbox import DraftListResponse, InboxResponse, SentResponse
from app.schemas.interaction import (
    DraftDeleteResponse,
    DraftResponse,
    DraftSaveRequest,
    FolderAssignRequest,
    InteractionArchiveResponse,
    InteractionClaimResponse,
    InteractionFolderResponse,
    InteractionSnoozeResponse,
    InteractionTagsResponse,
    SnoozeRequest,
    TagsUpdateRequest,
)
from app.schemas.open_email import OpenEmailResponse
from app.schemas.ticket_action import (
    InteractionReplyRequest,
    InteractionReplyResponse,
)
from app.services.inbox_service import InboxService
from app.services.open_email_service import OpenEmailService
from app.services.interaction_service import InteractionService
from app.storage import get_storage_service

router = APIRouter(
    prefix="/inbox",
    tags=["Inbox"],
)


# ---------------------------------------------------------
# Account Manager Inbox
# ---------------------------------------------------------

@router.get(
    "",
    response_model=InboxResponse,
)
async def get_inbox(
    client_id: UUID | None = Query(default=None),
    folder_id: UUID | None = Query(default=None),
    view: str = Query(default="pending", pattern="^(pending|replied|ticketed|archived|snoozed|all)$"),
    scope: str = Query(default="mine", pattern="^(mine|all)$"),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the mail belonging to the clients the authenticated user
    manages.

    `view` selects which root emails: not-yet-actioned ("pending"),
    replied-but-never-ticketed ("replied"), promoted-to-a-ticket
    ("ticketed"), marked Informational/Archive ("archived"), hidden
    until a future time ("snoozed"), or every one of them ("all").

    `folder_id` further narrows to one custom folder — orthogonal to
    `view`, composes with any of the above.

    `scope="all"` is the "All Inboxes" escape hatch — every client's
    mail, not just this user's own. Only takes effect for Team Lead /
    Account Manager / Site Lead / Super Admin; ignored for anyone else.
    """

    repository = InteractionRepository(db)
    attachment_repository = AttachmentRepository(db)
    user_repository = UserRepository(db)

    service = InboxService(
        repository,
        attachment_repository=attachment_repository,
        user_repository=user_repository,
    )

    return await service.get_inbox(
        current_user,
        client_id=client_id,
        view=view,
        scope=scope,
        folder_id=folder_id,
    )


# ---------------------------------------------------------
# Sent / Drafts (list views)
# ---------------------------------------------------------
#
# Registered before the "/{interaction_id}" path-param routes below
# (open_email in particular) — FastAPI matches routes in registration
# order, and "/inbox/sent"/"/inbox/drafts" would otherwise be
# swallowed by "/inbox/{interaction_id}" trying (and failing) to
# parse "sent"/"drafts" as a UUID.

@router.get(
    "/sent",
    response_model=SentResponse,
)
async def get_sent(
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Every reply the current user has sent, pre-ticket or ticket-level alike."""

    repository = InteractionRepository(db)

    service = InboxService(repository)

    return await service.get_sent(current_user)


@router.get(
    "/drafts",
    response_model=DraftListResponse,
)
async def get_drafts(
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Every draft the current user currently has saved, across every thread."""

    repository = InteractionRepository(db)

    service = InboxService(repository)

    return await service.get_drafts(current_user)


# ---------------------------------------------------------
# Claim ("Assign to me")
# ---------------------------------------------------------

@router.post(
    "/{interaction_id}/claim",
    response_model=InteractionClaimResponse,
    status_code=201,
)
async def claim_interaction(
    interaction_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Claims a pending, unticketed inbox item for the authenticated
    user — "Assign to me". Race-guarded: if two agents claim the same
    item at once, exactly one succeeds and the other gets a 409.
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.claim_interaction(
        interaction_id=interaction_id,
        current_user=current_user,
    )


# ---------------------------------------------------------
# Archive ("Informational / Archive")
# ---------------------------------------------------------

@router.post(
    "/{interaction_id}/archive",
    response_model=InteractionArchiveResponse,
    status_code=200,
)
async def archive_interaction(
    interaction_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Marks a pending, unticketed inbox item Informational/Archive —
    stored, no ticket, no work assignment, still searchable under the
    "archived" inbox view.
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.archive_interaction(
        interaction_id=interaction_id,
        current_user=current_user,
    )


# ---------------------------------------------------------
# Snooze / Unsnooze
# ---------------------------------------------------------

@router.post(
    "/{interaction_id}/snooze",
    response_model=InteractionSnoozeResponse,
    status_code=200,
)
async def snooze_interaction(
    interaction_id: UUID,
    request: SnoozeRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Hides a pending, unticketed inbox item from the "pending" view
    until `snooze_until` — it resurfaces there automatically once
    that time passes, no background job needed.
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.snooze_interaction(
        interaction_id=interaction_id,
        request=request,
        current_user=current_user,
    )


@router.post(
    "/{interaction_id}/unsnooze",
    response_model=InteractionSnoozeResponse,
    status_code=200,
)
async def unsnooze_interaction(
    interaction_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Clears an active snooze early, returning the item to "pending" immediately."""

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.unsnooze_interaction(
        interaction_id=interaction_id,
        current_user=current_user,
    )


# ---------------------------------------------------------
# Tags
# ---------------------------------------------------------

@router.patch(
    "/{interaction_id}/tags",
    response_model=InteractionTagsResponse,
    status_code=200,
)
async def update_interaction_tags(
    interaction_id: UUID,
    request: TagsUpdateRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Full-replaces the tag list on a mail item."""

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.set_interaction_tags(
        interaction_id=interaction_id,
        request=request,
        current_user=current_user,
    )


# ---------------------------------------------------------
# Folder assignment
# ---------------------------------------------------------

@router.patch(
    "/{interaction_id}/folder",
    response_model=InteractionFolderResponse,
    status_code=200,
)
async def update_interaction_folder(
    interaction_id: UUID,
    request: FolderAssignRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Files (or unfiles, if folder_id is null) a mail item into a custom folder."""

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    mail_folder_repository = MailFolderRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
        mail_folder_repository=mail_folder_repository,
    )

    return await service.set_interaction_folder(
        interaction_id=interaction_id,
        request=request,
        current_user=current_user,
    )


# ---------------------------------------------------------
# Drafts (per-thread actions)
# ---------------------------------------------------------

@router.put(
    "/{interaction_id}/draft",
    response_model=DraftResponse,
    status_code=200,
)
async def save_draft(
    interaction_id: UUID,
    request: DraftSaveRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Upserts the current user's draft reply on this thread."""

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.save_draft(
        interaction_id=interaction_id,
        request=request,
        current_user=current_user,
    )


@router.post(
    "/{interaction_id}/draft/send",
    response_model=InteractionReplyResponse,
    status_code=201,
)
async def send_draft(
    interaction_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Sends the current user's draft on this thread as a real reply."""

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.send_draft(
        interaction_id=interaction_id,
        current_user=current_user,
    )


@router.delete(
    "/{interaction_id}/draft",
    response_model=DraftDeleteResponse,
    status_code=200,
)
async def discard_draft(
    interaction_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Deletes the current user's draft on this thread without sending it."""

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.discard_draft(
        interaction_id=interaction_id,
        current_user=current_user,
    )


# ---------------------------------------------------------
# Open Email / Thread
# ---------------------------------------------------------

@router.get(
    "/{interaction_id}",
    response_model=OpenEmailResponse,
)
async def open_email(
    interaction_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the complete details of one inbox email, plus every
    reply already filed under it.
    """

    repository = InteractionRepository(db)
    attachment_repository = AttachmentRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    ticket_repository = TicketRepository(db)

    service = OpenEmailService(
        repository,
        attachment_repository=attachment_repository,
        storage_service=get_storage_service(),
        user_repository=user_repository,
        client_repository=client_repository,
        ticket_repository=ticket_repository,
    )

    return await service.get_email_details(
        interaction_id=interaction_id,
        current_user=current_user,
    )


# ---------------------------------------------------------
# Reply (bare interaction — no ticket)
# ---------------------------------------------------------

@router.post(
    "/{interaction_id}/reply",
    response_model=InteractionReplyResponse,
    status_code=201,
)
async def reply_to_interaction(
    interaction_id: UUID,
    request: InteractionReplyRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Replies to a client on an inbox conversation that hasn't become
    a ticket — the "general communication" path (e.g. "are you
    working today?" -> reply -> done, no ticket needed).
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.add_interaction_reply(
        interaction_id=interaction_id,
        request=request,
        current_user=current_user,
    )
