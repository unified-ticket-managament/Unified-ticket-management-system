from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.assignment import (
    AssignableAgentsResponse,
    AssignableGroup,
    AssignableUserSummary,
)
# Role-name constants imported from the centralized access_control.py
# rather than redeclared locally (this module used to declare its own
# copy of all five) — re-exported under the same names, so any other
# module importing them FROM assignment_service (e.g. ticket_service.py
# imports STAFF_ROLE_NAME from here) keeps working unchanged.
from app.ticketing.services.access_control import (
    ACCOUNT_MANAGER_ROLE_NAME,
    SITE_LEAD_ROLE_NAME,
    STAFF_ROLE_NAME,
    SUPER_ADMIN_ROLE_NAME,
    TEAM_LEAD_ROLE_NAME,
    ensure_has_permission,
)


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
    - Account Manager: every active Team Lead AND every active Staff
      member — both **narrowed to the ticket's own category whenever
      one is known** (see `category_name` below), since each category
      has exactly one operational team (one Team Lead, a handful of
      Staff) and a company-wide, unscoped list of either is meaningless
      noise once the ticket's own department is already known. Falls
      back to the full company-wide Team Lead list (still respecting
      the underlying Organization Structure business rule — see root
      CLAUDE.md — that any Account Manager may in principle work with
      any Team Lead) only while no category has been chosen yet in the
      dialog. This picker-level narrowing is purely a UI convenience —
      it does NOT narrow `InteractionService.transfer_agent`'s own,
      separately-gated ability to hand an *existing* ticket to any
      Team Lead company-wide; that rule is untouched.
    - Team Lead: their own reporting Staff (`teamlead_id` match, always
      already within their own category by construction), plus
      themselves.
    - Site Lead: every active Account Manager / Team Lead / Staff,
      narrowed to `category_name` for the Team Lead/Staff groups the
      same way Account Manager's are, when one is known — Site Lead
      keeps unrestricted oversight, this is purely about not showing
      an irrelevant company-wide list when the caller already told us
      which category the new ticket belongs to.
    - Super Admin: every active user of every role, same category
      narrowing as Site Lead for Team Lead/Staff.
    - Staff (or anything else): no groups — always themselves only.

    `category_name` (optional, a `CategoryName` value like
    "Eligibility") is the new ticket's own `ticket_type` — passed by
    the caller (the GET /agents/assignable route reads it from a query
    param; `resolve_target` below reads it from the same
    `TicketFromInteractionCreate.ticket_type` the ticket is actually
    being created with) so the "Assigned To" picker and the server-side
    validation of whatever was picked always agree on the same scope.
    Omitting it preserves the old, unscoped-by-category behavior — this
    is additive, not a breaking change for any caller that doesn't know
    the category yet.
    """

    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    async def get_assignable_groups(
        self,
        current_user: User,
        category_name: str | None = None,
    ) -> AssignableAgentsResponse:
        role_name = current_user.role.name
        groups: list[AssignableGroup] = []

        if role_name == ACCOUNT_MANAGER_ROLE_NAME:
            # Both groups narrow to category_name when known — see the
            # class docstring's Account Manager rule above. Team Lead
            # previously listed every Team Lead company-wide
            # unconditionally; Staff previously used
            # list_active_by_role_and_manager (only Staff who report
            # directly to *this* Account Manager via manager_id, a
            # company-wide reporting-line coincidence, not a category
            # concept — empty for every Account Manager except
            # whichever one happens to be every Staff member's
            # manager_id). Both fall back to their old, unscoped
            # behavior only while no category is known yet, so a
            # caller that hasn't picked one still sees a sensible
            # default list rather than an empty one.
            team_leads = (
                await self.user_repository.list_active_by_role_and_category(
                    TEAM_LEAD_ROLE_NAME, category_name
                )
                if category_name is not None
                else await self.user_repository.list_active_by_role_name(TEAM_LEAD_ROLE_NAME)
            )
            staff = (
                await self.user_repository.list_active_staff_by_category(category_name)
                if category_name is not None
                else await self.user_repository.list_active_by_role_and_manager(
                    STAFF_ROLE_NAME, current_user.user_id
                )
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
            team_leads = (
                await self.user_repository.list_active_by_role_and_category(
                    TEAM_LEAD_ROLE_NAME, category_name
                )
                if category_name is not None
                else await self.user_repository.list_active_by_role_name(TEAM_LEAD_ROLE_NAME)
            )
            staff = (
                await self.user_repository.list_active_staff_by_category(category_name)
                if category_name is not None
                else await self.user_repository.list_active_by_role_name(STAFF_ROLE_NAME)
            )
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
            team_leads = (
                await self.user_repository.list_active_by_role_and_category(
                    TEAM_LEAD_ROLE_NAME, category_name
                )
                if category_name is not None
                else await self.user_repository.list_active_by_role_name(TEAM_LEAD_ROLE_NAME)
            )
            staff = (
                await self.user_repository.list_active_staff_by_category(category_name)
                if category_name is not None
                else await self.user_repository.list_active_by_role_name(STAFF_ROLE_NAME)
            )
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

    async def resolve_target(
        self,
        current_user: User,
        agent_id: UUID | None,
        category_name: str | None = None,
    ) -> UUID | None:
        """
        Validates a chosen `agent_id` against the same set
        `get_assignable_groups` offers. `None` preserves the original,
        pre-existing behavior (ticket born unclaimed) for any caller
        that doesn't send this field at all. `category_name` must be
        the same value the picker itself was scoped by (the ticket's
        own `ticket_type`), so this re-validation can never reject a
        choice the picker legitimately offered.
        """

        if agent_id is None:
            return None

        if agent_id == current_user.user_id:
            return agent_id

        # Assigning to someone other than yourself is ticket:assign —
        # Full by default for Super Admin/Site Lead/Account Manager
        # (own clients)/Team Lead (team), Override-only for Staff. The
        # reporting-hierarchy check below already independently blocks
        # Staff from reaching anyone (their own groups are always
        # empty), but this makes the permission itself the enforcement
        # point rather than a side effect of hierarchy shape.
        ensure_has_permission(current_user, "ticket:assign")

        response = await self.get_assignable_groups(current_user, category_name)
        allowed_ids = {user.user_id for group in response.groups for user in group.users}

        if agent_id not in allowed_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You can only assign this ticket to yourself or someone in your reporting hierarchy.",
            )

        return agent_id
