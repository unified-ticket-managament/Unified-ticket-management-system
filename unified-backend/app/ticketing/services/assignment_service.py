from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.assignment import (
    AssignableAgentsResponse,
    AssignableGroup,
    AssignableUserSummary,
)

ACCOUNT_MANAGER_ROLE_NAME = "Account Manager"
TEAM_LEAD_ROLE_NAME = "Team Lead"
STAFF_ROLE_NAME = "Staff"
SITE_LEAD_ROLE_NAME = "Site Lead"
SUPER_ADMIN_ROLE_NAME = "Super Admin"


def _summary(user: User) -> AssignableUserSummary:
    return AssignableUserSummary(user_id=user.user_id, name=user.name)


class AssignmentService:
    """
    Resolves who the current user is allowed to assign a new ticket to
    when promoting an inbox email — the Create Ticket dialog's
    "Assigned To" field. Read-only picker data lives here
    (`get_assignable_groups`); `resolve_target` is the write-path
    guard InboxTicketService calls so a crafted `agent_id` can never
    assign outside the actor's own hierarchy.

    Role rules:
    - Account Manager: their own reporting Team Leads and Staff
      (`manager_id` match), plus themselves.
    - Team Lead: their own reporting Staff (`teamlead_id` match), plus
      themselves.
    - Site Lead: every active Account Manager / Team Lead / Staff,
      unrestricted (Site Lead has unconditional visibility elsewhere
      in this codebase too).
    - Super Admin: every active user of every role.
    - Staff (or anything else): no groups — always themselves only.
    """

    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    async def get_assignable_groups(self, current_user: User) -> AssignableAgentsResponse:
        role_name = current_user.role.name
        groups: list[AssignableGroup] = []

        if role_name == ACCOUNT_MANAGER_ROLE_NAME:
            team_leads = await self.user_repository.list_active_by_role_and_manager(
                TEAM_LEAD_ROLE_NAME, current_user.user_id
            )
            staff = await self.user_repository.list_active_by_role_and_manager(
                STAFF_ROLE_NAME, current_user.user_id
            )
            groups = [
                AssignableGroup(role=TEAM_LEAD_ROLE_NAME, users=[_summary(u) for u in team_leads]),
                AssignableGroup(role=STAFF_ROLE_NAME, users=[_summary(u) for u in staff]),
            ]

        elif role_name == TEAM_LEAD_ROLE_NAME:
            staff = await self.user_repository.list_active_staff_by_teamlead(
                current_user.user_id
            )
            groups = [
                AssignableGroup(role=STAFF_ROLE_NAME, users=[_summary(u) for u in staff]),
            ]

        elif role_name == SITE_LEAD_ROLE_NAME:
            account_managers = await self.user_repository.list_active_by_role_name(
                ACCOUNT_MANAGER_ROLE_NAME
            )
            team_leads = await self.user_repository.list_active_by_role_name(TEAM_LEAD_ROLE_NAME)
            staff = await self.user_repository.list_active_by_role_name(STAFF_ROLE_NAME)
            groups = [
                AssignableGroup(
                    role=ACCOUNT_MANAGER_ROLE_NAME,
                    users=[_summary(u) for u in account_managers],
                ),
                AssignableGroup(role=TEAM_LEAD_ROLE_NAME, users=[_summary(u) for u in team_leads]),
                AssignableGroup(role=STAFF_ROLE_NAME, users=[_summary(u) for u in staff]),
            ]

        elif role_name == SUPER_ADMIN_ROLE_NAME:
            super_admins = await self.user_repository.list_active_by_role_name(
                SUPER_ADMIN_ROLE_NAME
            )
            site_leads = await self.user_repository.list_active_by_role_name(SITE_LEAD_ROLE_NAME)
            account_managers = await self.user_repository.list_active_by_role_name(
                ACCOUNT_MANAGER_ROLE_NAME
            )
            team_leads = await self.user_repository.list_active_by_role_name(TEAM_LEAD_ROLE_NAME)
            staff = await self.user_repository.list_active_by_role_name(STAFF_ROLE_NAME)
            groups = [
                AssignableGroup(
                    role=SUPER_ADMIN_ROLE_NAME, users=[_summary(u) for u in super_admins]
                ),
                AssignableGroup(role=SITE_LEAD_ROLE_NAME, users=[_summary(u) for u in site_leads]),
                AssignableGroup(
                    role=ACCOUNT_MANAGER_ROLE_NAME,
                    users=[_summary(u) for u in account_managers],
                ),
                AssignableGroup(role=TEAM_LEAD_ROLE_NAME, users=[_summary(u) for u in team_leads]),
                AssignableGroup(role=STAFF_ROLE_NAME, users=[_summary(u) for u in staff]),
            ]

        # Staff (or any unhandled role): no groups — "Assigned To" is
        # always themselves, enforced client-side as a read-only field
        # and here too via resolve_target below.

        return AssignableAgentsResponse(me=_summary(current_user), groups=groups)

    async def resolve_target(self, current_user: User, agent_id: UUID | None) -> UUID | None:
        """
        Validates a chosen `agent_id` against the same set
        `get_assignable_groups` offers. `None` preserves the original,
        pre-existing behavior (ticket born unclaimed) for any caller
        that doesn't send this field at all.
        """

        if agent_id is None:
            return None

        if agent_id == current_user.user_id:
            return agent_id

        response = await self.get_assignable_groups(current_user)
        allowed_ids = {user.user_id for group in response.groups for user in group.users}

        if agent_id not in allowed_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You can only assign this ticket to yourself or someone in your reporting hierarchy.",
            )

        return agent_id
