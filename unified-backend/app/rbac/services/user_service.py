import json
from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import User

from app.auth.password import get_password_hash
from app.rbac.repositories import CategoryRepository, RoleRepository, UserRepository
from app.rbac.schemas.audit_log import AuditLogCreate
from app.rbac.schemas.user import UserCreate, UserUpdate
from app.rbac.services.audit_log_service import AuditLogService

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
        audit_log_service: AuditLogService,
    ):
        self.user_repository = user_repository
        self.role_repository = role_repository
        self.category_repository = category_repository
        self.audit_log_service = audit_log_service

    # --------------------------------------------------
    # Create User
    # --------------------------------------------------

    async def create_user(
            self,
            user_data: UserCreate,
            actor: User | None = None,
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

        # Validate manager/team-lead — see _validate_manager_and_teamlead's
        # own docstring for why existence alone (the old check here)
        # isn't enough to keep the Organization Structure's reporting
        # shape intact.
        await self._validate_manager_and_teamlead(
            role.name,
            user_data.manager_id,
            user_data.teamlead_id,
            user_data.category_id,
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

        user = await self.user_repository.create(user)

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="user.create",
                entity_type="user",
                entity_id=str(user.user_id),
                new_value=json.dumps(
                    {"name": user.name, "email": user.email, "role_id": str(user.role_id)}
                ),
            )
        )

        return user

    # --------------------------------------------------
    # Reporting-line validation
    # --------------------------------------------------

    async def _validate_manager_and_teamlead(
        self,
        role_name: str,
        manager_id: UUID | None,
        teamlead_id: UUID | None,
        category_id: UUID | None,
    ) -> None:
        """
        Enforces the Organization Structure's reporting shape (see root
        CLAUDE.md): Super Admin > Site Lead > Account Manager > Team
        Lead > Staff. manager_id/teamlead_id previously only checked
        that the referenced user existed at all — nothing stopped a
        Staff member's teamlead_id from pointing at another Staff
        member, or a Team Lead's manager_id from pointing at a
        different Team Lead.
        """

        if manager_id is not None:
            manager = await self.user_repository.get_by_id(manager_id)

            if manager is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Manager not found.",
                )

            # An Account Manager's own manager (if ever set — it's
            # usually left null, falling back to the first Super Admin,
            # see OrganizationService._get_parent) sits one level up at
            # Site Lead/Super Admin; every other role's manager_id is
            # the Account Manager one level up from it.
            expected_roles = (
                {"Site Lead", "Super Admin"}
                if role_name == "Account Manager"
                else {"Account Manager"}
            )

            if manager.role.name not in expected_roles:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "manager_id must reference a user holding one of "
                        f"these roles: {', '.join(sorted(expected_roles))}."
                    ),
                )

        if teamlead_id is not None:
            teamlead = await self.user_repository.get_by_id(teamlead_id)

            if teamlead is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Team Lead not found.",
                )

            if teamlead.role.name != "Team Lead":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="teamlead_id must reference a user holding the Team Lead role.",
                )

            # Every Staff member belongs to exactly one Team Lead, and
            # a Team Lead owns exactly one business category — so the
            # Staff member's own category must match theirs. A Team
            # Lead with no category assigned yet (shouldn't normally
            # happen — category is required for that role — but could
            # exist on old data) doesn't block this, since there's
            # nothing to mismatch against.
            if (
                category_id is not None
                and teamlead.category_id is not None
                and teamlead.category_id != category_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The assigned Team Lead's category must match this user's own category.",
                )

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
        actor: User | None = None,
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
        new_role = None
        if "role_id" in update_data:

            new_role = await self.role_repository.get_by_id(
                update_data["role_id"]
            )

            if new_role is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Role not found.",
                )

        # Reporting-line validation — re-runs whenever any field that
        # affects the check's own inputs is touched (not just when
        # manager_id/teamlead_id themselves change), e.g. changing
        # category_id alone must still be checked against an existing
        # teamlead_id. Falls back to the user's current value for
        # anything not present in this particular update.
        if update_data.keys() & {"role_id", "category_id", "manager_id", "teamlead_id"}:
            effective_role_name = new_role.name if new_role is not None else user.role.name
            effective_manager_id = update_data.get("manager_id", user.manager_id)
            effective_teamlead_id = update_data.get("teamlead_id", user.teamlead_id)
            effective_category_id = update_data.get("category_id", user.category_id)

            await self._validate_manager_and_teamlead(
                effective_role_name,
                effective_manager_id,
                effective_teamlead_id,
                effective_category_id,
            )

        old_values = {
            field: (str(getattr(user, field)) if getattr(user, field) is not None else None)
            for field in update_data
        }
        old_role_id = user.role_id
        old_is_active = user.is_active

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

        user = await self.user_repository.update(user)

        if update_data:
            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="user.update",
                    entity_type="user",
                    entity_id=str(user.user_id),
                    old_value=json.dumps(old_values),
                    new_value=json.dumps(
                        {k: (str(v) if v is not None else None) for k, v in update_data.items()}
                    ),
                )
            )

        # "Role Changed" is logged as its own distinct action in
        # addition to the generic user.update row above — same
        # mutation, but callers that only care about role history
        # (not every profile-field edit) can filter on this action
        # name instead of parsing old_value/new_value.
        if "role_id" in update_data and str(old_role_id) != str(update_data["role_id"]):
            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="user.role_changed",
                    entity_type="user",
                    entity_id=str(user.user_id),
                    old_value=json.dumps({"role_id": str(old_role_id)}),
                    new_value=json.dumps({"role_id": str(update_data["role_id"])}),
                )
            )

        # Same reasoning as role_changed above — is_active can also be
        # toggled through this generic update path (not only the
        # dedicated activate/deactivate endpoints below), so it gets
        # its own named action here too.
        if "is_active" in update_data and bool(old_is_active) != bool(update_data["is_active"]):
            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="user.activate" if update_data["is_active"] else "user.deactivate",
                    entity_type="user",
                    entity_id=str(user.user_id),
                )
            )

        return user

    # --------------------------------------------------
    # Delete User
    # --------------------------------------------------

    async def delete_user(
        self,
        user_id: UUID,
        actor: User | None = None,
    ):

        user = await self.get_user(user_id)

        await self.user_repository.delete(user)

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="user.delete",
                entity_type="user",
                entity_id=str(user_id),
                old_value=json.dumps({"name": user.name, "email": user.email}),
            )
        )

    # --------------------------------------------------
    # Activate
    # --------------------------------------------------

    async def activate_user(
        self,
        user_id: UUID,
        actor: User | None = None,
    ) -> User:

        user = await self.get_user(user_id)
        user.permission_version += 1

        user = await self.user_repository.activate(
            user
        )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="user.activate",
                entity_type="user",
                entity_id=str(user.user_id),
            )
        )

        return user

    # --------------------------------------------------
    # Deactivate
    # --------------------------------------------------

    async def deactivate_user(
        self,
        user_id: UUID,
        actor: User | None = None,
    ) -> User:

        user = await self.get_user(user_id)
        user.permission_version += 1

        user = await self.user_repository.deactivate(
            user
        )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="user.deactivate",
                entity_type="user",
                entity_id=str(user.user_id),
            )
        )

        return user