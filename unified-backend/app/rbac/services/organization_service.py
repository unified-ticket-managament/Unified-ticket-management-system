from uuid import UUID

from shared_models.models import User

from app.rbac.repositories import ReportingManagerRepository, RoleRepository, UserRepository
from app.rbac.schemas.organization import OrganizationNode


class OrganizationService:
    """
    Builds the Organization Chart for a user — a literal, role-agnostic
    reporting hierarchy computed purely from `User.reporting_manager_id`,
    a dedicated, unrestricted-by-role column introduced specifically
    for this chart (see shared_models' User model and alembic_rbac's
    add_reporting_manager_id_to_users migration). For the viewed
    profile (`current_user`), the chart shows:

      1. Their real reporting-manager chain, climbed one real parent at
         a time via `reporting_manager_id`, all the way to the top of
         the company — never fanning out to a sibling's branch, and
         never inserting a role-implied layer (e.g. "Site Lead") that
         isn't backed by an actual FK on some row.
      2. The viewed profile itself.
      3. Their full downward subtree, recursive — every active user
         whose own `reporting_manager_id` points (directly or
         transitively) back to the viewed profile — again with no role
         assumption about who can have reports (a Team Lead, an
         Account Manager, or even a Staff member with a report of
         their own all resolve the same way).

    **`reporting_manager_id` is deliberately a separate column from
    `manager_id`/`teamlead_id`, not a replacement for them.** Those two
    fields continue, completely unchanged, to drive every other
    existing consumer — permission-override/permission-request
    scoping (`_build_subtree`/`get_subordinate_user_ids` below),
    ticket-assignment pickers, SLA/escalation ownership resolution,
    audit-log visibility. This chart is the *only* thing that reads
    `reporting_manager_id`; nothing else should. `reporting_manager_id`
    was one-time backfilled from `manager_id`/`teamlead_id` (teamlead_id
    wins when both are set) at migration time, then is independently
    editable going forward via `UserService`'s own create/update paths.

    `reporting_manager_teams` (an Account Manager's "Reporting Manager"
    HR responsibility over a category) is a separate, still-fully-
    functional feature (`ReportingManagerService`) — this chart does
    not read it and never has, independent of the reporting_manager_id
    column added here.

    `get_subordinate_user_ids` (used to scope permission-override grant
    authority — an unrelated, purely-RBAC concept) deliberately keeps
    using the narrower, private `_build_subtree` below, which reads
    `manager_id`/`teamlead_id` and is role-shaped on purpose (Account
    Manager's own reports are resolved only via the Team-Lead-role
    tier, matching how override-grant authority has always been
    scoped) — this is intentionally NOT the same traversal or the same
    column `get_chart_for_user` uses, and must not be changed to match
    it.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        reporting_manager_repository: ReportingManagerRepository | None = None,
    ):
        self.user_repository = user_repository
        self.role_repository = role_repository
        # No longer read by this service (the Reporting-Manager-category
        # widening that used to consume it was removed — see this
        # class's own docstring) — kept as a constructor parameter so
        # every existing call site (DI factories, tests) stays
        # unchanged; ReportingManagerService is still the real, active
        # consumer of this repository elsewhere.
        self.reporting_manager_repository = reporting_manager_repository

    # --------------------------------------------------
    # Entry Point
    # --------------------------------------------------

    async def get_chart_for_user(
        self,
        current_user: User,
    ) -> OrganizationNode:
        """
        current_user's own literal chart: their real manager chain
        above them, and their full real reporting subtree below them.
        Works identically for every role — Super Admin, Site Lead,
        Account Manager, Team Lead, Staff, Viewer, Client — since
        nothing here branches on role, only on whether manager_id/
        teamlead_id/direct-report rows actually exist.
        """

        node = await self._build_literal_subtree(current_user)

        # Climb the real, single-parent chain to the top. `visited`
        # guards against a corrupted/cyclical manager_id chain (should
        # never happen given UserService's own validation, but this
        # must not hang or crash if it somehow does).
        visited = {current_user.user_id}
        ancestor = await self._resolve_immediate_manager(current_user)

        while ancestor is not None and ancestor.user_id not in visited:
            visited.add(ancestor.user_id)
            node = await self._to_node(ancestor, [node])
            ancestor = await self._resolve_immediate_manager(ancestor)

        return node

    async def _resolve_immediate_manager(self, user: User) -> User | None:
        """
        The one real, specific person `user` reports to, per
        `reporting_manager_id` — this chart's sole source of truth
        (see this class's own docstring for why that's a dedicated
        column, not `manager_id`/`teamlead_id`).
        """

        if user.reporting_manager_id is None:
            return None
        return await self.user_repository.get_by_id(user.reporting_manager_id)

    async def _build_literal_subtree(
        self,
        user: User,
        visited: set[UUID] | None = None,
    ) -> OrganizationNode:
        """
        `user`'s full downward subtree, recursive — every active user
        whose own `reporting_manager_id` resolves back to `user`,
        directly or transitively, via UserRepository.get_direct_reports
        at every level. No role branching: this is what lets, e.g., an
        Account Manager whose real data has both Team Leads and
        individual Staff reporting straight to them render correctly,
        which a "Team Leads always sit between Account Manager and
        Staff" assumption would have silently dropped.

        `visited` guards against a corrupted/cyclical
        `reporting_manager_id` chain (e.g. A's report is B, and B's own
        reporting_manager_id was somehow reassigned to point at A) —
        without it, such a cycle would recurse forever building the
        downward tree, unlike the upward climb in get_chart_for_user,
        which already has its own separate cycle guard.
        """

        seen = visited if visited is not None else {user.user_id}
        reports = await self.user_repository.get_direct_reports(user.user_id)

        children: list[OrganizationNode] = []
        for report in reports:
            if report.user_id in seen:
                continue
            seen.add(report.user_id)
            children.append(await self._build_literal_subtree(report, seen))

        return await self._to_node(user, children)

    # --------------------------------------------------
    # Subtree Construction — reporting line only (SECURITY-SENSITIVE:
    # get_subordinate_user_ids below relies on this staying scoped to
    # the real manager_id/teamlead_id line, resolved role-by-role — see
    # this module's own docstring. Deliberately NOT the same traversal
    # get_chart_for_user uses above.)
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
        _build_subtree — deliberately NOT _build_literal_subtree, see
        this module's own docstring) into the set of every user_id
        reporting to them, directly or transitively. Reuses the same
        manager_id/teamlead_id traversal already built for permission-
        override scoping — used to scope an Account Manager's
        permission-override grant authority to "their own reports"
        only. Must stay role-shaped exactly as it always has; widening
        it to match the Organization Chart's own literal traversal
        would change who an Account Manager can grant/revoke
        permissions for, which is out of scope for the chart fix this
        method's sibling above was built for.
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
    # Users-page reporting-manager visibility scope (SEPARATE from
    # get_subordinate_user_ids above — see this module's own docstring
    # and UserService.list_users' `include_reporting_scope` flag)
    # --------------------------------------------------

    async def get_reporting_scope_user_ids(
        self,
        current_user: User,
    ) -> set[UUID] | None:
        """
        Users-page-only visibility scope (see
        UserService.list_users' `include_reporting_scope` flag).

        Primary source: `reporting_manager_id` — the SAME dedicated
        column the Organization Chart itself is built on
        (`get_direct_reports`/`_build_literal_subtree`, see this
        module's own docstring), walked recursively/downward from the
        caller here as a flat set instead of a tree. This is the real,
        already-existing, independently-maintained "who reports to me"
        relationship in this system — confirmed against live data as
        the correct answer for both a single-category Account Manager
        (13 Staff + 1 Team Lead, all via `reporting_manager_id`,
        matching `manager_id` exactly) and a dual-category Team Lead
        (23 reports spanning Payment Posting, Quality, AR, IV, and
        Coding — categories her own `manager_id`/`teamlead_id`-based
        reports alone never captured, since several of those reports
        have no `teamlead_id` set to anyone at all yet). Earlier
        attempts to approximate this via `manager_id`/`teamlead_id`
        alone, or via widening by the caller's own category tags, were
        both superseded — the latter was actively wrong, pulling in
        unrelated same-category people with no real reporting
        relationship to the caller at all.

        Seeded from the same baseline the non-widened path already
        uses (get_subordinate_user_ids for Account Manager/Team Lead —
        preserving its "the manager never sees themselves" semantics —
        or self-only for everyone else) purely as a safety net for a
        user whose `reporting_manager_id` hasn't been backfilled/set
        yet but whose real `manager_id`/`teamlead_id` already is.

        A second, still-real edge — `reporting_manager_teams` category
        membership — is also checked at every node reached (not just
        the original caller), so an Account Manager holding that
        separate, explicit HR "Reporting Manager for this whole
        category" assignment is still honored on top of the
        reporting_manager_id tree.

        Both edges are keyed purely on real data at each node — never
        on role name — so this generalizes to any manager/hierarchy
        depth automatically, with no code change. `visited` guards
        against cycles/duplicates and bounds the traversal.

        Does not call anything that changes get_subordinate_user_ids'
        own behavior; permission-override grant scoping
        (PermissionOverrideService/PermissionRequestService) keeps
        using that narrower method directly, untouched.
        """

        role_name = current_user.role.name if current_user.role is not None else None

        if role_name in ("Super Admin", "Site Lead"):
            return None

        if role_name in ("Account Manager", "Team Lead"):
            scope = set(await self.get_subordinate_user_ids(current_user))
        else:
            scope = {current_user.user_id}

        visited = set(scope) | {current_user.user_id}
        queue = list(visited)

        while queue:
            node_id = queue.pop()

            direct_reports = await self.user_repository.get_direct_reports(node_id)
            for report in direct_reports:
                if report.user_id not in visited:
                    visited.add(report.user_id)
                    scope.add(report.user_id)
                    queue.append(report.user_id)

            if self.reporting_manager_repository is not None:
                rm_category_ids = (
                    await self.reporting_manager_repository.list_category_ids_by_account_manager(
                        node_id
                    )
                )
                if rm_category_ids:
                    category_member_ids = await self.user_repository.list_active_ids_by_categories(
                        rm_category_ids
                    )
                    for member_id in category_member_ids:
                        if member_id not in visited:
                            visited.add(member_id)
                            scope.add(member_id)
                            queue.append(member_id)

        return scope

    async def get_reporting_manager_user_ids(
        self,
        user_ids: list[UUID],
    ) -> set[UUID]:
        """
        Among `user_ids`, which hold at least one active
        reporting_manager_teams assignment (any category) — i.e. are a
        Reporting Manager at all. This is an HR responsibility layered
        on top of the Account Manager role, not a Role/permission of
        its own — deliberately not creating either just to answer this
        question. Backs the Users page's "Reporting Manager" option in
        its Role filter dropdown.
        """

        if self.reporting_manager_repository is None or not user_ids:
            return set()

        return await self.reporting_manager_repository.list_account_manager_ids_among(
            user_ids
        )

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

    async def _to_node(
        self,
        user: User,
        children: list[OrganizationNode] | None = None,
    ) -> OrganizationNode:

        # `departments` (plural, the new multi-category-aware field)
        # is the real source; `department` (singular, pre-existing) is
        # derived from it for back-compat — for a 0-or-1-category user
        # this renders byte-identical to before this change.
        departments = sorted(c.category_name.value for c in user.categories)
        department = (
            ", ".join(departments)
            if departments
            else (
                user.category.category_name.value
                if user.category is not None
                else None
            )
        )

        return OrganizationNode(
            user_id=user.user_id,
            name=user.name,
            email=user.email,
            role=user.role.name,
            department=department,
            departments=departments,
            is_active=user.is_active,
            children=children or [],
        )
