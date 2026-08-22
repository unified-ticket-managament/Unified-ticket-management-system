# attachment_service.py

import asyncio
import base64
import logging
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from shared_models.models import User

from app.ticketing.enums import (
    ActorRole,
    AuditEntityType,
    AuditEventType,
    InteractionDirection,
    InteractionStatus,
)
from app.ticketing.models.attachment import Attachment
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.schemas.attachment import (
    AttachmentCreate,
    AttachmentMetadata,
    AttachmentUploadResponse,
    InlineImageUploadResponse,
)
from app.ticketing.schemas.email import LinkedAttachmentCandidate
from app.ticketing.schemas.interaction import InteractionCreate
from app.ticketing.schemas.payloads import EnvelopeAttachment
from app.ticketing.services.access_control import (
    SUPERVISOR_ROLE_NAMES,
    ensure_account_manager_owns_ticket_client,
    ensure_agent_can_act_on_ticket,
    ensure_agent_can_view_ticket,
    ensure_has_permission,
    ensure_ticket_not_closed,
)
from app.ticketing.services.audit_log_service import AuditLogService
from app.ticketing.storage.base import StorageService
from app.ticketing.utils.constants import MAX_ATTACHMENT_FILES, MAX_ATTACHMENT_SIZE_BYTES
from app.ticketing.utils.validators import (
    build_attachment_object_key,
    sanitize_filename,
    validate_attachment_type,
)

# Microsoft Graph's sendMail only accepts small attachments embedded
# directly in the message body (`contentBytes`) — anything larger
# needs a draft message plus a chunked upload session, which isn't
# implemented here. 3MB/file is comfortably under Graph's own ~4MB
# whole-message ceiling once the base64 inflation (~33%) and the rest
# of the message are accounted for.
GRAPH_INLINE_ATTACHMENT_MAX_BYTES = 3 * 1024 * 1024


async def attachment_to_metadata(
    attachment: Attachment,
    storage_service: StorageService,
) -> AttachmentMetadata:
    if attachment.is_external_link:
        # No real bytes, no storage_key — the "download" is just the
        # original OneDrive/SharePoint URL, opened in a new tab rather
        # than fetched through our own storage service.
        return AttachmentMetadata(
            id=attachment.attachment_id,
            filename=attachment.filename,
            mime_type=attachment.mime_type,
            size=attachment.size_bytes,
            download_url=attachment.external_url or "",
            preview_url=None,
            is_external_link=True,
            content_id=None,
            is_inline=False,
        )

    is_image = (attachment.mime_type or "").startswith("image/")

    download_url, preview_url = await asyncio.gather(
        storage_service.presigned_get_url(
            object_key=attachment.storage_key,
            filename=attachment.filename,
            inline=False,
        ),
        storage_service.presigned_get_url(
            object_key=attachment.storage_key,
            filename=attachment.filename,
            inline=True,
        )
        if is_image
        else _none(),
    )

    return AttachmentMetadata(
        id=attachment.attachment_id,
        filename=attachment.filename,
        mime_type=attachment.mime_type,
        size=attachment.size_bytes,
        download_url=download_url,
        preview_url=preview_url,
        is_external_link=False,
        content_id=attachment.content_id,
        is_inline=bool(attachment.is_inline),
    )


async def _none() -> None:
    return None


logger = logging.getLogger(__name__)


async def load_envelope_attachments(
    attachments: list[Attachment],
    storage_service: StorageService,
) -> list[EnvelopeAttachment]:
    """
    Reads each attachment's real bytes back out of storage and
    base64-encodes them, ready to embed directly in an outbound Graph
    sendMail call (see graph_client.py's _build_graph_attachments) —
    the one place these two things (a DB-tracked Attachment row and
    the file content Graph needs inline) actually meet.

    An attachment over GRAPH_INLINE_ATTACHMENT_MAX_BYTES, or one whose
    object read fails outright (e.g. deleted from the bucket), is
    skipped and logged rather than failing the whole send — a missing
    or oversized attachment shouldn't block an otherwise-good email
    from going out.
    """

    loaded: list[EnvelopeAttachment] = []

    for attachment in attachments:
        if attachment.is_external_link:
            # A cloud-link reference has no real bytes to embed in an
            # outbound Graph message — skip it rather than trying to
            # read a storage object that was never created.
            logger.info(
                "Skipping external-link attachment %s (%r) on outbound send — "
                "no real file content to embed.",
                attachment.attachment_id,
                attachment.filename,
            )
            continue

        if (attachment.size_bytes or 0) > GRAPH_INLINE_ATTACHMENT_MAX_BYTES:
            logger.warning(
                "Skipping attachment %s (%r, %d bytes) on outbound send — exceeds "
                "the %d byte inline-attachment limit; large-attachment upload "
                "sessions aren't implemented.",
                attachment.attachment_id,
                attachment.filename,
                attachment.size_bytes or 0,
                GRAPH_INLINE_ATTACHMENT_MAX_BYTES,
            )
            continue

        try:
            data = await storage_service.download(object_key=attachment.storage_key)
        except Exception:
            logger.exception(
                "Failed to read attachment %s (object_key=%s) for outbound send — "
                "sending without it.",
                attachment.attachment_id,
                attachment.storage_key,
            )
            continue

        loaded.append(
            EnvelopeAttachment(
                filename=attachment.filename,
                content_type=attachment.mime_type or "application/octet-stream",
                content_base64=base64.b64encode(data).decode("ascii"),
                content_id=attachment.content_id,
                # bool(...), not the raw attribute: an Attachment
                # constructed but not yet flushed has is_inline=None
                # (SQLAlchemy's mapped_column default=False is applied
                # at INSERT time, not at Python object construction) —
                # coerce so this never 500s on a not-yet-persisted row.
                is_inline=bool(attachment.is_inline),
            )
        )

    return loaded


async def attachments_to_metadata(
    attachments: list[Attachment],
    storage_service: StorageService,
) -> list[AttachmentMetadata]:
    """Signs every attachment's URLs concurrently — each is a real
    network call for backends like Supabase, so this avoids paying
    that latency once per file, serially.

    A single attachment whose object is missing/unsignable (e.g. it
    was deleted from the bucket, or its DB row outlived the upload)
    must not take down an entire timeline/inbox listing — it's
    dropped from the result and logged instead of raising.
    """
    results = await asyncio.gather(
        *(attachment_to_metadata(a, storage_service) for a in attachments),
        return_exceptions=True,
    )

    metadata: list[AttachmentMetadata] = []

    for attachment, result in zip(attachments, results):
        if isinstance(result, Exception):
            logger.warning(
                "Failed to sign URLs for attachment %s (object_key=%s): %s",
                attachment.attachment_id,
                attachment.storage_key,
                result,
            )
            continue
        metadata.append(result)

    return metadata


class AttachmentService:
    """
    Handles file uploads on a ticket and on incoming emails.

    Every uploaded file is recorded as an Interaction so it appears
    on the ticket timeline, and its file metadata is stored in its
    own Attachment row linked to that interaction. Validation and
    the actual object-storage write happen in one place —
    `validate_and_store_files` — so both upload paths (ticket
    upload, email intake) go through the same rules.
    """

    def __init__(
        self,
        attachment_repository: AttachmentRepository,
        interaction_repository: InteractionRepository,
        ticket_repository: TicketRepository,
        storage_service: StorageService,
        client_repository=None,
        escalation_repository=None,
        escalation_handling_sla_repository=None,
    ):
        self.attachment_repository = attachment_repository
        self.interaction_repository = interaction_repository
        self.ticket_repository = ticket_repository
        self.storage_service = storage_service
        self.client_repository = client_repository
        # Optional, same convention as InteractionService's own
        # escalation-aware call sites — threaded into
        # ensure_agent_can_act_on_ticket so upload_attachment is
        # frozen while a ticket's escalation is still awaiting
        # acceptance, same as reply/internal-note/status-change.
        # upload_attachment previously passed neither at all, so this
        # check never ran for it — a real, confirmed gap, not a
        # hypothetical one.
        self.escalation_repository = escalation_repository
        self.escalation_handling_sla_repository = escalation_handling_sla_repository

    # ---------------------------------------------------------
    # Shared validation + storage choke point
    # ---------------------------------------------------------

    async def validate_and_store_files(
        self,
        files: list[UploadFile],
        interaction_id: UUID,
    ) -> list[Attachment]:
        if len(files) > MAX_ATTACHMENT_FILES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A maximum of {MAX_ATTACHMENT_FILES} files can be uploaded at once.",
            )

        attachments: list[Attachment] = []

        for file in files:
            filename = sanitize_filename(file.filename or "file")

            try:
                validate_attachment_type(filename, file.content_type)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail=str(exc),
                )

            data = await file.read()

            if len(data) > MAX_ATTACHMENT_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f'"{filename}" exceeds the 25MB size limit.',
                )

            object_key = build_attachment_object_key(filename)

            await self.storage_service.upload(
                data=data,
                object_key=object_key,
                content_type=file.content_type or "application/octet-stream",
            )

            attachment = await self.attachment_repository.create(
                AttachmentCreate(
                    interaction_id=interaction_id,
                    filename=filename,
                    mime_type=file.content_type,
                    size_bytes=len(data),
                    storage_key=object_key,
                    bucket_name=self.storage_service.bucket,
                    # Present only on a _GraphAttachmentUploadFile
                    # carrying a real inline image (see
                    # mail_mapping_service.build_upload_files_from_
                    # graph_attachments) — absent on every plain
                    # fastapi.UploadFile (ticket upload, the N8N
                    # transport), which reproduces this call's exact
                    # pre-existing behavior unchanged.
                    content_id=getattr(file, "content_id", None),
                    is_inline=bool(getattr(file, "is_inline", False)),
                )
            )
            attachments.append(attachment)

        return attachments

    async def create_linked_attachments(
        self,
        interaction_id: UUID,
        candidates: list[LinkedAttachmentCandidate],
    ) -> list[Attachment]:
        """
        Records OneDrive/SharePoint "Attach as cloud link" references
        (extracted from an inbound email's HTML body — see
        mail_mapping_service.extract_cloud_link_attachments) as
        Attachment rows with no real storage_key/bytes, only
        external_url. Deliberately bypasses validate_and_store_files —
        there is nothing to type-check, size-check, or upload; only a
        filename+URL to persist.
        """

        attachments: list[Attachment] = []

        for candidate in candidates[:MAX_ATTACHMENT_FILES]:
            attachment = await self.attachment_repository.create(
                AttachmentCreate(
                    interaction_id=interaction_id,
                    filename=sanitize_filename(candidate.filename),
                    storage_key=None,
                    external_url=candidate.url,
                    is_external_link=True,
                )
            )
            attachments.append(attachment)

        return attachments

    async def create_inline_image(
        self,
        file: UploadFile,
        interaction_id: UUID,
    ) -> Attachment:
        """
        Stores a single pasted-into-the-body screenshot/image as an
        inline attachment: same validation/storage choke point as
        validate_and_store_files (type/size checks, storage_service.
        upload), but additionally mints a content_id and sets
        is_inline=True so the composer can reference it as
        `cid:{content_id}` inside the HTML body it will submit, and so
        this row is never surfaced as a downloadable attachment
        alongside the message the way a real file attachment is.

        Deliberately a single-file method, not a list — a paste event
        inserts exactly one image at a time, unlike the batch ticket/
        draft upload endpoints. Deliberately not folded into
        validate_and_store_files — not every uploaded image is a body
        image (a user can still attach an ordinary photo as a real,
        downloadable file), so "is this inline" must be an explicit,
        separate signal from the caller, not inferred from mime_type.
        """

        filename = sanitize_filename(file.filename or "image")

        try:
            validate_attachment_type(filename, file.content_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=str(exc),
            )

        if not (file.content_type or "").startswith("image/"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Only image files can be uploaded as an inline body image.",
            )

        data = await file.read()

        if len(data) > GRAPH_INLINE_ATTACHMENT_MAX_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f'"{filename}" exceeds the '
                    f"{GRAPH_INLINE_ATTACHMENT_MAX_BYTES // (1024 * 1024)}MB "
                    "inline-image limit."
                ),
            )

        object_key = build_attachment_object_key(filename)

        await self.storage_service.upload(
            data=data,
            object_key=object_key,
            content_type=file.content_type or "application/octet-stream",
        )

        return await self.attachment_repository.create(
            AttachmentCreate(
                interaction_id=interaction_id,
                filename=filename,
                mime_type=file.content_type,
                size_bytes=len(data),
                storage_key=object_key,
                bucket_name=self.storage_service.bucket,
                content_id=uuid4().hex,
                is_inline=True,
            )
        )

    # ---------------------------------------------------------
    # Ticket Attachment Upload
    # ---------------------------------------------------------

    async def upload_attachment(
        self,
        ticket_id: UUID,
        files: list[UploadFile],
        current_user: User,
    ) -> AttachmentUploadResponse:

        ticket = await self.ticket_repository.get_by_id(ticket_id)

        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )

        if not files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one file is required.",
            )

        ensure_ticket_not_closed(ticket)
        # This was previously called without `await` — since
        # ensure_agent_can_act_on_ticket is async, that silently created
        # a coroutine object and never ran it, meaning this check never
        # actually executed and any authenticated agent could upload to
        # any ticket regardless of category/ownership. Fixed here.
        await ensure_agent_can_act_on_ticket(
            ticket,
            current_user,
            escalation_repository=self.escalation_repository,
            escalation_handling_sla_repository=self.escalation_handling_sla_repository,
        )
        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )
        ensure_has_permission(current_user, "ticket:upload_attachment")

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        interaction = await self.interaction_repository.create(
            InteractionCreate(
                ticket_id=ticket_id,
                interaction_type="ATTACHMENT",
                direction=InteractionDirection.INTERNAL,
                status=InteractionStatus.ASSIGNED,
                performed_by=actor_id,
                payload={"file_count": len(files)},
                is_visible=True,
                message_id=None,
            )
        )

        attachments = await self.validate_and_store_files(
            files, interaction.interaction_id
        )

        # One audit row per file — metadata only, never the file
        # content itself.
        for attachment in attachments:
            await AuditLogService.log_event(
                self.attachment_repository.db,
                entity_type=AuditEntityType.ATTACHMENT,
                entity_id=attachment.attachment_id,
                event_type=AuditEventType.ATTACHMENT_UPLOADED,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_role=actor_role,
                new_values={
                    "filename": attachment.filename,
                    "mime_type": attachment.mime_type,
                    "size_bytes": attachment.size_bytes,
                    "interaction_id": attachment.interaction_id,
                    "ticket_id": ticket_id,
                },
            )

        return AttachmentUploadResponse(
            interaction_id=interaction.interaction_id,
            ticket_id=ticket_id,
            attachments=await attachments_to_metadata(attachments, self.storage_service),
            message="Attachment(s) uploaded successfully.",
        )

    async def upload_inline_image(
        self,
        ticket_id: UUID,
        file: UploadFile,
        current_user: User,
    ) -> InlineImageUploadResponse:
        """
        Orchestrates the ticket-scoped inline-image (pasted
        screenshot) upload: same auth chain as upload_attachment
        (ticket-not-closed, can-act-on-ticket, AM-owns-client,
        ticket:upload_attachment) — pasting an image into a reply/note
        body is the same capability as attaching a file, just a
        different resulting shape — then records it under a fresh
        ATTACHMENT interaction (mirroring upload_attachment's own
        per-call interaction, since a ticket reply/note composer has
        no pre-existing draft interaction to attach to the way Mail's
        pre-ticket draft flow does).
        """

        ticket = await self.ticket_repository.get_by_id(ticket_id)

        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )

        ensure_ticket_not_closed(ticket)
        await ensure_agent_can_act_on_ticket(
            ticket,
            current_user,
            escalation_repository=self.escalation_repository,
            escalation_handling_sla_repository=self.escalation_handling_sla_repository,
        )
        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )
        ensure_has_permission(current_user, "ticket:upload_attachment")

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        interaction = await self.interaction_repository.create(
            InteractionCreate(
                ticket_id=ticket_id,
                interaction_type="ATTACHMENT",
                direction=InteractionDirection.INTERNAL,
                status=InteractionStatus.ASSIGNED,
                performed_by=actor_id,
                payload={"file_count": 1, "is_inline": True},
                is_visible=True,
                message_id=None,
            )
        )

        attachment = await self.create_inline_image(file, interaction.interaction_id)

        await AuditLogService.log_event(
            self.attachment_repository.db,
            entity_type=AuditEntityType.ATTACHMENT,
            entity_id=attachment.attachment_id,
            event_type=AuditEventType.ATTACHMENT_UPLOADED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={
                "filename": attachment.filename,
                "mime_type": attachment.mime_type,
                "size_bytes": attachment.size_bytes,
                "interaction_id": attachment.interaction_id,
                "ticket_id": ticket_id,
                "is_inline": True,
            },
        )

        is_image = (attachment.mime_type or "").startswith("image/")
        preview_url = (
            await self.storage_service.presigned_get_url(
                object_key=attachment.storage_key,
                filename=attachment.filename,
                inline=True,
            )
            if is_image
            else None
        )

        return InlineImageUploadResponse(
            id=attachment.attachment_id,
            content_id=attachment.content_id,
            filename=attachment.filename,
            mime_type=attachment.mime_type,
            size=attachment.size_bytes,
            preview_url=preview_url,
            interaction_id=interaction.interaction_id,
        )

    # ---------------------------------------------------------
    # Single Attachment — Get / Delete
    # ---------------------------------------------------------

    async def _resolve_and_authorize(
        self,
        attachment_id: UUID,
        current_user: User,
    ) -> Attachment:
        attachment = await self.attachment_repository.get_by_id(attachment_id)

        if attachment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attachment not found.",
            )

        interaction = await self.interaction_repository.get_by_id(
            attachment.interaction_id
        )

        if interaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attachment not found.",
            )

        if interaction.ticket_id is not None:
            ticket = await self.ticket_repository.get_by_id(interaction.ticket_id)
            if ticket is not None:
                ensure_agent_can_view_ticket(ticket, current_user)
                await ensure_account_manager_owns_ticket_client(
                    ticket, current_user, self.client_repository
                )
        elif current_user.role.name not in SUPERVISOR_ROLE_NAMES:
            # Not yet attached to a ticket — falls back to the
            # inbox's own scoping (the agent it was assigned to).
            payload_agent = interaction.payload.get("agent_name")
            if payload_agent is not None and payload_agent != current_user.name:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have access to this attachment.",
                )

        return attachment

    async def get_attachment(
        self,
        attachment_id: UUID,
        current_user: User,
    ) -> AttachmentMetadata:
        attachment = await self._resolve_and_authorize(attachment_id, current_user)
        return await attachment_to_metadata(attachment, self.storage_service)

    async def get_download_url(
        self,
        attachment_id: UUID,
        current_user: User,
    ) -> str:
        attachment = await self._resolve_and_authorize(attachment_id, current_user)
        if attachment.is_external_link:
            return attachment.external_url or ""
        return await self.storage_service.presigned_get_url(
            object_key=attachment.storage_key,
            filename=attachment.filename,
            inline=False,
        )

    async def delete_attachment(
        self,
        attachment_id: UUID,
        current_user: User,
    ) -> None:
        attachment = await self._resolve_and_authorize(attachment_id, current_user)
        # Removing an attachment (as opposed to viewing/downloading one,
        # which _resolve_and_authorize alone already gates) is the
        # ticket:archive_attachment permission — Full for Super Admin/
        # Site Lead/Account Manager (own clients, checked above), a
        # personal override for everyone else.
        ensure_has_permission(current_user, "ticket:archive_attachment")
        # An external-link attachment has no object in our own storage
        # to delete — only the DB row itself.
        if not attachment.is_external_link:
            await self.storage_service.delete(object_key=attachment.storage_key)
        await self.attachment_repository.delete(attachment)
