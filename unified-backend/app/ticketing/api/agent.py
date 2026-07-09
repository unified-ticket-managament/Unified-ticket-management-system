from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.agent import AgentSummaryResponse

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
    category: str | None = Query(
        default=None,
        description="Work-specialization category (e.g. 'AR') to scope results to — "
        "used by the ticket Assign-to-Staff picker so a Team Lead only sees their "
        "own category's Staff, not every Staff member company-wide.",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns active Staff users — used to populate agent pickers (e.g.
    Transfer/Assign-to-Staff) with real users, not dummy names.
    `category` set narrows to Staff in that one category; omitted
    returns every active Staff member (unfiltered).
    """

    repository = UserRepository(db)

    agents = (
        await repository.list_active_staff_by_category(category)
        if category is not None
        else await repository.list_active_by_role_name("Staff")
    )

    return [
        AgentSummaryResponse(
            user_id=agent.user_id,
            name=agent.name,
            email=agent.email,
        )
        for agent in agents
    ]