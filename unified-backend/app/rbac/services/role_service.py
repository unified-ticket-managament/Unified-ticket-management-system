import json
from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import Role, User

from app.rbac.repositories import RoleRepository
from app.rbac.schemas.audit_log import AuditLogCreate
from app.rbac.schemas.role import RoleCreate, RoleUpdate
from app.rbac.services.audit_log_service import AuditLogService


class RoleService:
    """
    Business logic for Role operations.
    """

    def __init__(
        self,
        role_repository: RoleRepository,
        audit_log_service: AuditLogService,
    ):
        self.role_repository = role_repository
        self.audit_log_service = audit_log_service

    # --------------------------------------------------
    # Create Role
    # --------------------------------------------------

    async def create_role(
        self,
        role_data: RoleCreate,
        actor: User | None = None,
    ) -> Role:

        exists = await self.role_repository.get_by_name_case_insensitive(
            role_data.name
        )

        if exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Role already exists.",
            )

        role = Role(
            name=role_data.name,
        )

        role = await self.role_repository.create(role)

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="role.create",
                entity_type="role",
                entity_id=str(role.role_id),
                new_value=json.dumps({"name": role.name}),
            )
        )

        return role

    # --------------------------------------------------
    # Get Role
    # --------------------------------------------------

    async def get_role(
        self,
        role_id: UUID,
    ) -> Role:

        role = await self.role_repository.get_by_id(
            role_id
        )

        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found.",
            )

        return role

    async def get_role_by_name(
        self,
        name: str,
    ) -> Role:

        role = await self.role_repository.get_by_name(
            name
        )

        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found.",
            )

        return role

    async def list_roles(
        self,
        page: int = 1,
        page_size: int = 10,
    ):
        return await self.role_repository.get_all(
            page,
            page_size,
        )

    # --------------------------------------------------
    # Update Role
    # --------------------------------------------------

    async def update_role(
        self,
        role_id: UUID,
        role_data: RoleUpdate,
        actor: User | None = None,
    ) -> Role:

        role = await self.get_role(role_id)

        update_data = role_data.model_dump(
            exclude_unset=True
        )

        if "name" in update_data:

            exists = await self.role_repository.get_by_name_case_insensitive(
                update_data["name"]
            )

            if (
                exists
                and exists.role_id != role.role_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Role already exists.",
                )

        old_values = {field: getattr(role, field) for field in update_data}

        for field, value in update_data.items():
            setattr(role, field, value)

        role = await self.role_repository.update(role)

        if update_data:
            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="role.update",
                    entity_type="role",
                    entity_id=str(role.role_id),
                    old_value=json.dumps(old_values),
                    new_value=json.dumps(update_data),
                )
            )

        return role

    # --------------------------------------------------
    # Delete Role
    # --------------------------------------------------

    async def delete_role(
        self,
        role_id: UUID,
        actor: User | None = None,
    ):

        role = await self.get_role(role_id)

        user_count = await self.role_repository.get_users_count(
            role.role_id
        )

        if user_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Role cannot be deleted because it is assigned to users.",
            )

        await self.role_repository.delete(role)

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="role.delete",
                entity_type="role",
                entity_id=str(role_id),
                old_value=json.dumps({"name": role.name}),
            )
        )