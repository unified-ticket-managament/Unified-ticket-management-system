from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import User

from app.auth.password import get_password_hash
from app.rbac.repositories import CategoryRepository, RoleRepository, UserRepository
from app.rbac.schemas.user import UserCreate, UserUpdate

# Roles required to belong to a work-specialization category — see
# shared_models.models.Category. Not imported from a shared constant
# because RBAC's role-name literals live only in the frontend's
# role-access.ts today; keep this set in sync with it by hand.
CATEGORY_REQUIRED_ROLE_NAMES = {"Staff", "Team Lead"}

# Fields whose change should invalidate any already-issued session's
# cached RBAC state (see User.permission_version's own docstring and
# app/core/rbac_cache.py) — role/category/reporting-line reassignment
# all change what a user is authorized to do or see. `name`/`email`
# are deliberately excluded: cosmetic, not authorization-relevant, and
# already accepted as "stale until next token refresh" the same way
# permissions/scoped_permissions are.
_RBAC_RELEVANT_FIELDS = {"role_id", "category_id", "manager_id", "teamlead_id"}


class UserService:
    """
    Business logic for User operations.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        category_repository: CategoryRepository,
    ):
        self.user_repository = user_repository
        self.role_repository = role_repository
        self.category_repository = category_repository

    # --------------------------------------------------
    # Create User
    # --------------------------------------------------

    async def create_user(
            self,
            user_data: UserCreate,
        ) -> User:

        # Check email already exists
        if await self.user_repository.exists(user_data.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists.",
            )

        # Check role exists
        role = await self.role_repository.get_by_id(
            user_data.role_id
        )

        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found.",
            )

        # Validate manager
        if user_data.manager_id is not None:

            manager = await self.user_repository.get_by_id(
                user_data.manager_id
            )

            if manager is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Manager not found.",
                )

        # Validate team lead
        if user_data.teamlead_id is not None:

            teamlead = await self.user_repository.get_by_id(
                user_data.teamlead_id
            )

            if teamlead is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Team Lead not found.",
                )

        # Staff/Team Lead must belong to a work-specialization
        # category; every other role leaves it unset.
        if role.name in CATEGORY_REQUIRED_ROLE_NAMES and user_data.category_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category is required for Staff and Team Lead users.",
            )

        if user_data.category_id is not None:

            category = await self.category_repository.get_by_id(
                user_data.category_id
            )

            if category is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Category not found.",
                )

        user = User(
            name=user_data.name,
            email=user_data.email,
            password_hash=get_password_hash(
                user_data.password
            ),
            role_id=user_data.role_id,
            manager_id=user_data.manager_id,
            teamlead_id=user_data.teamlead_id,
            category_id=user_data.category_id,
            is_active=user_data.is_active,
        )

        return await self.user_repository.create(user)

    # --------------------------------------------------
    # Get User
    # --------------------------------------------------

    async def get_user(
        self,
        user_id: UUID,
    ) -> User:

        user = await self.user_repository.get_by_id(
            user_id
        )

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        return user

    async def get_user_by_email(
        self,
        email: str,
    ) -> User:

        user = await self.user_repository.get_by_email(
            email
        )

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        return user

    async def list_users(
        self,
        page: int = 1,
        page_size: int = 10,
        search: str | None = None,
        category_id: UUID | None = None,
    ):

        return await self.user_repository.get_all(
            page,
            page_size,
            search,
            category_id,
        )

    # --------------------------------------------------
    # Update User
    # --------------------------------------------------

    async def update_user(
        self,
        user_id: UUID,
        user_data: UserUpdate,
    ) -> User:

        user = await self.get_user(user_id)

        update_data = user_data.model_dump(
            exclude_unset=True
        )

        # Email validation
        if "email" in update_data:

            existing = await self.user_repository.get_by_email(
                update_data["email"]
            )

            if (
                existing
                and existing.user_id != user.user_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already exists.",
                )

        # Role validation
        if "role_id" in update_data:

            role = await self.role_repository.get_by_id(
                update_data["role_id"]
            )

            if role is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Role not found.",
                )

        for field, value in update_data.items():
            setattr(user, field, value)

        # Any of these change what this user is authorized to do or
        # see — bump so a session already in flight with the old
        # value baked into its JWT gets rejected on its next DB-
        # verified request instead of trusting a stale role/category
        # for the rest of the token's natural TTL. See
        # app/core/rbac_cache.py's module docstring.
        if _RBAC_RELEVANT_FIELDS.intersection(update_data.keys()):
            user.permission_version += 1

        return await self.user_repository.update(user)

    # --------------------------------------------------
    # Delete User
    # --------------------------------------------------

    async def delete_user(
        self,
        user_id: UUID,
    ):

        user = await self.get_user(user_id)

        await self.user_repository.delete(user)

    # --------------------------------------------------
    # Activate
    # --------------------------------------------------

    async def activate_user(
        self,
        user_id: UUID,
    ) -> User:

        user = await self.get_user(user_id)
        user.permission_version += 1

        return await self.user_repository.activate(
            user
        )

    # --------------------------------------------------
    # Deactivate
    # --------------------------------------------------

    async def deactivate_user(
        self,
        user_id: UUID,
    ) -> User:

        user = await self.get_user(user_id)
        user.permission_version += 1

        return await self.user_repository.deactivate(
            user
        )