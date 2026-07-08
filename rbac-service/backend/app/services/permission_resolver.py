from shared_models.models import User

from app.repositories.permission_override_repository import (
    PermissionOverrideRepository,
)
from app.repositories.role_permission_repository import (
    RolePermissionRepository,
)


class PermissionResolverService:
    """
    The single place a user's effective permissions are computed:
    role defaults unioned with their active (non-revoked, non-expired)
    personal overrides. AuthService, the JWT-issuing code, and the
    override grant/revoke authorization check all go through this, so
    they can never disagree about what "effective permissions" means.
    """

    def __init__(
        self,
        role_permission_repository: RolePermissionRepository,
        permission_override_repository: PermissionOverrideRepository,
    ):
        self.role_permission_repository = role_permission_repository
        self.permission_override_repository = permission_override_repository

    async def get_effective_permissions(
        self,
        user: User,
    ) -> tuple[list[str], list[str]]:
        """
        Returns (all_effective_permission_names, override_only_names),
        both sorted. override_only_names is always a subset of
        all_effective_permission_names — it exists so callers can tell
        which of a user's permissions came from a personal grant rather
        than their role, without a second query.
        """

        role_permissions = (
            await self.role_permission_repository.get_permissions_by_role(
                user.role_id
            )
        )
        role_names = {p.permission_name for p in role_permissions}

        active_overrides = (
            await self.permission_override_repository.list_active_by_user(
                user.user_id
            )
        )
        override_names = {
            o.permission.permission_name for o in active_overrides
        }

        override_only_names = sorted(override_names - role_names)
        all_names = sorted(role_names | override_names)

        return all_names, override_only_names
