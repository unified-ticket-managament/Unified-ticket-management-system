# attachment_service.py

import asyncio
import logging
from uuid import UUID

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
)
from app.ticketing.schemas.interaction import InteractionCreate
from app.ticketing.services.access_control import (
    SUPERVISOR_ROLE_NAMES,
    ensure_agent_can_act_on_ticket,
    ensure_agent_can_view_ticket,
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


async def attachment_to_metadata(
    attachment: Attachment,
    storage_service: StorageService,
) -> AttachmentMetadata:
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
    )


async def _none() -> None:
    return None


logger = logging.getLogger(__name__)


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
    ):
        self.attachment_repository = attachment_repository
        self.interaction_repository = interaction_repository
        self.ticket_repository = ticket_repository
        self.storage_service = storage_service

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
                )
            )
            attachments.append(attachment)

        return attachments

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
        ensure_agent_can_act_on_ticket(ticket, current_user)

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
        await self.storage_service.delete(object_key=attachment.storage_key)
        await self.attachment_repository.delete(attachment)
