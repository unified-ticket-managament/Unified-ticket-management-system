from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.schemas.attachment import AttachmentMetadata
from app.ticketing.repositories.interaction_repository import (
    InteractionRepository,
)
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.ticket_edit_access_repository import (
    TicketEditAccessRequestRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.compose import ComposeEmailRequest, ComposeEmailResponse
from app.ticketing.schemas.inbox import DraftListResponse, InboxResponse, SentResponse
from app.ticketing.schemas.interaction import (
    DraftDeleteResponse,
    DraftResponse,
    DraftSaveRequest,
    DraftSendRequest,
    FolderAssignRequest,
    InteractionArchiveResponse,
    InteractionClaimResponse,
    InteractionFolderResponse,
    InteractionTagsResponse,
    TagsUpdateRequest,
)
from app.ticketing.schemas.open_email import OpenEmailResponse
from app.ticketing.schemas.ticket_action import (
    InteractionReplyRequest,
    InteractionReplyResponse,
)
from app.ticketing.services.attachment_service import AttachmentService, attachments_to_metadata
from app.ticketing.services.inbox_service import InboxService
from app.ticketing.services.open_email_service import OpenEmailService
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.sla_service import build_sla_service
from app.ticketing.storage import get_storage_service

router = APIRouter(
    prefix="/inbox",
    tags=["Inbox"],
)


def _split_emails(raw: str | None) -> list[str]:
    """
    The Compose form sends Cc/Bcc as a single comma-separated Form
    field (a multipart request can't carry a JSON array field
    alongside file uploads the way a plain JSON body could) — this
    splits and drops blanks/whitespace so an empty field cleanly
    becomes an empty list rather than `[""]`.
    """

    if not raw:
        return []
    return [email.strip() for email in raw.split(",") if email.strip()]


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
    view: str = Query(default="pending", pattern="^(pending|replied|ticketed|archived|all)$"),
    scope: str = Query(default="mine", pattern="^(mine|all)$"),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the mail belonging to the clients the authenticated user
    manages.

    `view` selects which root emails: not-yet-actioned ("pending"),
    replied-but-never-ticketed ("replied"), promoted-to-a-ticket
    ("ticketed"), marked Informational/Archive ("archived"), or every
    one of them ("all").

    `folder_id` further narrows to one custom folder — orthogonal to
    `view`, composes with any of the above.

    `scope="all"` is the "All Inboxes" escape hatch — every client's
    mail, not just this user's own. Only takes effect for Team Lead /
    Account Manager / Site Lead / Super Admin; ignored for anyone else.
    """

    repository = InteractionRepository(db)
    attachment_repository = AttachmentRepository(db)
    user_repository = UserRepository(db)
    ticket_repository = TicketRepository(db)
    edit_access_repository = TicketEditAccessRequestRepository(db)

    service = InboxService(
        repository,
        attachment_repository=attachment_repository,
        user_repository=user_repository,
        ticket_repository=ticket_repository,
        edit_access_repository=edit_access_repository,
    )

    return await service.get_inbox(
        current_user,
        client_id=client_id,
        view=view,
        scope=scope,
        folder_id=folder_id,
    )


@router.get(
    "/folder-counts",
    response_model=dict[UUID, int],
)
async def get_folder_counts(
    client_id: UUID | None = Query(default=None),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Every custom folder's item count in one query, under the same
    role scoping as GET /inbox — backs the Mail sidebar's per-folder
    badges without calling GET /inbox once per folder just to read
    `.total`.
    """

    repository = InteractionRepository(db)
    edit_access_repository = TicketEditAccessRequestRepository(db)

    service = InboxService(
        repository,
        edit_access_repository=edit_access_repository,
    )

    return await service.get_folder_counts(current_user, client_id=client_id)


@router.get(
    "/view-counts",
    response_model=dict[str, int],
)
async def get_view_counts(
    client_id: UUID | None = Query(default=None),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Pending/Replied/Ticketed/Archived/All badge counts in one query,
    under the same role scoping as GET /inbox — lets the Mail
    sidebar show accurate tab counts without fetching each tab's
    actual row data until it's opened.
    """

    repository = InteractionRepository(db)
    edit_access_repository = TicketEditAccessRequestRepository(db)

    service = InboxService(
        repository,
        edit_access_repository=edit_access_repository,
    )

    return await service.get_view_counts(current_user, client_id=client_id)


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
# Compose — brand-new outbound email, no prior thread
# ---------------------------------------------------------
#
# Registered before "/{interaction_id}" for the same reason /sent and
# /drafts are above — a static path segment must be matched before
# FastAPI tries (and fails) to parse "compose" as a UUID.

@router.post(
    "/compose",
    response_model=ComposeEmailResponse,
    status_code=201,
)
async def compose_email(
    client_id: UUID = Form(...),
    to_email: str = Form(...),
    subject: str = Form(...),
    message: str = Form(...),
    cc: str = Form(default=""),
    bcc: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Authors a brand-new outbound email to one of the platform's
    clients — the "Compose" action, the one Mail path with no
    existing interaction to reply onto. Multipart (rather than a
    plain JSON body, like every other Mail endpoint) purely so
    attachments can ride along in the same request, mirroring
    POST /tickets/{id}/attachments.
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    attachment_repository = AttachmentRepository(db)
    storage_service = get_storage_service()

    interaction_service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    composed = await interaction_service.compose_email(
        request=ComposeEmailRequest(
            client_id=client_id,
            to_email=to_email,
            subject=subject,
            message=message,
            cc=_split_emails(cc),
            bcc=_split_emails(bcc),
        ),
        current_user=current_user,
    )

    if files:
        attachment_service = AttachmentService(
            attachment_repository=attachment_repository,
            interaction_repository=interaction_repository,
            ticket_repository=ticket_repository,
            storage_service=storage_service,
        )
        stored = await attachment_service.validate_and_store_files(
            files, composed.interaction_id
        )
        composed.attachments = await attachments_to_metadata(stored, storage_service)

    return composed


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
        sla_service=build_sla_service(db),
    )

    return await service.archive_interaction(
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
    """Upserts the current user's draft reply (message + Cc/Bcc) on this thread."""

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    attachment_repository = AttachmentRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
        attachment_repository=attachment_repository,
        storage_service=get_storage_service(),
    )

    return await service.save_draft(
        interaction_id=interaction_id,
        request=request,
        current_user=current_user,
    )


@router.post(
    "/{interaction_id}/draft/attachments",
    response_model=list[AttachmentMetadata],
    status_code=201,
)
async def upload_draft_attachment(
    interaction_id: UUID,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Attaches files to the current user's in-progress draft on this
    thread — works pre-ticket, unlike POST /tickets/{id}/attachments,
    since attachments are always stored against an interaction_id
    (never a ticket_id) at the data-model level.
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    attachment_repository = AttachmentRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
        attachment_repository=attachment_repository,
        storage_service=get_storage_service(),
    )

    return await service.upload_draft_attachment(
        interaction_id=interaction_id,
        files=files,
        current_user=current_user,
    )


@router.post(
    "/{interaction_id}/draft/send",
    response_model=InteractionReplyResponse,
    status_code=201,
)
async def send_draft(
    interaction_id: UUID,
    body: DraftSendRequest | None = None,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Sends the current user's draft on this thread as a real reply."""

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    attachment_repository = AttachmentRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
        attachment_repository=attachment_repository,
        storage_service=get_storage_service(),
    )

    return await service.send_draft(
        interaction_id=interaction_id,
        current_user=current_user,
        to_email=body.to_email if body else None,
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
    """Deletes the current user's draft (and any of its attachments) without sending it."""

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    attachment_repository = AttachmentRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
        attachment_repository=attachment_repository,
        storage_service=get_storage_service(),
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
        sla_service=build_sla_service(db),
    )

    return await service.add_interaction_reply(
        interaction_id=interaction_id,
        request=request,
        current_user=current_user,
    )
