from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent, get_current_user
from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.user_repository import UserRepository
from app.schemas.agent import AgentSummaryResponse
from app.schemas.inbox import InboxResponse
from app.schemas.open_email import OpenEmailResponse
from app.services.inbox_service import InboxService
from app.services.open_email_service import OpenEmailService
from app.storage import get_storage_service

router = APIRouter(
    prefix="/agents",
    tags=["Agents"],
)


# ---------------------------------------------------------
# List Agents
# ---------------------------------------------------------

@router.get(
    "",
    response_model=list[AgentSummaryResponse],
)
async def list_agents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns every active Staff user — used to populate agent
    pickers (e.g. Transfer Agent) with real users, not dummy names.
    """

    repository = UserRepository(db)

    agents = await repository.list_active_by_role_name("Staff")

    return [
        AgentSummaryResponse(
            user_id=agent.user_id,
            name=agent.name,
            email=agent.email,
        )
        for agent in agents
    ]


# ---------------------------------------------------------
# Agent Inbox
# ---------------------------------------------------------

@router.get(
    "/me/inbox",
    response_model=InboxResponse,
)
async def get_agent_inbox(
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns all pending emails assigned to the authenticated agent.
    """

    repository = InteractionRepository(db)
    attachment_repository = AttachmentRepository(db)

    service = InboxService(repository, attachment_repository=attachment_repository)

    return await service.get_agent_inbox(current_user.name)


# ---------------------------------------------------------
# Open Email
# ---------------------------------------------------------

@router.get(
    "/me/inbox/{interaction_id}",
    response_model=OpenEmailResponse,
)
async def open_email(
    interaction_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns complete details of
    one email in the agent inbox.
    """

    repository = InteractionRepository(db)
    attachment_repository = AttachmentRepository(db)

    service = OpenEmailService(
        repository,
        attachment_repository=attachment_repository,
        storage_service=get_storage_service(),
    )

    return await service.get_email_details(
        interaction_id=interaction_id,
    )