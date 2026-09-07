import json
from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import Category, User

from app.rbac.repositories import CategoryRepository, ReportingManagerRepository, UserRepository
from app.rbac.schemas.audit_log import AuditLogCreate
from app.rbac.schemas.category import (
    CategoryCreate,
    CategoryMemberResponse,
    CategoryUpdate,
)
from app.rbac.services.audit_log_service import AuditLogService
from app.ticketing.repositories.client_repository import ClientRepository


class CategoryService:
    """
    Business logic for Category operations — a work-specialization
    category is created dynamically at runtime (no fixed enum backing
    it — see shared_models.models.Category), optionally with Staff/
    Team Lead users assigned to it at creation time.
    """

    def __init__(
        self,
        category_repository: CategoryRepository,
        user_repository: UserRepository,
        reporting_manager_repository: ReportingManagerRepository,
        audit_log_service: AuditLogService,
        client_repository: ClientRepository | None = None,
    ):
        self.category_repository = category_repository
        self.user_repository = user_repository
        # Used by delete_category's pre-delete guard — a category with
        # an active Account Manager Reporting Manager mapping must not
        # be silently cascade-deleted (see reporting_manager_teams'
        # ON DELETE CASCADE FK).
        self.reporting_manager_repository = reporting_manager_repository
        self.audit_log_service = audit_log_service
        # Optional — only needed for the inbox_email cross-table
        # uniqueness check below, mirrors this codebase's existing
        # optional-dependency convention (e.g. EmailService's own
        # None-safe collaborators).
        self.client_repository = client_repository

    async def _normalize_and_validate_inbox_email(
        self, inbox_email: str | None, *, category_id: UUID | None = None
    ) -> str | None:
        """
        Normalizes a submitted CATEGORY mailbox address and enforces
        that it never collides with an existing CATEGORY mailbox (a
        different category) or an ACTIVE CLIENT's mailbox
        (Client.inbox_email) — keeping the two kinds of shared inbox
        mutually exclusive by construction, never inferred from the
        address string itself at mail-arrival time. Only active
        clients block a category mailbox: a client deactivated after
        its email was mistakenly used (e.g. a shared-mailbox address
        accidentally entered as a client's email) must not permanently
        block that address from ever being used as a category mailbox
        going forward — see get_active_by_inbox_email's own docstring.
        """

        if inbox_email is None:
            return None

        normalized = inbox_email.strip().lower()
        if not normalized:
            return None

        existing_category = await self.category_repository.get_active_by_inbox_email(
            normalized
        )
        if existing_category is not None and existing_category.category_id != category_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This address is already configured as a category mailbox.",
            )

        if self.client_repository is not None:
            active_client = await self.client_repository.get_active_by_inbox_email(
                normalized
            )
            if active_client is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "This shared mailbox is already associated with an active "
                        "client and cannot be assigned to a category. Please use a "
                        "different mailbox."
                    ),
                )

        return normalized

    # --------------------------------------------------
    # Create Category
    # --------------------------------------------------

    async def create_category(
        self,
        category_data: CategoryCreate,
        actor: User | None = None,
    ) -> Category:

        name = category_data.category_name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category name is required.",
            )

        exists = await self.category_repository.exists(name)

        if exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category already exists.",
            )

        inbox_email = await self._normalize_and_validate_inbox_email(
            category_data.inbox_email
        )

        # Assigning users is optional — an empty/omitted user_ids is a
        # normal, valid case (a category with zero members). Ids that
        # ARE submitted must resolve to real users, never trusted
        # blindly from the frontend.
        user_ids = list(dict.fromkeys(category_data.user_ids))
        if user_ids:
            found_users = await self.user_repository.get_by_ids(user_ids)
            if len(found_users) != len(user_ids):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="One or more users were not found.",
                )

        category = Category(category_name=name, inbox_email=inbox_email)
        category = await self.category_repository.create(category)

        await self.user_repository.add_users_to_category(
            category.category_id,
            user_ids,
            assigned_by=actor.user_id if actor else None,
        )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="category.create",
                entity_type="category",
                entity_id=str(category.category_id),
                new_value=json.dumps(
                    {"category_name": name, "inbox_email": inbox_email}
                ),
            )
        )

        category.assigned_user_count = len(user_ids)
        return category

    # --------------------------------------------------
    # Get Category
    # --------------------------------------------------

    async def get_category(
        self,
        category_id: UUID,
    ) -> Category:

        category = await self.category_repository.get_by_id(
            category_id
        )

        if category is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found.",
            )

        member_count = await self.category_repository.get_users_count(
            category.category_id
        )
        am_ids = await self.reporting_manager_repository.list_account_manager_ids_by_category(
            category.category_id
        )
        category.assigned_user_count = member_count + len(set(am_ids))

        return category

    async def list_categories(
        self,
        page: int = 1,
        page_size: int = 10,
    ):
        categories, total = await self.category_repository.get_all(
            page,
            page_size,
        )

        category_ids = [category.category_id for category in categories]
        counts = await self.category_repository.get_counts_by_category_ids(category_ids)
        # Reporting-Manager-mapped Account Managers aren't in
        # user_categories, so they'd otherwise be invisible in the
        # "Assigned Users" column despite being genuinely assigned to
        # the category.
        am_counts = await self.reporting_manager_repository.get_counts_by_category_ids(
            category_ids
        )
        for category in categories:
            category.assigned_user_count = counts.get(
                category.category_id, 0
            ) + am_counts.get(category.category_id, 0)

        return categories, total

    # --------------------------------------------------
    # Update Category
    # --------------------------------------------------

    async def update_category(
        self,
        category_id: UUID,
        category_data: CategoryUpdate,
        actor: User | None = None,
    ) -> Category:

        category = await self.get_category(category_id)

        update_data = category_data.model_dump(
            exclude_unset=True
        )

        # Snapshot only the fields actually being changed, before
        # they're overwritten below — mirrors UserService.update_user's
        # "diff of just the changed fields" audit convention.
        old_values = {field: getattr(category, field) for field in update_data}

        if "category_name" in update_data:
            name = (update_data["category_name"] or "").strip()
            if not name:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Category name is required.",
                )

            exists = await self.category_repository.get_by_name(name)

            if (
                exists
                and exists.category_id != category.category_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Category already exists.",
                )

            update_data["category_name"] = name

        if "inbox_email" in update_data:
            update_data["inbox_email"] = await self._normalize_and_validate_inbox_email(
                update_data["inbox_email"], category_id=category.category_id
            )

        for field, value in update_data.items():
            setattr(category, field, value)

        # category.assigned_user_count was already computed by the
        # get_category() call above — membership isn't touched by a
        # rename, so it's still accurate; no need to re-query.
        assigned_user_count = category.assigned_user_count
        updated = await self.category_repository.update(category)
        updated.assigned_user_count = assigned_user_count

        new_values = {field: update_data[field] for field in old_values}
        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="category.update",
                entity_type="category",
                entity_id=str(category_id),
                old_value=json.dumps(old_values, default=str),
                new_value=json.dumps(new_values, default=str),
            )
        )

        return updated

    # --------------------------------------------------
    # Category Members (Edit Category — add/remove Team Leads/Staff)
    # --------------------------------------------------

    async def get_members(
        self,
        category_id: UUID,
    ) -> list[CategoryMemberResponse]:

        # 404s if the category doesn't exist, same as every other
        # category_id-taking method here.
        await self.get_category(category_id)

        rows = await self.category_repository.get_members(category_id)

        return [
            CategoryMemberResponse(
                user_id=user_id, name=name, email=email, role_name=role_name
            )
            for user_id, name, email, role_name in rows
        ]

    async def set_members(
        self,
        category_id: UUID,
        user_ids: list[UUID],
        actor: User | None = None,
    ) -> list[CategoryMemberResponse]:
        """
        Full-replace this category's membership set — diffs the
        submitted `user_ids` against who's currently assigned and
        adds/removes only the difference, mirroring
        UserService.set_user_categories's own full-replace semantics
        but scoped to one category instead of one user. Submitted ids
        are validated to exist first, same as create_category.
        """

        await self.get_category(category_id)

        new_ids = set(dict.fromkeys(user_ids))
        if new_ids:
            found_users = await self.user_repository.get_by_ids(list(new_ids))
            if len(found_users) != len(new_ids):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="One or more users were not found.",
                )

        current_rows = await self.category_repository.get_members(category_id)
        current_ids = {user_id for user_id, _, _, _ in current_rows}

        to_add = list(new_ids - current_ids)
        to_remove = list(current_ids - new_ids)

        if to_add:
            await self.user_repository.add_users_to_category(category_id, to_add)
        if to_remove:
            await self.user_repository.remove_users_from_category(
                category_id, to_remove
            )

        if to_add or to_remove:
            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="category.members_set",
                    entity_type="category",
                    entity_id=str(category_id),
                    new_value=json.dumps(
                        {
                            "added": [str(i) for i in to_add],
                            "removed": [str(i) for i in to_remove],
                        }
                    ),
                )
            )

        return await self.get_members(category_id)

    # --------------------------------------------------
    # Delete Category
    # --------------------------------------------------

    async def delete_category(
        self,
        category_id: UUID,
        actor: User | None = None,
    ):

        category = await self.get_category(category_id)

        # reporting_manager_teams.category_id is ON DELETE CASCADE —
        # without this check, deleting a category would silently wipe
        # out any Account Manager's active Reporting Manager mapping
        # to it with no warning and no audit trail. Checked before the
        # generic member-count guard below so this more specific
        # message wins even though assigned_user_count (get_category()
        # above) now folds the mapped Account Manager(s) into the same
        # total.
        reporting_manager_ids = (
            await self.reporting_manager_repository.list_account_manager_ids_by_category(
                category_id
            )
        )
        if reporting_manager_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Category cannot be deleted because it has an active "
                    "Reporting Manager assignment."
                ),
            )

        # get_category() above already computed this.
        user_count = category.assigned_user_count

        if user_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category cannot be deleted because it is assigned to users.",
            )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="category.delete",
                entity_type="category",
                entity_id=str(category_id),
                old_value=json.dumps({"category_name": category.category_name}),
            )
        )

        await self.category_repository.delete(category)
