from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.enums import (
    AuditEntityType,
    AuditEventType,
    EditAccessStatus,
    InteractionDirection,
    InteractionStatus,
)
from app.models.ticket_edit_access_request import TicketEditAccessRequest
from app.repositories.interaction_repository import InteractionRepository
from app.repositories.ticket_edit_access_repository import (
    TicketEditAccessRequestRepository,
)
from app.repositories.ticket_repository import TicketRepository
from app.repositories.user_repository import UserRepository
from app.schemas.edit_access import (
    EditAccessApproveRequest,
    EditAccessRejectRequest,
    EditAccessRequestCreate,
    EditAccessRequestResponse,
)
from app.schemas.interaction import InteractionCreate
from app.services.access_control import (
    SUPERVISOR_ROLE_NAMES,
    ensure_agent_can_view_ticket,
    ensure_can_review_edit_access,
    ensure_ticket_not_closed,
    has_permission,
)
from app.services.audit_log_service import AuditLogService


class EditAccessService:
    """
    Business logic for the per-ticket edit-access request/approve/
    reject workflow — letting someone who isn't the assigned agent
    (and doesn't already hold ticket:edit_ticket) work one specific
    ticket, once someone who does hold it approves. Every transition
    is recorded twice: on the ticket's own Interaction timeline (the
    "personal"/business record agents read day to day) and in the
    central AuditLog (the compliance-grade record) — see CLAUDE.md's
    "Interaction vs. AuditLog" note for why these stay separate.
    """

    def __init__(
        self,
        ticket_repository: TicketRepository,
        user_repository: UserRepository,
        interaction_repository: InteractionRepository,
        edit_access_repository: TicketEditAccessRequestRepository,
    ):
        self.ticket_repository = ticket_repository
        self.user_repository = user_repository
        self.interaction_repository = interaction_repository
        self.edit_access_repository = edit_access_repository

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    async def _get_ticket_or_404(self, ticket_id: UUID):
        ticket = await self.ticket_repository.get_by_id(ticket_id)

        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )

        return ticket

    async def _already_has_access(self, ticket, current_user: User) -> bool:
        if current_user.role.name in SUPERVISOR_ROLE_NAMES:
            return True

        if ticket.agent_id == current_user.user_id:
            return True

        if has_permission(current_user, "ticket:edit_ticket"):
            return True

        return await self.edit_access_repository.has_active_grant(
            ticket.ticket_id, current_user.user_id
        )

    async def _record(
        self,
        *,
        ticket_id: UUID,
        interaction_type: str,
        actor_id: UUID | None,
        actor_name: str,
        actor_role,
        payload: dict,
        event_type: AuditEventType,
        old_values: dict | None = None,
        new_values: dict | None = None,
    ) -> None:
        await self.interaction_repository.create(
            InteractionCreate(
                ticket_id=ticket_id,
                interaction_type=interaction_type,
                direction=InteractionDirection.INTERNAL,
                status=InteractionStatus.ASSIGNED,
                performed_by=actor_id,
                payload=payload,
                is_visible=True,
            )
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=event_type,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values=old_values,
            new_values=new_values,
        )

    async def _to_response(
        self,
        edit_request: TicketEditAccessRequest,
        names: dict[UUID, str] | None = None,
    ) -> EditAccessRequestResponse:
        if names is None:
            names = await self.user_repository.get_names_by_ids(
                [
                    uid
                    for uid in (edit_request.requested_by, edit_request.reviewed_by)
                    if uid is not None
                ]
            )

        return EditAccessRequestResponse(
            request_id=edit_request.request_id,
            ticket_id=edit_request.ticket_id,
            requested_by=edit_request.requested_by,
            requested_by_name=names.get(edit_request.requested_by),
            reason=edit_request.reason,
            status=edit_request.status,
            reviewed_by=edit_request.reviewed_by,
            reviewed_by_name=(
                names.get(edit_request.reviewed_by)
                if edit_request.reviewed_by is not None
                else None
            ),
            reviewed_at=edit_request.reviewed_at,
            review_note=edit_request.review_note,
            expires_at=edit_request.expires_at,
            created_at=edit_request.created_at,
        )

    # --------------------------------------------------
    # Request
    # --------------------------------------------------

    async def request_access(
        self,
        ticket_id: UUID,
        request: EditAccessRequestCreate,
        current_user: User,
    ) -> EditAccessRequestResponse:

        ticket = await self._get_ticket_or_404(ticket_id)
        ensure_agent_can_view_ticket(ticket, current_user)
        ensure_ticket_not_closed(ticket)

        if await self._already_has_access(ticket, current_user):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You can already work on this ticket.",
            )

        existing = await self.edit_access_repository.get_pending_by_ticket_and_user(
            ticket_id, current_user.user_id
        )

        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You already have a pending request for this ticket.",
            )

        edit_request = await self.edit_access_repository.create(
            TicketEditAccessRequest(
                ticket_id=ticket_id,
                requested_by=current_user.user_id,
                reason=request.reason,
            )
        )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await self._record(
            ticket_id=ticket_id,
            interaction_type="EDIT_ACCESS_REQUESTED",
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            payload={"request_id": str(edit_request.request_id), "reason": request.reason},
            event_type=AuditEventType.EDIT_ACCESS_REQUESTED,
            new_values={
                "request_id": edit_request.request_id,
                "requested_by": current_user.user_id,
                "reason": request.reason,
            },
        )

        return await self._to_response(edit_request)

    # --------------------------------------------------
    # Approve
    # --------------------------------------------------

    async def approve(
        self,
        ticket_id: UUID,
        request_id: UUID,
        request: EditAccessApproveRequest,
        current_user: User,
    ) -> EditAccessRequestResponse:

        ticket = await self._get_ticket_or_404(ticket_id)
        ensure_can_review_edit_access(ticket, current_user)

        edit_request = await self.edit_access_repository.get_by_id(request_id)

        if edit_request is None or edit_request.ticket_id != ticket_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Edit-access request not found.",
            )

        if edit_request.status != EditAccessStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This request has already been reviewed.",
            )

        edit_request = await self.edit_access_repository.approve(
            edit_request,
            reviewed_by=current_user.user_id,
            expires_at=request.expires_at,
            review_note=request.review_note,
        )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await self._record(
            ticket_id=ticket_id,
            interaction_type="EDIT_ACCESS_APPROVED",
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            payload={
                "request_id": str(edit_request.request_id),
                "requested_by": str(edit_request.requested_by),
                "expires_at": (
                    request.expires_at.isoformat() if request.expires_at else None
                ),
            },
            event_type=AuditEventType.EDIT_ACCESS_APPROVED,
            old_values={"status": EditAccessStatus.PENDING},
            new_values={
                "status": EditAccessStatus.APPROVED,
                "requested_by": edit_request.requested_by,
                "expires_at": edit_request.expires_at,
            },
        )

        return await self._to_response(edit_request)

    # --------------------------------------------------
    # Reject
    # --------------------------------------------------

    async def reject(
        self,
        ticket_id: UUID,
        request_id: UUID,
        request: EditAccessRejectRequest,
        current_user: User,
    ) -> EditAccessRequestResponse:

        ticket = await self._get_ticket_or_404(ticket_id)
        ensure_can_review_edit_access(ticket, current_user)

        edit_request = await self.edit_access_repository.get_by_id(request_id)

        if edit_request is None or edit_request.ticket_id != ticket_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Edit-access request not found.",
            )

        if edit_request.status != EditAccessStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This request has already been reviewed.",
            )

        edit_request = await self.edit_access_repository.reject(
            edit_request,
            reviewed_by=current_user.user_id,
            review_note=request.review_note,
        )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await self._record(
            ticket_id=ticket_id,
            interaction_type="EDIT_ACCESS_REJECTED",
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            payload={
                "request_id": str(edit_request.request_id),
                "requested_by": str(edit_request.requested_by),
                "review_note": request.review_note,
            },
            event_type=AuditEventType.EDIT_ACCESS_REJECTED,
            old_values={"status": EditAccessStatus.PENDING},
            new_values={
                "status": EditAccessStatus.REJECTED,
                "requested_by": edit_request.requested_by,
            },
        )

        return await self._to_response(edit_request)

    # --------------------------------------------------
    # List
    # --------------------------------------------------

    async def list_for_ticket(
        self,
        ticket_id: UUID,
        current_user: User,
    ) -> list[EditAccessRequestResponse]:

        ticket = await self._get_ticket_or_404(ticket_id)
        ensure_agent_can_view_ticket(ticket, current_user)

        requests = await self.edit_access_repository.list_by_ticket(ticket_id)

        user_ids = {
            uid
            for r in requests
            for uid in (r.requested_by, r.reviewed_by)
            if uid is not None
        }
        names = await self.user_repository.get_names_by_ids(list(user_ids))

        return [await self._to_response(r, names) for r in requests]
