import json
from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import User

from app.rbac.models.reporting_manager_team import ReportingManagerTeam
from app.rbac.repositories import CategoryRepository, ReportingManagerRepository, UserRepository
from app.rbac.schemas.audit_log import AuditLogCreate
from app.rbac.schemas.reporting_manager import ReportingManagerAssign, ReportingManagerResponse
from app.rbac.services.access_control import has_permission
from app.rbac.services.audit_log_service import AuditLogService

ACCOUNT_MANAGER_ROLE_NAME = "Account Manager"
MANAGE_REPORTING_MANAGERS_PERMISSION = "org:manage_reporting_managers"


def _to_response(row) -> ReportingManagerResponse:
    mapping: ReportingManagerTeam = row[0]

    return ReportingManagerResponse(
        id=mapping.id,
        account_manager_id=mapping.account_manager_id,
        account_manager_name=row.account_manager_name,
        category_id=mapping.category_id,
        category_name=row.category_name,
        assigned_by=mapping.assigned_by,
        assigned_by_name=row.assigned_by_name,
        assigned_at=mapping.assigned_at,
    )


class ReportingManagerService:
    """
    Business logic for the "Reporting Manager" mapping — an additional
    HR/people-management responsibility layered onto an existing
    Account Manager, scoped to one or more business categories (see
    ReportingManagerTeam's own docstring, and root CLAUDE.md's
    "Organization Structure" section for the full business rule this
    implements). Deliberately does not touch `User.manager_id`/
    `teamlead_id` or ticket-assignment scope — those stay exactly as
    they already are.

    Authorization: `org:manage_reporting_managers` remains the broad
    administrative permission (Super Admin/Site Lead by default) that
    can manage ANY Account Manager's mapping — unchanged. Layered on
    top of it, `ensure_can_manage_mapping` also lets an Account Manager
    manage their own mapping without holding that permission — a
    self-service capability generic to the role and the actor's own
    identity, never a name/email/hardcoded id.
    """

    def __init__(
        self,
        reporting_manager_repository: ReportingManagerRepository,
        user_repository: UserRepository,
        category_repository: CategoryRepository,
        audit_log_service: AuditLogService,
    ):
        self.reporting_manager_repository = reporting_manager_repository
        self.user_repository = user_repository
        self.category_repository = category_repository
        self.audit_log_service = audit_log_service

    def ensure_can_manage_mapping(
        self,
        actor: User,
        target_account_manager_id: UUID,
    ) -> None:
        """
        403s unless `actor` may create/revoke a Reporting Manager
        mapping for `target_account_manager_id`. Two independent
        paths: broad administrative authority
        (`org:manage_reporting_managers`), or Account Manager
        self-service — the actor IS the Account Manager the mapping is
        for. Never authorizes one Account Manager to manage another
        AM's mapping.
        """

        if has_permission(actor, MANAGE_REPORTING_MANAGERS_PERMISSION):
            return

        if (
            actor.role.name == ACCOUNT_MANAGER_ROLE_NAME
            and actor.user_id == target_account_manager_id
        ):
            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You are not permitted to manage this Account Manager's "
                "Reporting Manager assignments."
            ),
        )

    async def list_visible(
        self,
        actor: User,
        account_manager_id: UUID | None = None,
        category_id: UUID | None = None,
    ) -> list[ReportingManagerResponse]:
        """
        Read-side counterpart to ensure_can_manage_mapping. A holder of
        `org:manage_reporting_managers` sees the same unrestricted,
        optionally-filtered view as before. An Account Manager without
        that permission is scoped to their own mappings only —
        filtered further to `category_id` when supplied, so a
        self-service AM asking "who's Reporting Manager for category
        X" only ever learns whether THEY are, never another AM's
        mapping. Anyone else is denied.
        """

        if has_permission(actor, MANAGE_REPORTING_MANAGERS_PERMISSION):
            if category_id is not None:
                return await self.list_by_category(category_id)
            if account_manager_id is not None:
                return await self.list_by_account_manager(account_manager_id)
            return await self.list_all()

        if actor.role.name == ACCOUNT_MANAGER_ROLE_NAME:
            own = await self.list_by_account_manager(actor.user_id)
            if category_id is not None:
                own = [row for row in own if row.category_id == category_id]
            return own

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {MANAGE_REPORTING_MANAGERS_PERMISSION}",
        )

    async def assign(
        self,
        data: ReportingManagerAssign,
        actor: User,
    ) -> ReportingManagerResponse:

        self.ensure_can_manage_mapping(actor, data.account_manager_id)

        account_manager = await self.user_repository.get_by_id(data.account_manager_id)

        if account_manager is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account Manager not found.",
            )

        if account_manager.role.name != ACCOUNT_MANAGER_ROLE_NAME:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reporting Manager responsibility can only be assigned to a user holding the Account Manager role.",
            )

        category = await self.category_repository.get_by_id(data.category_id)

        if category is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found.",
            )

        if await self.reporting_manager_repository.exists(
            data.account_manager_id, data.category_id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This Account Manager is already the Reporting Manager for this category.",
            )

        mapping = ReportingManagerTeam(
            account_manager_id=data.account_manager_id,
            category_id=data.category_id,
            assigned_by=actor.user_id,
        )

        mapping = await self.reporting_manager_repository.create(mapping)

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id,
                action="reporting_manager.assigned",
                entity_type="reporting_manager_team",
                entity_id=str(mapping.id),
                new_value=json.dumps(
                    {
                        "account_manager_id": str(data.account_manager_id),
                        "category_id": str(data.category_id),
                    }
                ),
            )
        )

        row = await self.reporting_manager_repository.get_by_id(mapping.id)
        return _to_response(row)

    async def list_all(self) -> list[ReportingManagerResponse]:
        rows = await self.reporting_manager_repository.list_all()
        return [_to_response(row) for row in rows]

    async def list_by_account_manager(
        self, account_manager_id: UUID
    ) -> list[ReportingManagerResponse]:
        rows = await self.reporting_manager_repository.list_by_account_manager(
            account_manager_id
        )
        return [_to_response(row) for row in rows]

    async def list_by_category(self, category_id: UUID) -> list[ReportingManagerResponse]:
        rows = await self.reporting_manager_repository.list_by_category(category_id)
        return [_to_response(row) for row in rows]

    async def revoke(self, mapping_id: UUID, actor: User) -> None:
        row = await self.reporting_manager_repository.get_by_id(mapping_id)

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reporting Manager assignment not found.",
            )

        mapping: ReportingManagerTeam = row[0]
        self.ensure_can_manage_mapping(actor, mapping.account_manager_id)

        old_value = json.dumps(
            {
                "account_manager_id": str(mapping.account_manager_id),
                "category_id": str(mapping.category_id),
            }
        )

        await self.reporting_manager_repository.delete(mapping)

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id,
                action="reporting_manager.revoked",
                entity_type="reporting_manager_team",
                entity_id=str(mapping_id),
                old_value=old_value,
            )
        )
