from shared_models.models import User

from app.repositories import RoleRepository, UserRepository
from app.schemas.organization import OrganizationNode

# Fixed hierarchy levels this chart understands. Roles outside this
# list (e.g. Viewer) are not part of the formal reporting structure.
ROLE_HIERARCHY = ["Super Admin", "Manager", "Team Lead", "Staff"]


class OrganizationService:
    """
    Builds the organization chart for a user.

    The chart is derived from role level (Super Admin > Manager >
    Team Lead > Staff) combined with the existing `manager_id` /
    `teamlead_id` relationships on User - no additional schema is
    required.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
    ):
        self.user_repository = user_repository
        self.role_repository = role_repository

    # --------------------------------------------------
    # Entry Point
    # --------------------------------------------------

    async def get_chart_for_user(
        self,
        current_user: User,
    ) -> OrganizationNode:

        role_name = current_user.role.name

        if role_name not in ROLE_HIERARCHY:
            # Roles outside the formal hierarchy are shown standalone.
            return await self._to_node(current_user)

        level = ROLE_HIERARCHY.index(role_name)

        # The logged-in user always sees their own full subtree...
        node = await self._build_subtree(current_user)
        user = current_user

        # ...but ancestors above them are a single chain, never
        # fanning out to a sibling's branch (e.g. a Team Lead must
        # not see their Manager's other Team Leads).
        for depth in range(level, 0, -1):
            parent = await self._get_parent(user, depth)

            if parent is None:
                break

            node = await self._to_node(parent, [node])
            user = parent

        return node

    # --------------------------------------------------
    # Ancestor Resolution
    # --------------------------------------------------

    async def _get_parent(
        self,
        user: User,
        depth: int,
    ) -> User | None:
        """
        Returns the direct supervisor of `user`, who sits at
        hierarchy depth `depth - 1`.
        """

        # Staff -> Team Lead (fall back to Manager if unassigned)
        if depth == 3:
            if user.teamlead_id is not None:
                return await self.user_repository.get_by_id(user.teamlead_id)

            if user.manager_id is not None:
                return await self.user_repository.get_by_id(user.manager_id)

            return None

        # Team Lead -> Manager
        if depth == 2:
            if user.manager_id is not None:
                return await self.user_repository.get_by_id(user.manager_id)

            return None

        # Manager -> Super Admin (no manager_id is set by default, so
        # fall back to the first Super Admin account on record)
        if depth == 1:
            if user.manager_id is not None:
                return await self.user_repository.get_by_id(user.manager_id)

            return await self._first_by_role("Super Admin")

        return None

    # --------------------------------------------------
    # Subtree Construction
    # --------------------------------------------------

    async def _build_subtree(
        self,
        user: User,
    ) -> OrganizationNode:

        role_name = user.role.name
        children_users: list[User] = []

        if role_name == "Super Admin":
            children_users = await self._all_by_role("Manager")

        elif role_name == "Manager":
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
    ) -> OrganizationNode:

        return OrganizationNode(
            user_id=user.user_id,
            name=user.name,
            email=user.email,
            role=user.role.name,
            department=None,
            is_active=user.is_active,
            children=children or [],
        )
