# agent_assignment_service.py

from shared_models.models import User

from app.repositories.interaction_repository import InteractionRepository
from app.repositories.ticket_repository import TicketRepository
from app.repositories.user_repository import UserRepository

STAFF_ROLE_NAME = "Staff"


class AgentAssignmentService:
    """
    Decides which agent (Staff user) a new inbound email is
    routed to.

    The team's real routing rule (skill-based routing, SLA/score
    based queueing, manual manager reassignment, etc. — see the
    workflow diagrams) has not been finalised yet. Until it is,
    this picks the active Staff member with the fewest current
    items on their plate — open tickets plus still-pending
    (not yet ticketed) inbox emails — so routing stays fair
    across bursts of new emails instead of piling onto whichever
    agent happens to sort first when everyone is tied at zero.

    Swap the body of `select_agent` when the real rule is ready —
    every caller only depends on this one method.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        ticket_repository: TicketRepository,
        interaction_repository: InteractionRepository,
    ):
        self.user_repository = user_repository
        self.ticket_repository = ticket_repository
        self.interaction_repository = interaction_repository

    async def select_agent(self) -> User | None:
        agents = await self.user_repository.list_active_by_role_name(
            STAFF_ROLE_NAME
        )

        if not agents:
            return None

        if len(agents) == 1:
            return agents[0]

        agent_ids = [agent.user_id for agent in agents]

        ticket_workloads = await self.ticket_repository.count_open_tickets_by_agent(
            agent_ids
        )
        pending_workloads = await self.interaction_repository.count_pending_by_agent(
            agent_ids
        )

        def workload(agent: User) -> int:
            return ticket_workloads.get(agent.user_id, 0) + pending_workloads.get(
                agent.user_id, 0
            )

        return min(agents, key=workload)
