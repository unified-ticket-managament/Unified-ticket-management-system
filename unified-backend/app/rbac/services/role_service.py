from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import Role

from app.rbac.repositories import RoleRepository
from app.rbac.schemas.role import RoleCreate, RoleUpdate


class RoleService:
    """
    Business logic for Role operations.
    """

    def __init__(
        self,
        role_repository: RoleRepository,
    ):
        self.role_repository = role_repository

    # --------------------------------------------------
    # Create Role
    # --------------------------------------------------

    async def create_role(
        self,
        role_data: RoleCreate,
    ) -> Role:

        exists = await self.role_repository.exists(
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

        return await self.role_repository.create(role)

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
    ) -> Role:

        role = await self.get_role(role_id)

        update_data = role_data.model_dump(
            exclude_unset=True
        )

        if "name" in update_data:

            exists = await self.role_repository.get_by_name(
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

        for field, value in update_data.items():
            setattr(role, field, value)

        return await self.role_repository.update(role)

    # --------------------------------------------------
    # Delete Role
    # --------------------------------------------------

    async def delete_role(
        self,
        role_id: UUID,
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