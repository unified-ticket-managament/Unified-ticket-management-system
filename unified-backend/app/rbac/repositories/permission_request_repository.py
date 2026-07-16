from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.rbac.models.permission_request import PermissionRequest, PermissionRequestStatus

from .base import BaseRepository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PermissionRequestRepository(BaseRepository):
    """
    Repository for permission-request database operations.
    """

    async def create(
        self,
        request: PermissionRequest,
    ) -> PermissionRequest:

        self.db.add(request)

        await self.db.flush()
        await self.db.refresh(request, attribute_names=["permission"])

        return request

    async def get_by_id(
        self,
        request_id: UUID,
    ) -> PermissionRequest | None:

        result = await self.db.execute(
            select(PermissionRequest)
            .options(
                selectinload(PermissionRequest.permission),
                selectinload(PermissionRequest.granted_override),
            )
            .where(PermissionRequest.request_id == request_id)
        )

        return result.scalar_one_or_none()

    async def get_pending_by_requester_permission_and_scope(
        self,
        requester_id: UUID,
        permission_id: UUID,
        scope_ticket_id: UUID | None,
    ) -> PermissionRequest | None:
        """Matches the DB's own pending-uniqueness index exactly (same
        requester+permission+ticket-scope triple) — a requester may
        hold two concurrently-PENDING requests for the same permission
        as long as they're scoped to different tickets."""

        result = await self.db.execute(
            select(PermissionRequest).where(
                PermissionRequest.requester_id == requester_id,
                PermissionRequest.permission_id == permission_id,
                PermissionRequest.scope_ticket_id == scope_ticket_id,
                PermissionRequest.status == PermissionRequestStatus.PENDING,
            )
        )

        return result.scalar_one_or_none()

    async def list_by_requester(
        self,
        requester_id: UUID,
    ) -> list[PermissionRequest]:

        result = await self.db.execute(
            select(PermissionRequest)
            .options(
                selectinload(PermissionRequest.permission),
                selectinload(PermissionRequest.granted_override),
            )
            .where(PermissionRequest.requester_id == requester_id)
            .order_by(PermissionRequest.created_at.desc())
        )

        return list(result.scalars().all())

    async def list_pending_for_approver(
        self,
        selected_approver_id: UUID,
    ) -> list[PermissionRequest]:
        """
        Strictly PENDING requests where this exact user is the one
        selected in the "Request To" dropdown — the entire visibility
        rule for "Pending My Review" is this one column match, no role
        or subordinate-scoping logic layered on top: only the person
        actually picked ever sees or can act on a request.
        """

        result = await self.db.execute(
            select(PermissionRequest)
            .options(selectinload(PermissionRequest.permission))
            .where(
                PermissionRequest.status == PermissionRequestStatus.PENDING,
                PermissionRequest.selected_approver_id == selected_approver_id,
            )
            .order_by(PermissionRequest.created_at.asc())
        )

        return list(result.scalars().all())

    async def list_history(self) -> list[PermissionRequest]:
        """
        Every request that has left PENDING — APPROVED, REJECTED, or
        REVOKED — regardless of who it was addressed to. This is the
        raw, unscoped set; PermissionRequestService.list_history
        narrows it per-viewer (oversight scoping, same rule the old
        role-based review queue used) before returning it, since
        "history" is a broader oversight view than the strict
        point-to-point Pending queue.
        """

        result = await self.db.execute(
            select(PermissionRequest)
            .options(selectinload(PermissionRequest.permission))
            .where(
                PermissionRequest.status.in_(
                    [
                        PermissionRequestStatus.APPROVED,
                        PermissionRequestStatus.REJECTED,
                        PermissionRequestStatus.REVOKED,
                    ]
                )
            )
            .order_by(PermissionRequest.reviewed_at.desc())
        )

        return list(result.scalars().all())

    async def approve(
        self,
        request: PermissionRequest,
        reviewed_by: UUID,
        review_comment: str | None,
        expires_at: datetime | None,
        granted_override_id: UUID,
    ) -> PermissionRequest:

        request.status = PermissionRequestStatus.APPROVED
        request.reviewed_by = reviewed_by
        request.reviewed_at = utc_now()
        request.review_comment = review_comment
        request.expires_at = expires_at
        request.granted_override_id = granted_override_id

        await self.db.flush()
        await self.db.refresh(request)

        return request

    async def reject(
        self,
        request: PermissionRequest,
        reviewed_by: UUID,
        review_comment: str | None,
    ) -> PermissionRequest:

        request.status = PermissionRequestStatus.REJECTED
        request.reviewed_by = reviewed_by
        request.reviewed_at = utc_now()
        request.review_comment = review_comment

        await self.db.flush()
        await self.db.refresh(request)

        return request

    async def revoke(
        self,
        request: PermissionRequest,
        revoked_by: UUID,
        revoke_reason: str | None,
    ) -> PermissionRequest:
        """Marks an APPROVED request REVOKED — never deletes the row,
        preserving it for audit/history per the request's own docstring."""

        request.status = PermissionRequestStatus.REVOKED
        request.revoked_by = revoked_by
        request.revoked_at = utc_now()
        request.revoke_reason = revoke_reason

        await self.db.flush()
        await self.db.refresh(request)

        return request
