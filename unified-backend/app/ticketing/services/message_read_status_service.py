from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.message_read_receipt_repository import (
    MessageReadReceiptRepository,
)
from app.ticketing.schemas.inbox import ReadStatusResponse


class MessageReadStatusService:
    """
    Explicit read/unread toggling for a mail thread — the manual
    counterpart to OpenEmailService's own implicit mark-read-on-open
    (see that service's get_email_details for the automatic path).
    """

    def __init__(
        self,
        interaction_repository: InteractionRepository,
        read_receipt_repository: MessageReadReceiptRepository,
    ):
        self.interaction_repository = interaction_repository
        self.read_receipt_repository = read_receipt_repository

    async def _resolve_root_id(self, interaction_id: UUID) -> UUID:
        """
        Mirrors OpenEmailService.get_email_details's own root
        resolution — is_read is always keyed by the thread root, so a
        reply's own id must map onto the same row the list/detail
        views already read/write.
        """

        interaction = await self.interaction_repository.get_by_id(interaction_id)
        if interaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        if interaction.parent_interaction_id is not None:
            root = await self.interaction_repository.find_thread_root(interaction_id)
            if root is not None:
                return root.interaction_id

        return interaction.interaction_id

    async def mark_read(
        self, interaction_id: UUID, current_user: User
    ) -> ReadStatusResponse:
        root_id = await self._resolve_root_id(interaction_id)
        await self.read_receipt_repository.mark_read(current_user.user_id, root_id)
        return ReadStatusResponse(interaction_id=root_id, is_read=True)

    async def mark_unread(
        self, interaction_id: UUID, current_user: User
    ) -> ReadStatusResponse:
        root_id = await self._resolve_root_id(interaction_id)
        await self.read_receipt_repository.mark_unread(current_user.user_id, root_id)
        return ReadStatusResponse(interaction_id=root_id, is_read=False)
