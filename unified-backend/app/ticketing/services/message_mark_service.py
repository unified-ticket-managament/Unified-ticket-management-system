from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.message_mark_repository import MessageMarkRepository


class MessageMarkService:
    """
    Personal Flag / Pin on a mail thread. Like read/unread, a mark is
    always stored against the thread root and belongs to the caller
    alone. View access is enforced by the caller (BulkMailActionService
    runs `_ensure_can_view` first), so this owns no access rules.
    """

    def __init__(
        self,
        interaction_repository: InteractionRepository,
        mark_repository: MessageMarkRepository,
    ):
        self.interaction_repository = interaction_repository
        self.mark_repository = mark_repository

    async def _resolve_root_id(self, interaction_id: UUID) -> UUID:
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

    async def set_flag(self, interaction_id: UUID, flagged: bool, current_user: User) -> None:
        root_id = await self._resolve_root_id(interaction_id)
        await self.mark_repository.set_flag(current_user.user_id, root_id, flagged)

    async def set_pin(self, interaction_id: UUID, pinned: bool, current_user: User) -> None:
        root_id = await self._resolve_root_id(interaction_id)
        await self.mark_repository.set_pin(current_user.user_id, root_id, pinned)
