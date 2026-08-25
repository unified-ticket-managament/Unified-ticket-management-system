from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.ticketing.enums import TicketPriority
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.distribution_list_repository import (
    DistributionListRepository,
)
from app.ticketing.schemas.attachment import AttachmentMetadata, InlineImageUploadResponse
from app.ticketing.repositories.interaction_repository import (
    InteractionRepository,
)
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.message_read_receipt_repository import (
    MessageReadReceiptRepository,
)
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.compose import ComposeEmailRequest, ComposeEmailResponse
from app.ticketing.schemas.forward import (
    ForwardToInternalUserRequest,
    ForwardToInternalUserResponse,
)
from app.ticketing.schemas.inbox import (
    DraftListResponse,
    InboxResponse,
    ReadStatusResponse,
    SentResponse,
)
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
from app.ticketing.utils.recipient_validation import ensure_recipients_are_valid
from app.ticketing.services.inbox_service import InboxService
from app.ticketing.services.mail_folder_service import MailFolderService
from app.ticketing.services.rule_access import folder_name_to_rules, has_folder_share_access
from app.ticketing.services.message_read_status_service import (
    MessageReadStatusService,
)
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


def _split_uuids(raw: str | None) -> list[UUID]:
    """
    Same comma-separated-Form-field convention as _split_emails above,
    for a Compose/Forward request's inline_image_interaction_ids — the
    staging interaction ids minted by POST /inbox/compose/attachments/
    inline-image (see InteractionService.upload_compose_inline_image).
    """

    if not raw:
        return []
    try:
        return [UUID(value.strip()) for value in raw.split(",") if value.strip()]
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="inline_image_interaction_ids must be a comma-separated list of UUIDs.",
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
    view: str = Query(default="pending", pattern="^(pending|replied|ticketed|archived|all)$"),
    scope: str = Query(default="mine", pattern="^(mine|all)$"),
    search: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None),
    category: str | None = Query(default=None),
    priority: TicketPriority | None = Query(default=None),
    assigned_to_me: bool = Query(default=False),
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

    `assigned_to_me=true` additionally narrows to threads whose ticket
    is assigned to the caller — composes with (never replaces) the
    caller's own role-based scope, e.g. an Account Manager gets "my
    owned clients' tickets assigned to me," not company-wide. Backs the
    Mail page's "My Claims" ticketed section (see InboxService.
    _resolve_scope) — has no effect for Staff, whose scope already
    always means "assigned to me."

    `limit`/`offset`/`search` are all optional and additive — omitting
    `limit` returns the exact same unbounded response this endpoint
    always returned. `total` in the response always reflects the full
    filtered count, whether or not `limit` was passed. `cursor` (from
    a previous response's `next_cursor`) is an additive keyset-paging
    alternative to `offset` for deep paging at scale — pass either,
    not both; `cursor` wins if both are given.

    `category`/`priority` filter to threads whose ticket matches (both
    only ever apply to already-ticketed threads) — moves what used to
    be a client-side-only filter over whatever page was already loaded
    into the query itself, so it searches the full filtered set.
    """

    bypass_ownership_scope = False
    if folder_id is not None:
        # A folder now has the same ownership/sharing-driven visibility
        # as the rules that file mail into it (see MailFolderService) —
        # a guessed/leaked private folder_id must not be usable to
        # filter the inbox by it. Missing and not-visible are treated
        # identically (404) so existence isn't leaked either.
        #
        # `via_sharing` additionally decides whether the viewer's own
        # role-based ownership scope (Account Manager's owned clients,
        # Team Lead's category, Staff's assigned tickets) is bypassed
        # for THIS folder_id only — a folder genuinely shared with this
        # viewer (via a rule's shared_user_ids) must actually show what
        # was filed into it, not just appear to exist while showing
        # nothing (see InboxService._resolve_scope's own docstring).
        # Never widens the viewer's own unscoped Inbox, and never
        # bypasses anything for a folder they merely created themselves
        # with no rule sharing it — resolve_folder_access already
        # distinguishes those cases.
        folder_repository = MailFolderRepository(db)
        folder = await folder_repository.get_by_id(folder_id)
        if folder is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Folder not found.",
            )
        access = await MailFolderService(folder_repository).resolve_folder_access(
            folder, current_user, RuleRepository(db), DistributionListRepository(db)
        )
        if not access.visible:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Folder not found.",
            )
        bypass_ownership_scope = access.via_sharing

    repository = InteractionRepository(db)
    attachment_repository = AttachmentRepository(db)
    user_repository = UserRepository(db)
    ticket_repository = TicketRepository(db)
    read_receipt_repository = MessageReadReceiptRepository(db)

    service = InboxService(
        repository,
        attachment_repository=attachment_repository,
        user_repository=user_repository,
        ticket_repository=ticket_repository,
        read_receipt_repository=read_receipt_repository,
        sla_service=build_sla_service(db),
    )

    return await service.get_inbox(
        current_user,
        client_id=client_id,
        view=view,
        scope=scope,
        folder_id=folder_id,
        search=search,
        limit=limit,
        offset=offset,
        cursor=cursor,
        category_filter=category,
        priority_filter=priority,
        assigned_to_me=assigned_to_me,
        bypass_ownership_scope=bypass_ownership_scope,
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

    Folders the viewer has genuine sharing access to (a rule filing
    into them names the viewer in shared_user_ids — see
    rule_access.has_folder_share_access) are counted with the same
    ownership bypass GET /inbox applies for a single shared folder_id
    — otherwise a shared folder would show a real folder in the
    sidebar (GET /folders already grants that) but a misleading 0
    count here, the exact bug this whole fix addresses.
    """

    folder_repository = MailFolderRepository(db)
    rule_repository = RuleRepository(db)
    distribution_list_repository = DistributionListRepository(db)

    all_folders = await folder_repository.list_all()
    all_rules = await rule_repository.list_all()
    name_to_rules = folder_name_to_rules(all_rules)
    user_dl_ids = await distribution_list_repository.list_active_list_ids_for_user(
        current_user.user_id
    )
    shared_folder_ids = {
        folder.folder_id
        for folder in all_folders
        if has_folder_share_access(folder.name, current_user, name_to_rules, user_dl_ids)
    }

    repository = InteractionRepository(db)

    service = InboxService(repository)

    return await service.get_folder_counts(
        current_user, client_id=client_id, shared_folder_ids=shared_folder_ids
    )


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

    service = InboxService(repository)

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
    """Every brand-new Compose email the current user has sent — see /replied for replies."""

    repository = InteractionRepository(db)

    service = InboxService(repository)

    return await service.get_sent(current_user)


@router.get(
    "/replied",
    response_model=SentResponse,
)
async def get_replied(
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Every reply the current user has sent, pre-ticket or ticket-level alike."""

    repository = InteractionRepository(db)

    service = InboxService(repository)

    return await service.get_replied(current_user)


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
    client_id: UUID | None = Form(default=None),
    category_id: UUID | None = Form(default=None),
    to_email: str = Form(default=""),
    distribution_list_ids: list[UUID] = Form(default=[]),
    subject: str = Form(...),
    message: str = Form(...),
    cc: str = Form(default=""),
    bcc: str = Form(default=""),
    body_html: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    inline_image_interaction_ids: str = Form(default=""),
    idempotency_key: str | None = Form(default=None),
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

    `to_email` is now optional — the primary recipient can come
    entirely from `distribution_list_ids` (resolved server-side to
    real "To" recipients, merged into one send via the same additive
    OutboundEnvelope.to_emails mechanism Forward uses); at least one
    of the two must resolve to a real address or the service 400s.

    `inline_image_interaction_ids` carries the staging interaction
    ids minted by POST /inbox/compose/attachments/inline-image for
    any screenshot pasted into the body before Send — see
    InteractionService.upload_compose_inline_image.
    """

    # Validated before ComposeEmailRequest is ever constructed — that
    # constructor's fields are EmailStr-typed, so a malformed address
    # reaching it directly would raise an unhandled pydantic.
    # ValidationError (no handler registered for it — see app/main.py)
    # rather than a clean 400. See recipient_validation.py's own
    # module docstring for the full syntax+domain rationale.
    parsed_to_email = to_email.strip() or None
    parsed_cc = _split_emails(cc)
    parsed_bcc = _split_emails(bcc)
    await ensure_recipients_are_valid(to=parsed_to_email, cc=parsed_cc, bcc=parsed_bcc)

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
        attachment_repository=attachment_repository,
        storage_service=storage_service,
        distribution_list_repository=DistributionListRepository(db),
    )

    composed = await interaction_service.compose_email(
        request=ComposeEmailRequest(
            client_id=client_id,
            category_id=category_id,
            to_email=parsed_to_email,
            distribution_list_ids=distribution_list_ids,
            subject=subject,
            message=message,
            cc=parsed_cc,
            bcc=parsed_bcc,
            body_html=body_html,
            idempotency_key=idempotency_key,
        ),
        current_user=current_user,
        files=files,
        inline_image_interaction_ids=_split_uuids(inline_image_interaction_ids),
    )

    if files or inline_image_interaction_ids:
        # compose_email already stored/reassigned these (before
        # dispatch, so they actually ride along on the real outbound
        # email — see InteractionService._attach_outbound_files/
        # _merge_inline_images_into_envelope) — just re-fetch for the
        # response's attachment metadata.
        stored = await attachment_repository.list_by_interaction_id(
            composed.interaction_id
        )
        composed.attachments = await attachments_to_metadata(stored, storage_service)

    return composed


# ---------------------------------------------------------
# Compose/Forward inline image staging — no interaction exists yet
# ---------------------------------------------------------
#
# Registered before "/{interaction_id}" for the same reason /compose
# itself is above.

@router.post(
    "/compose/attachments/inline-image",
    response_model=InlineImageUploadResponse,
    status_code=201,
)
async def upload_compose_inline_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Uploads a single pasted-into-the-body screenshot for a Compose or
    Forward message that hasn't been sent yet — neither has a pre-
    existing interaction to stage against the way a ticket reply/note
    or a pre-ticket draft reply does (see InteractionService.
    upload_compose_inline_image). The returned interaction_id is sent
    back as one of compose_email's/forward_to_internal_user's
    inline_image_interaction_ids at Send time.
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

    return await service.upload_compose_inline_image(
        file=file,
        current_user=current_user,
    )


# ---------------------------------------------------------
# Forward — an existing client email, to an internal org user
# ---------------------------------------------------------


@router.post(
    "/{interaction_id}/forward",
    response_model=ForwardToInternalUserResponse,
    status_code=201,
)
async def forward_to_internal_user(
    interaction_id: UUID,
    client_id: UUID | None = Form(default=None),
    category_id: UUID | None = Form(default=None),
    recipient_user_ids: list[UUID] = Form(default=[]),
    recipient_emails: list[str] = Form(default=[]),
    distribution_list_ids: list[UUID] = Form(default=[]),
    cc: str = Form(default=""),
    bcc: str = Form(default=""),
    subject: str = Form(...),
    message: str = Form(...),
    body_html: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    inline_image_interaction_ids: str = Form(default=""),
    idempotency_key: str | None = Form(default=None),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Forwards an existing client email/interaction to a mix of internal
    organization users, external addresses, and/or Distribution
    Lists — see InteractionService.forward_to_internal_user for the
    full authorization/delivery mechanics. Multipart (like /compose),
    not a plain JSON body: original attachments already stored against
    `interaction_id` are always carried over, and any newly uploaded
    `files` ride along too, subject to the combined 10-attachment
    total enforced in the service layer.

    `recipient_user_ids`/`recipient_emails`/`distribution_list_ids` are
    each a repeated Form field (the frontend appends the same key once
    per value) — FastAPI/Starlette binds repeated same-key multipart
    fields to a `list[...]` parameter natively.

    `body_html` — the frontend has sent this field for a while (see
    api/inbox.ts's ForwardToInternalUserPayload), and
    ForwardToInternalUserRequest already declares it, but this route
    never actually accepted/parsed it as a Form field until now — a
    real, previously-silent gap: any HTML the composer sent was
    dropped before ever reaching the service, regardless of what the
    editor produced.

    `inline_image_interaction_ids` — see compose_email's identical
    param above; the same POST /inbox/compose/attachments/inline-image
    staging endpoint is reused for Forward's own paste-a-screenshot
    case, since neither Compose nor Forward has a pre-existing
    interaction to stage against before Send.
    """

    # See compose_email's identical call above — validated before
    # ForwardToInternalUserRequest (EmailStr-typed) is constructed, so
    # a malformed recipient_emails/cc/bcc entry 400s cleanly instead of
    # raising an unhandled pydantic.ValidationError. recipient_user_ids
    # (the internal-recipient branch) are real, already-stored platform
    # users' own emails — not new user input — so they're never
    # re-validated here; distribution_list_ids resolve to internal
    # users too and are validated the same way, inside the service.
    parsed_cc = _split_emails(cc)
    parsed_bcc = _split_emails(bcc)
    await ensure_recipients_are_valid(to=recipient_emails, cc=parsed_cc, bcc=parsed_bcc)

    request = ForwardToInternalUserRequest(
        client_id=client_id,
        category_id=category_id,
        recipient_user_ids=recipient_user_ids,
        recipient_emails=recipient_emails,
        distribution_list_ids=distribution_list_ids,
        cc=parsed_cc,
        bcc=parsed_bcc,
        subject=subject,
        message=message,
        body_html=body_html,
        idempotency_key=idempotency_key,
    )

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    attachment_repository = AttachmentRepository(db)
    storage_service = get_storage_service()
    notification_service = NotificationService(NotificationRepository(db))

    interaction_service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
        attachment_repository=attachment_repository,
        storage_service=storage_service,
        notification_service=notification_service,
        distribution_list_repository=DistributionListRepository(db),
    )

    return await interaction_service.forward_to_internal_user(
        interaction_id=interaction_id,
        request=request,
        current_user=current_user,
        files=files,
        inline_image_interaction_ids=_split_uuids(inline_image_interaction_ids),
    )


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
# Read / Unread (explicit manual toggle)
# ---------------------------------------------------------
#
# The automatic "opened = read" marking already happens as a side
# effect of GET /inbox/{interaction_id} (see OpenEmailService). These
# two routes are the explicit counterpart — mark_unread has no other
# caller anywhere in the app, since opening a thread only ever marks
# it read, never unread.

@router.post(
    "/{interaction_id}/read",
    response_model=ReadStatusResponse,
    status_code=200,
)
async def mark_inbox_read(
    interaction_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Explicitly marks a mail thread read — the manual "Mark as Read" control."""

    service = MessageReadStatusService(
        InteractionRepository(db), MessageReadReceiptRepository(db)
    )

    return await service.mark_read(interaction_id, current_user)


@router.post(
    "/{interaction_id}/unread",
    response_model=ReadStatusResponse,
    status_code=200,
)
async def mark_inbox_unread(
    interaction_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Explicitly marks a mail thread unread — the manual "Mark as Unread" control."""

    service = MessageReadStatusService(
        InteractionRepository(db), MessageReadReceiptRepository(db)
    )

    return await service.mark_unread(interaction_id, current_user)


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
        sla_service=build_sla_service(
            db, notification_service=NotificationService(NotificationRepository(db))
        ),
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
    "/{interaction_id}/draft/attachments/inline-image",
    response_model=InlineImageUploadResponse,
    status_code=201,
)
async def upload_draft_inline_image(
    interaction_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Uploads a single pasted-into-the-body screenshot to the current
    user's in-progress draft on this thread — the pre-ticket
    counterpart of POST /tickets/{id}/attachments/inline-image, same
    "always keyed on interaction_id, never ticket_id" rule every other
    draft-attachment route already follows.
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

    return await service.upload_draft_inline_image(
        interaction_id=interaction_id,
        file=file,
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
        distribution_list_repository=DistributionListRepository(db),
    )

    return await service.send_draft(
        interaction_id=interaction_id,
        current_user=current_user,
        to_email=body.to_email if body else None,
        to_emails=body.to_emails if body else None,
        distribution_list_ids=body.distribution_list_ids if body else [],
        idempotency_key=body.idempotency_key if body else None,
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
    mark_read: bool = True,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the complete details of one inbox email, plus every
    reply already filed under it.

    `mark_read` defaults to True (a genuine "open this thread" call
    marks it read, as always) — callers re-fetching an already-open
    thread's details (a manual refresh, or a post-send re-fetch) pass
    `mark_read=false` so that doesn't silently undo an explicit
    "Mark as Unread".
    """

    repository = InteractionRepository(db)
    attachment_repository = AttachmentRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    ticket_repository = TicketRepository(db)
    read_receipt_repository = MessageReadReceiptRepository(db)

    service = OpenEmailService(
        repository,
        attachment_repository=attachment_repository,
        storage_service=get_storage_service(),
        user_repository=user_repository,
        client_repository=client_repository,
        ticket_repository=ticket_repository,
        read_receipt_repository=read_receipt_repository,
        sla_service=build_sla_service(db),
    )

    return await service.get_email_details(
        interaction_id=interaction_id,
        current_user=current_user,
        mark_read=mark_read,
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
        sla_service=build_sla_service(
            db, notification_service=NotificationService(NotificationRepository(db))
        ),
        distribution_list_repository=DistributionListRepository(db),
    )

    return await service.add_interaction_reply(
        interaction_id=interaction_id,
        request=request,
        current_user=current_user,
    )
