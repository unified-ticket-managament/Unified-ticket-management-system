from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent, get_current_user
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.agent import AgentSummaryResponse
from app.ticketing.schemas.assignment import AssignableAgentsResponse
from app.ticketing.services.assignment_service import AssignmentService

router = APIRouter(
    prefix="/agents",
    tags=["Agents"],
)


# ---------------------------------------------------------
# Assignable "Assigned To" targets (Create Ticket dialog)
# ---------------------------------------------------------

# Registered before the plain "" list route below only for readability
# (no path-param collision risk here, unlike /inbox's static-before-
# {interaction_id} ordering — "/assignable" and "" can't shadow each
# other either way).
@router.get(
    "/assignable",
    response_model=AssignableAgentsResponse,
)
async def get_assignable_agents(
    category: str | None = Query(
        None,
        description=(
            "The new ticket's own category (e.g. 'Eligibility') — "
            "narrows the Team Lead/Staff groups to that one "
            "work-specialization team instead of showing every "
            "category's staff at once. Omit for the old, unscoped list."
        ),
    ),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns who the current user may assign a brand-new ticket to when
    promoting an inbox email — themselves, plus whichever role-grouped
    hierarchy they supervise (see AssignmentService for the exact
    rules per role).
    """

    repository = UserRepository(db)
    service = AssignmentService(repository)

    return await service.get_assignable_groups(current_user, category)


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