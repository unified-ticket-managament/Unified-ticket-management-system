from uuid import UUID

from fastapi import HTTPException, status

from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.schemas.open_email import OpenEmailResponse
from app.schemas.payloads import EmailPayload
from app.services.attachment_service import attachments_to_metadata
from app.storage.base import StorageService


class OpenEmailService:
    """
    Service responsible for returning the
    complete details of an inbox email.
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
        Returns the complete email details
        for the specified interaction.
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

        return OpenEmailResponse(
            interaction_id=interaction.interaction_id,
            client_name=payload.client_name,
            agent_name=payload.agent_name,
            from_email=payload.from_email,
            subject=payload.subject,
            body=payload.body,
            message_id=interaction.message_id,
            received_at=interaction.created_at,
            status=interaction.status,
            attachments=attachments,
        )