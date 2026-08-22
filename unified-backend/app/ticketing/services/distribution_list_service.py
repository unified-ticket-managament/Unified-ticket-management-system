# distribution_list_service.py
#
# Admin CRUD for Distribution Lists (internal groups). Management
# (create/edit/add-remove-member/activate-deactivate) is gated on
# rule:manage — reused, not a new permission, since this is the same
# admin/org-config action as Rules management and already granted to
# the same roles (Super Admin, Site Lead, Account Manager, Team Lead).
# *Using* a Distribution List as a recipient elsewhere (Forward,
# Compose, Reply, Internal Note, Rules' forward_to) is a completely
# separate, unscoped concern — see list_active_for_recipient_picker
# and app/ticketing/api/distribution_list.py's `active` route, neither
# of which touches this permission at all.

from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.enums import ActorRole, AuditEntityType, AuditEventType
from app.ticketing.models.distribution_list import DistributionList
from app.ticketing.repositories.distribution_list_repository import (
    DistributionListRepository,
)
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.distribution_list import (
    DistributionListCreate,
    DistributionListMemberSummary,
    DistributionListRecipientCandidate,
    DistributionListResponse,
    DistributionListSummaryResponse,
    DistributionListUpdate,
)
from app.ticketing.services.access_control import AGENT_ROLE_NAMES, ensure_has_permission
from app.ticketing.services.audit_log_service import AuditLogService

DISTRIBUTION_LIST_MANAGE_PERMISSION = "rule:manage"


class DistributionListService:
    def __init__(
        self,
        repository: DistributionListRepository,
        user_repository: UserRepository,
    ):
        self.repository = repository
        self.user_repository = user_repository

    async def list_all(self, current_user: User) -> list[DistributionListSummaryResponse]:
        ensure_has_permission(current_user, DISTRIBUTION_LIST_MANAGE_PERMISSION)
        rows = await self.repository.list_with_member_counts()
        return [self._to_summary(dl, count) for dl, count in rows]

    async def list_active_for_recipient_picker(
        self,
    ) -> list[DistributionListRecipientCandidate]:
        """
        Backs GET /distribution-lists/active — every recipient picker
        in the app (Forward, Compose, Reply, Ticket Reply, Internal
        Note, Rules' forward_to action). Deliberately takes no
        `current_user`/permission check beyond the route's own
        `Depends(get_current_agent)` — this is a *usage* listing, not
        a management one, matching GET /tickets/internal-notes/
        recipients' identical "authenticated agent, nothing more" gate.
        """

        rows = await self.repository.list_active_with_member_counts()
        return [
            DistributionListRecipientCandidate(
                distribution_list_id=dl.distribution_list_id,
                name=dl.name,
                description=dl.description,
                member_count=count,
            )
            for dl, count in rows
        ]

    async def get(self, distribution_list_id: UUID, current_user: User) -> DistributionListResponse:
        ensure_has_permission(current_user, DISTRIBUTION_LIST_MANAGE_PERMISSION)
        dl = await self._get_or_404(distribution_list_id)
        members = await self.repository.list_members(distribution_list_id)
        return self._to_detail(dl, members)

    async def create(
        self, request: DistributionListCreate, current_user: User
    ) -> DistributionListResponse:
        ensure_has_permission(current_user, DISTRIBUTION_LIST_MANAGE_PERMISSION)
        await self._ensure_name_available(request.name)
        await self._ensure_all_eligible(request.member_user_ids)

        dl = await self.repository.create(
            DistributionList(
                name=request.name.strip(),
                description=request.description,
                is_active=True,
                created_by=current_user.user_id,
            )
        )
        for user_id in dict.fromkeys(request.member_user_ids):
            await self.repository.add_member(dl.distribution_list_id, user_id)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(current_user)
        await AuditLogService.log_event(
            self.repository.db,
            entity_type=AuditEntityType.DISTRIBUTION_LIST,
            entity_id=dl.distribution_list_id,
            event_type=AuditEventType.DISTRIBUTION_LIST_CREATED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={
                "name": dl.name,
                "member_user_ids": list(dict.fromkeys(request.member_user_ids)),
            },
        )

        members = await self.repository.list_members(dl.distribution_list_id)
        return self._to_detail(dl, members)

    async def update(
        self, distribution_list_id: UUID, request: DistributionListUpdate, current_user: User
    ) -> DistributionListResponse:
        ensure_has_permission(current_user, DISTRIBUTION_LIST_MANAGE_PERMISSION)
        dl = await self._get_or_404(distribution_list_id)
        await self._ensure_name_available(request.name, exclude_id=distribution_list_id)

        old_values = {"name": dl.name, "description": dl.description, "is_active": dl.is_active}
        dl.name = request.name.strip()
        dl.description = request.description
        dl.is_active = request.is_active
        saved = await self.repository.save(dl)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(current_user)
        await AuditLogService.log_event(
            self.repository.db,
            entity_type=AuditEntityType.DISTRIBUTION_LIST,
            entity_id=saved.distribution_list_id,
            event_type=(
                AuditEventType.DISTRIBUTION_LIST_DEACTIVATED
                if old_values["is_active"] and not saved.is_active
                else AuditEventType.DISTRIBUTION_LIST_UPDATED
            ),
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values=old_values,
            new_values={"name": saved.name, "description": saved.description, "is_active": saved.is_active},
        )

        members = await self.repository.list_members(distribution_list_id)
        return self._to_detail(saved, members)

    async def set_active(
        self, distribution_list_id: UUID, is_active: bool, current_user: User
    ) -> DistributionListResponse:
        ensure_has_permission(current_user, DISTRIBUTION_LIST_MANAGE_PERMISSION)
        dl = await self._get_or_404(distribution_list_id)
        was_active = dl.is_active
        dl.is_active = is_active
        saved = await self.repository.save(dl)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(current_user)
        await AuditLogService.log_event(
            self.repository.db,
            entity_type=AuditEntityType.DISTRIBUTION_LIST,
            entity_id=saved.distribution_list_id,
            event_type=(
                AuditEventType.DISTRIBUTION_LIST_DEACTIVATED
                if was_active and not is_active
                else AuditEventType.DISTRIBUTION_LIST_UPDATED
            ),
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"is_active": was_active},
            new_values={"is_active": is_active},
        )

        members = await self.repository.list_members(distribution_list_id)
        return self._to_detail(saved, members)

    async def add_member(
        self, distribution_list_id: UUID, user_id: UUID, current_user: User
    ) -> DistributionListResponse:
        ensure_has_permission(current_user, DISTRIBUTION_LIST_MANAGE_PERMISSION)
        dl = await self._get_or_404(distribution_list_id)
        await self._ensure_all_eligible([user_id])

        created = await self.repository.add_member(distribution_list_id, user_id)
        if created is not None:
            actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(current_user)
            await AuditLogService.log_event(
                self.repository.db,
                entity_type=AuditEntityType.DISTRIBUTION_LIST,
                entity_id=distribution_list_id,
                event_type=AuditEventType.DISTRIBUTION_LIST_MEMBER_ADDED,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_role=actor_role,
                new_values={"user_id": user_id},
            )

        members = await self.repository.list_members(distribution_list_id)
        return self._to_detail(dl, members)

    async def remove_member(
        self, distribution_list_id: UUID, user_id: UUID, current_user: User
    ) -> DistributionListResponse:
        ensure_has_permission(current_user, DISTRIBUTION_LIST_MANAGE_PERMISSION)
        dl = await self._get_or_404(distribution_list_id)

        removed = await self.repository.remove_member(distribution_list_id, user_id)
        if removed:
            actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(current_user)
            await AuditLogService.log_event(
                self.repository.db,
                entity_type=AuditEntityType.DISTRIBUTION_LIST,
                entity_id=distribution_list_id,
                event_type=AuditEventType.DISTRIBUTION_LIST_MEMBER_REMOVED,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_role=actor_role,
                old_values={"user_id": user_id},
            )

        members = await self.repository.list_members(distribution_list_id)
        return self._to_detail(dl, members)

    async def delete(self, distribution_list_id: UUID, current_user: User) -> None:
        ensure_has_permission(current_user, DISTRIBUTION_LIST_MANAGE_PERMISSION)
        dl = await self._get_or_404(distribution_list_id)
        await self.repository.delete(dl)

    async def _get_or_404(self, distribution_list_id: UUID) -> DistributionList:
        dl = await self.repository.get_by_id(distribution_list_id)
        if dl is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Distribution list not found.",
            )
        return dl

    async def _ensure_name_available(self, name: str, exclude_id: UUID | None = None) -> None:
        existing = await self.repository.get_by_name_case_insensitive(name, exclude_id=exclude_id)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A distribution list with this name already exists.",
            )

    async def _ensure_all_eligible(self, user_ids: list[UUID]) -> None:
        """
        Every candidate member must resolve to a real, active internal
        user (a role in AGENT_ROLE_NAMES) — the same bar Manual
        Forward's own internal-recipient validation already applies.
        No external emails as members.
        """

        for user_id in dict.fromkeys(user_ids):
            user = await self.user_repository.get_by_id(user_id)
            if (
                user is None
                or not user.is_active
                or user.role is None
                or user.role.name not in AGENT_ROLE_NAMES
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid distribution list member: {user_id}.",
                )

    @staticmethod
    def _to_summary(dl: DistributionList, member_count: int) -> DistributionListSummaryResponse:
        return DistributionListSummaryResponse(
            distribution_list_id=dl.distribution_list_id,
            name=dl.name,
            description=dl.description,
            is_active=dl.is_active,
            created_by=dl.created_by,
            member_count=member_count,
            created_at=dl.created_at,
            updated_at=dl.updated_at,
        )

    @staticmethod
    def _to_detail(dl: DistributionList, members: list[User]) -> DistributionListResponse:
        return DistributionListResponse(
            distribution_list_id=dl.distribution_list_id,
            name=dl.name,
            description=dl.description,
            is_active=dl.is_active,
            created_by=dl.created_by,
            created_at=dl.created_at,
            updated_at=dl.updated_at,
            members=[
                DistributionListMemberSummary(user_id=u.user_id, name=u.name, email=u.email)
                for u in members
            ],
        )
