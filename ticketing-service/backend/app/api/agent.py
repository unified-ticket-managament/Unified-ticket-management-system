from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.repositories.user_repository import UserRepository
from app.schemas.agent import AgentSummaryResponse

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