from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.ticket_repository import (
    TicketRepository,
)
from app.repositories.user_repository import UserRepository
from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.client_repository import ClientRepository
from app.schemas.interaction import (
    HideInteractionRequest,
    HideInteractionResponse,
    ThreadResponse,
)
from app.services.interaction_service import InteractionService

router = APIRouter(
    prefix="/interactions",
    tags=["Interactions"],
)


# =========================================================
# Thread Fetch — Outlook-style "open the conversation"
# =========================================================

@router.get(
    "/{interaction_id}/thread",
    response_model=ThreadResponse,
)
async def get_thread(
    interaction_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the full conversation for any id within it — the root
    itself, or any reply/follow-up filed under it. Resolves up to the
    thread root first, so opening a reply's own id still returns the
    complete thread, not just that one message.
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
    )

    return await service.get_thread(
        interaction_id=interaction_id,
        current_user=current_user,
    )


# =========================================================
# Hide / Soft-Delete Interaction (ticket-agnostic)
# =========================================================

@router.post(
    "/{interaction_id}/hide",
    response_model=HideInteractionResponse,
    status_code=status.HTTP_200_OK,
)
async def hide_interaction(
    interaction_id: UUID,
    request: HideInteractionRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Soft-deletes any interaction by ID alone — including
    emails still sitting in an inbox that haven't been turned
    into a ticket yet. The row is never physically deleted; it
    is marked not visible so the audit trail stays intact.

    For an interaction already on a ticket, prefer
    POST /tickets/{ticket_id}/interactions/{interaction_id}/hide
    if you already have the ticket_id on hand — both call the
    same underlying logic.
    """

    interaction_repository = InteractionRepository(db)

    interaction = await interaction_repository.get_by_id(interaction_id)

    if interaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interaction not found.",
        )

    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
    )

    return await service.hide_interaction(
        ticket_id=interaction.ticket_id,
        interaction_id=interaction_id,
        request=request,
        current_user=current_user,
    )
