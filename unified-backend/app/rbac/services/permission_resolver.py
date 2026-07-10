from shared_models.models import User

from app.rbac.repositories.permission_override_repository import (
    PermissionOverrideRepository,
)
from app.rbac.repositories.role_permission_repository import (
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
    ) -> tuple[list[str], list[str], dict[str, list[str]]]:
        """
        Returns (all_effective_permission_names, override_only_names,
        scoped_permissions). The first two are sorted lists, same as
        before scoped overrides existed; override_only_names is always
        a subset of all_effective_permission_names. scoped_permissions
        maps a permission name to the list of ticket ids (as strings)
        it's been granted for — these are deliberately excluded from
        the first two return values, since a ticket-scoped override
        must never read as "holds this permission everywhere" to a
        flat membership check like has_permission.
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

        global_override_names = {
            o.permission.permission_name
            for o in active_overrides
            if o.scope_ticket_id is None
        }

        scoped_permissions: dict[str, list[str]] = {}
        for o in active_overrides:
            if o.scope_ticket_id is None:
                continue
            scoped_permissions.setdefault(o.permission.permission_name, []).append(
                str(o.scope_ticket_id)
            )

        override_only_names = sorted(global_override_names - role_names)
        all_names = sorted(role_names | global_override_names)

        return all_names, override_only_names, scoped_permissions
