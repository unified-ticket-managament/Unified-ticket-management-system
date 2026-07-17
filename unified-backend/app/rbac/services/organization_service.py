from uuid import UUID

from shared_models.models import User

from app.rbac.repositories import ReportingManagerRepository, RoleRepository, UserRepository
from app.rbac.schemas.organization import OrganizationNode

# Roles this chart treats as part of the formal company hierarchy —
# Site Lead is included here (unlike the old ROLE_HIERARCHY it
# replaces) since the chart must now always show it as a fixed layer
# between Super Admin and Account Manager, even though nothing on
# `User` literally links a Team Lead/Account Manager to a specific
# Site Lead (see get_chart_for_user's own docstring). Every other role
# (Viewer, and anything unrecognized) renders as a standalone node.
ANCESTOR_ROLE_NAMES = {"Staff", "Team Lead", "Account Manager", "Site Lead", "Super Admin"}


class OrganizationService:
    """
    Builds the organization chart for a user — always the FULL chain
    from the top of the company down through that user's own position,
    then continuing down through their subordinates. Every call is
    "the chart for this specific profile": the same viewer sees a
    different tree depending on whose profile they're viewing (in
    practice, today, only their own — see users.py's
    `/users/me/organization-chart`), never one fixed, static tree.

    Three genuinely independent relationships feed this chart, per
    root CLAUDE.md's "Organization Structure" section:

    1. The real reporting line (`manager_id`/`teamlead_id` on User) —
       Super Admin > Account Manager > Team Lead > Staff.
    2. The Reporting Manager mapping (ReportingManagerTeam) — a
       genuinely many-to-many, database-driven Account Manager <->
       category assignment representing an *additional* HR
       responsibility, not a reporting-line change.
    3. Ticket-assignment capability — every Account Manager can work
       with every Team Lead company-wide (see AssignmentService), a
       fact this chart now reflects directly: viewing an Account
       Manager's own profile expands to EVERY Team Lead, not just
       their direct reports or Reporting Manager categories.

    Each Team Lead rendered under an Account Manager is tagged with
    which of these three relationships actually produced the edge
    (`relationship_to_parent`: "reports_to" / "reporting_manager" /
    "assignable"), so the frontend never conflates a real reporting
    line with the other two, purely-informational connections.

    **Above** the viewed profile, this chart shows only the one real,
    specific ancestor chain — never fanning out into a sibling's
    unrelated branch (e.g. a Staff member's chart shows their own Team
    Lead and that Team Lead's own connected Account Manager(s), never
    every other Team Lead or Account Manager in the company). A Team
    Lead can genuinely have more than one connected Account Manager
    (their real `manager_id` supervisor, plus every Account Manager
    who is Reporting Manager for that Team Lead's category) — when
    that happens, every connected Account Manager renders as a sibling
    ancestor, each showing only the one shared branch back down to the
    viewed profile, not their own unrelated Team Leads too. Site Lead
    is always inserted as a single fixed layer between Super Admin and
    Account Manager for this reason too — there's no `site_lead_id`
    column to resolve a specific one from, and product-wise every
    Account Manager sits under the same company-wide Site Lead(s).

    **Below and at** the viewed profile (`_expand_downward`), the
    chart always uses the widened, full rule for that role (all Site
    Leads under Super Admin, all Account Managers under Site Lead, all
    Team Leads under an Account Manager, that Team Lead's own Staff)
    — this is what makes viewing Super Admin/Site Lead show the whole
    company, while viewing one Staff member still shows only their own
    single ancestor chain above them.

    `get_subordinate_user_ids` (used to scope permission-override
    authority — an unrelated, purely-RBAC concept) deliberately keeps
    using the narrower, private `_build_subtree` below (real
    manager_id/teamlead_id reports only): neither the Reporting
    Manager mapping nor the wider ticket-assignment relationship this
    chart now displays should ever widen who an Account Manager can
    grant/revoke permissions for — the same "never bypass the real
    boundary" principle the Reporting Manager business rule already
    applies to client access.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        reporting_manager_repository: ReportingManagerRepository | None = None,
    ):
        self.user_repository = user_repository
        self.role_repository = role_repository
        self.reporting_manager_repository = reporting_manager_repository

    # --------------------------------------------------
    # Entry Point
    # --------------------------------------------------

    async def get_chart_for_user(
        self,
        current_user: User,
    ) -> OrganizationNode:

        role_name = current_user.role.name

        if role_name not in ANCESTOR_ROLE_NAMES:
            # Roles outside the formal hierarchy (Viewer) are shown standalone.
            return await self._to_node(current_user)

        # The viewed profile's own position, expanded fully downward
        # (see _expand_downward — this is what makes Super Admin/Site
        # Lead show the whole company, and an Account Manager show
        # every Team Lead they can work with).
        node = await self._expand_downward(current_user)

        if role_name == "Super Admin":
            # _expand_downward already recursed all the way down from
            # the very top — nothing sits above Super Admin to wrap it in.
            return node

        # `frontier` is the set of (user, already-built node) pairs
        # still needing to climb further up. It starts as just the
        # viewed profile itself, and can briefly widen to more than
        # one entry only when a Team Lead has multiple connected
        # Account Managers (see _resolve_connected_account_managers).
        frontier: list[tuple[User, OrganizationNode]] = [(current_user, node)]

        if role_name == "Staff":
            team_lead = None
            if current_user.teamlead_id is not None:
                team_lead = await self.user_repository.get_by_id(current_user.teamlead_id)

            if team_lead is not None:
                frontier = [(team_lead, await self._to_node(team_lead, [node]))]
            elif current_user.manager_id is not None:
                # No Team Lead on record — degrade to climbing
                # straight through whatever manager_id points at
                # (normally an Account Manager) instead of stopping.
                manager = await self.user_repository.get_by_id(current_user.manager_id)
                if manager is not None:
                    frontier = [(manager, await self._to_node(manager, [node]))]
            # else: a fully orphaned Staff record (no teamlead_id, no
            # manager_id) — frontier stays [(current_user, node)] and
            # attaches directly under Site Lead/Super Admin below,
            # rather than crashing.

        if role_name in ("Staff", "Team Lead"):
            climbed: list[tuple[User, OrganizationNode]] = []

            for user_at_level, built_node in frontier:
                if user_at_level.role.name == "Team Lead":
                    connected_ams = await self._resolve_connected_account_managers(
                        user_at_level
                    )

                    if connected_ams:
                        for am in connected_ams:
                            reporting_manager_for_names = (
                                await self._reporting_manager_categories(am)
                            )
                            climbed.append(
                                (
                                    am,
                                    await self._to_node(
                                        am,
                                        [built_node],
                                        reporting_manager_for=reporting_manager_for_names,
                                    ),
                                )
                            )
                    else:
                        # An orphaned Team Lead with no connected
                        # Account Manager at all — attaches directly
                        # under Site Lead/Super Admin below.
                        climbed.append((user_at_level, built_node))
                else:
                    climbed.append((user_at_level, built_node))

            frontier = climbed

        if role_name in ("Staff", "Team Lead", "Account Manager"):
            site_lead = await self._first_by_role("Site Lead")

            if site_lead is not None:
                children = [n for _, n in frontier]
                frontier = [(site_lead, await self._to_node(site_lead, children))]
            # else: no Site Lead seeded at all — leave `frontier` as
            # the Account Manager tier, wrapped directly under Super
            # Admin below instead.

        # role_name == "Site Lead" reaches here with `frontier`
        # untouched from its initial [(current_user, node)] — nothing
        # sits between Site Lead and Super Admin to resolve.

        super_admin = await self._first_by_role("Super Admin")

        if super_admin is None:
            # No Super Admin on record at all (shouldn't happen with
            # real seed data) — return the topmost node reached rather
            # than crash.
            return frontier[0][1]

        children = [n for _, n in frontier]
        return await self._to_node(super_admin, children)

    # --------------------------------------------------
    # Downward expansion — the viewed profile's own full subtree,
    # using the widened, "everyone at this tier" rule per role. Used
    # only for rendering the org chart — never for authority/scoping
    # decisions (see get_subordinate_user_ids/_build_subtree below).
    # --------------------------------------------------

    async def _expand_downward(
        self,
        user: User,
        relationship_to_parent: str = "reports_to",
    ) -> OrganizationNode:

        role_name = user.role.name
        children_nodes: list[OrganizationNode] = []
        reporting_manager_for_names: list[str] = []

        if role_name == "Super Admin":
            site_leads = await self._all_by_role("Site Lead")

            if site_leads:
                children_nodes = [await self._expand_downward(sl) for sl in site_leads]
            else:
                # No Site Lead seeded yet — degrade to the pre-Site-
                # Lead shape (Super Admin directly over every Account
                # Manager) rather than showing an empty chart.
                children_nodes = [
                    await self._expand_downward(am)
                    for am in await self._all_by_role("Account Manager")
                ]

        elif role_name == "Site Lead":
            children_nodes = [
                await self._expand_downward(am)
                for am in await self._all_by_role("Account Manager")
            ]

        elif role_name == "Account Manager":
            reporting_manager_for_names = await self._reporting_manager_categories(user)

            rm_category_ids: set[UUID] = set()
            if self.reporting_manager_repository is not None:
                rm_category_ids = set(
                    await self.reporting_manager_repository.list_category_ids_by_account_manager(
                        user.user_id
                    )
                )

            for team_lead in await self._all_by_role("Team Lead"):
                if team_lead.manager_id == user.user_id:
                    edge = "reports_to"
                elif team_lead.category_id is not None and team_lead.category_id in rm_category_ids:
                    edge = "reporting_manager"
                else:
                    # Every Account Manager can hand work to any Team
                    # Lead (see AssignmentService) — this Team Lead is
                    # neither a direct report nor a Reporting Manager
                    # category, just reachable via that unrestricted
                    # ticket-assignment capability.
                    edge = "assignable"

                children_nodes.append(
                    await self._expand_downward(team_lead, relationship_to_parent=edge)
                )

        elif role_name == "Team Lead":
            for staff in await self.user_repository.get_by_teamlead(user.user_id):
                children_nodes.append(await self._expand_downward(staff))

        return await self._to_node(
            user,
            children_nodes,
            relationship_to_parent=relationship_to_parent,
            reporting_manager_for=reporting_manager_for_names,
        )

    # --------------------------------------------------
    # Ancestor resolution (narrow — only the real, specific connected
    # parent(s), never every user at that tier)
    # --------------------------------------------------

    async def _resolve_connected_account_managers(self, team_lead: User) -> list[User]:
        """
        Every Account Manager genuinely connected to `team_lead`: their
        real `manager_id` supervisor (the org-chart reporting line),
        plus every Account Manager who is Reporting Manager for this
        Team Lead's own category (many-to-many — see
        ReportingManagerTeam). Deliberately NOT "every Account Manager
        who could assign this Team Lead work" — that unrestricted
        ticket-assignment relationship is only ever shown as part of
        the viewed profile's own downward expansion
        (_expand_downward's "assignable" edge), never as an ancestor
        fan-out for someone else's chart.
        """

        connected: dict[UUID, User] = {}

        if team_lead.manager_id is not None:
            manager = await self.user_repository.get_by_id(team_lead.manager_id)
            if manager is not None and manager.role.name == "Account Manager":
                connected[manager.user_id] = manager

        if self.reporting_manager_repository is not None and team_lead.category_id is not None:
            am_ids = await self.reporting_manager_repository.list_account_manager_ids_by_category(
                team_lead.category_id
            )
            for am_id in am_ids:
                if am_id in connected:
                    continue
                am_user = await self.user_repository.get_by_id(am_id)
                if am_user is not None:
                    connected[am_id] = am_user

        return list(connected.values())

    async def _reporting_manager_categories(self, user: User) -> list[str]:
        if self.reporting_manager_repository is None or user.role.name != "Account Manager":
            return []

        rows = await self.reporting_manager_repository.list_by_account_manager(user.user_id)
        return [row.category_name.value for row in rows]

    # --------------------------------------------------
    # Subtree Construction — reporting line only (SECURITY-SENSITIVE:
    # get_subordinate_user_ids below relies on this staying scoped to
    # the real manager_id/teamlead_id line — see this module's own
    # docstring)
    # --------------------------------------------------

    async def _build_subtree(
        self,
        user: User,
    ) -> OrganizationNode:

        role_name = user.role.name
        children_users: list[User] = []

        if role_name == "Super Admin":
            children_users = await self._all_by_role("Account Manager")

        elif role_name == "Account Manager":
            team_lead_role = await self.role_repository.get_by_name("Team Lead")

            if team_lead_role is not None:
                children_users = await self.user_repository.get_by_manager_and_role(
                    user.user_id,
                    team_lead_role.role_id,
                )

        elif role_name == "Team Lead":
            children_users = await self.user_repository.get_by_teamlead(
                user.user_id,
            )

        children = [
            await self._build_subtree(child)
            for child in children_users
        ]

        return await self._to_node(user, children)

    # --------------------------------------------------
    # Subordinate Lookup
    # --------------------------------------------------

    async def get_subordinate_user_ids(
        self,
        user: User,
    ) -> set[UUID]:
        """
        Flattens this user's own reporting-line subtree (see
        _build_subtree — deliberately NOT _expand_downward, see this
        module's own docstring) into the set of every user_id
        reporting to them, directly or transitively. Reuses the same
        manager_id/teamlead_id traversal already built for the org
        chart instead of duplicating it — used to scope an Account
        Manager's permission-override grant authority to "their own
        reports" only. Neither a Reporting Manager assignment nor the
        wider ticket-assignment relationship must ever widen this set.
        """

        root = await self._build_subtree(user)
        subordinate_ids: set[UUID] = set()

        def collect(node: OrganizationNode) -> None:
            for child in node.children:
                subordinate_ids.add(child.user_id)
                collect(child)

        collect(root)

        return subordinate_ids

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    async def _all_by_role(
        self,
        role_name: str,
    ) -> list[User]:

        role = await self.role_repository.get_by_name(role_name)

        if role is None:
            return []

        return await self.user_repository.get_by_role(role.role_id)

    async def _first_by_role(
        self,
        role_name: str,
    ) -> User | None:

        users = await self._all_by_role(role_name)

        return users[0] if users else None

    async def _to_node(
        self,
        user: User,
        children: list[OrganizationNode] | None = None,
        relationship_to_parent: str = "reports_to",
        reporting_manager_for: list[str] | None = None,
    ) -> OrganizationNode:

        department = (
            user.category.category_name.value
            if user.category is not None
            else None
        )

        return OrganizationNode(
            user_id=user.user_id,
            name=user.name,
            email=user.email,
            role=user.role.name,
            department=department,
            is_active=user.is_active,
            relationship_to_parent=relationship_to_parent,
            reporting_manager_for=reporting_manager_for or [],
            children=children or [],
        )
