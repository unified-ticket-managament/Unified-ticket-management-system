from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.schemas.inbox import InboxResponse
from app.schemas.open_email import OpenEmailResponse
from app.services.inbox_service import InboxService
from app.services.open_email_service import OpenEmailService

router = APIRouter(
    prefix="/agents",
    tags=["Agents"],
)


# ---------------------------------------------------------
# Agent Inbox
# ---------------------------------------------------------

@router.get(
    "/{agent_name}/inbox",
    response_model=InboxResponse,
)
async def get_agent_inbox(
    agent_name: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns all pending emails
    assigned to the specified agent.
    """

    repository = InteractionRepository(db)

    service = InboxService(repository)

    return await service.get_agent_inbox(agent_name)


# ---------------------------------------------------------
# Open Email
# ---------------------------------------------------------

@router.get(
    "/{agent_name}/inbox/{interaction_id}",
    response_model=OpenEmailResponse,
)
async def open_email(
    agent_name: str,
    interaction_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns complete details of
    one email in the agent inbox.
    """

    repository = InteractionRepository(db)

    service = OpenEmailService(repository)

    return await service.get_email_details(
        interaction_id=interaction_id,
    )