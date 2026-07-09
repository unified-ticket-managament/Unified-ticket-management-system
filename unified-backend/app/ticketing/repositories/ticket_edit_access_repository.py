from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.enums import EditAccessStatus
from app.ticketing.models.ticket_edit_access_request import TicketEditAccessRequest


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TicketEditAccessRequestRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, request: TicketEditAccessRequest) -> TicketEditAccessRequest:
        self.db.add(request)
        await self.db.flush()
        await self.db.refresh(request)

        return request

    async def get_by_id(self, request_id: UUID) -> TicketEditAccessRequest | None:
        result = await self.db.execute(
            select(TicketEditAccessRequest).where(
                TicketEditAccessRequest.request_id == request_id
            )
        )

        return result.scalar_one_or_none()

    async def get_pending_by_ticket_and_user(
        self,
        ticket_id: UUID,
        user_id: UUID,
    ) -> TicketEditAccessRequest | None:
        result = await self.db.execute(
            select(TicketEditAccessRequest).where(
                TicketEditAccessRequest.ticket_id == ticket_id,
                TicketEditAccessRequest.requested_by == user_id,
                TicketEditAccessRequest.status == EditAccessStatus.PENDING,
            )
        )

        return result.scalar_one_or_none()

    async def has_active_grant(self, ticket_id: UUID, user_id: UUID) -> bool:
        """
        True if this user has an approved, not-yet-expired edit-access
        grant on this ticket — the bypass check
        ensure_agent_can_act_on_ticket consults for anyone who isn't
        the assigned agent and doesn't hold ticket:edit_ticket outright.
        """

        now = utc_now()

        result = await self.db.execute(
            select(TicketEditAccessRequest.request_id).where(
                TicketEditAccessRequest.ticket_id == ticket_id,
                TicketEditAccessRequest.requested_by == user_id,
                TicketEditAccessRequest.status == EditAccessStatus.APPROVED,
                or_(
                    TicketEditAccessRequest.expires_at.is_(None),
                    TicketEditAccessRequest.expires_at > now,
                ),
            )
        )

        return result.scalar_one_or_none() is not None

    async def list_by_ticket(self, ticket_id: UUID) -> list[TicketEditAccessRequest]:
        result = await self.db.execute(
            select(TicketEditAccessRequest)
            .where(TicketEditAccessRequest.ticket_id == ticket_id)
            .order_by(TicketEditAccessRequest.created_at.desc())
        )

        return list(result.scalars().all())

    async def approve(
        self,
        request: TicketEditAccessRequest,
        reviewed_by: UUID,
        expires_at: datetime | None,
        review_note: str | None,
    ) -> TicketEditAccessRequest:
        request.status = EditAccessStatus.APPROVED
        request.reviewed_by = reviewed_by
        request.reviewed_at = utc_now()
        request.expires_at = expires_at
        request.review_note = review_note

        await self.db.flush()
        await self.db.refresh(request)

        return request

    async def reject(
        self,
        request: TicketEditAccessRequest,
        reviewed_by: UUID,
        review_note: str | None,
    ) -> TicketEditAccessRequest:
        request.status = EditAccessStatus.REJECTED
        request.reviewed_by = reviewed_by
        request.reviewed_at = utc_now()
        request.review_note = review_note

        await self.db.flush()
        await self.db.refresh(request)

        return request
