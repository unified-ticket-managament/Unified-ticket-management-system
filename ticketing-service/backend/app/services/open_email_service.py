from uuid import UUID

from fastapi import HTTPException, status

from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.schemas.interaction import InteractionResponse
from app.schemas.open_email import OpenEmailResponse
from app.schemas.payloads import EmailPayload
from app.services.attachment_service import attachments_to_metadata
from app.storage.base import StorageService


def _reply_to_response(interaction) -> InteractionResponse:
    """
    Builds an InteractionResponse for a thread reply without
    touching `interaction.attachments` — that relationship is lazy
    and unloaded here, so letting pydantic's from_attributes
    machinery read it directly would trigger an unawaited lazy load
    (same reasoning as interaction_service.py's `_to_response`).
    """

    return InteractionResponse(
        interaction_id=interaction.interaction_id,
        ticket_id=interaction.ticket_id,
        interaction_type=interaction.interaction_type,
        status=interaction.status,
        direction=interaction.direction,
        performed_by=interaction.performed_by,
        payload=interaction.payload,
        is_visible=interaction.is_visible,
        removed_by=interaction.removed_by,
        removed_at=interaction.removed_at,
        message_id=interaction.message_id,
        client_id=interaction.client_id,
        parent_interaction_id=interaction.parent_interaction_id,
        received_at=interaction.received_at,
        created_at=interaction.created_at,
        attachments=[],
    )


class OpenEmailService:
    """
    Service responsible for returning the complete details of an
    inbox email — the root message plus its thread of replies.
    """

    def __init__(
        self,
        interaction_repository: InteractionRepository,
        attachment_repository: AttachmentRepository | None = None,
        storage_service: StorageService | None = None,
    ):
        self.interaction_repository = interaction_repository
        self.attachment_repository = attachment_repository
        self.storage_service = storage_service

    async def get_email_details(
        self,
        interaction_id: UUID,
    ) -> OpenEmailResponse:
        """
        Returns the complete email details for the specified
        interaction, including every reply already filed under it.
        """

        interaction = await self.interaction_repository.get_by_id(
            interaction_id
        )

        if interaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        payload = EmailPayload.model_validate(
            interaction.payload
        )

        attachments = []

        if self.attachment_repository is not None and self.storage_service is not None:
            raw_attachments = await self.attachment_repository.list_by_interaction_id(
                interaction_id
            )
            attachments = await attachments_to_metadata(raw_attachments, self.storage_service)

        replies = await self.interaction_repository.list_thread(interaction_id)

        return OpenEmailResponse(
            interaction_id=interaction.interaction_id,
            ticket_id=interaction.ticket_id,
            client_id=interaction.client_id,
            client_name=payload.client_name or "Unknown",
            to_email=payload.to_email,
            from_email=payload.from_email,
            from_name=payload.from_name,
            subject=payload.subject,
            body=payload.body,
            message_id=interaction.message_id,
            received_at=interaction.received_at or interaction.created_at,
            status=interaction.status,
            attachments=attachments,
            replies=[_reply_to_response(reply) for reply in replies],
        )
