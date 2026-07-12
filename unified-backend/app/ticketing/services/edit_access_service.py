from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.enums import (
    AuditEntityType,
    AuditEventType,
    EditAccessStatus,
)
from app.ticketing.models.ticket_edit_access_request import TicketEditAccessRequest
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_edit_access_repository import (
    TicketEditAccessRequestRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.edit_access import (
    EditAccessApproveRequest,
    EditAccessRejectRequest,
    EditAccessRequestCreate,
    EditAccessRequestResponse,
)
from app.ticketing.services.access_control import (
    SUPERVISOR_ROLE_NAMES,
    ensure_agent_can_view_ticket,
    ensure_can_review_edit_access,
    ensure_ticket_not_closed,
    has_permission_for_ticket,
)
from app.ticketing.services.audit_log_service import AuditLogService
from app.notifications.service import NotificationService, NotificationType

# Roles that hold ticket:editother_ticket by default (see rbac-service's
# seed.py DEFAULT_ROLES) — Super Admin/Site Lead/Account Manager are
# unrestricted reviewers; Team Lead is further scoped to its own
# category, matching ensure_can_review_edit_access's own view+permission
# gate. Staff never holds this by default, so it's deliberately absent
# here — an individually-overridden Staff reviewer (a real but rare
# case) won't be notified, same accepted simplification as the
# eligible-approver-roles resolution in permission_request_service.py.
UNRESTRICTED_EDIT_ACCESS_ROLE_NAMES = {"Super Admin", "Site Lead", "Account Manager"}
CATEGORY_SCOPED_EDIT_ACCESS_ROLE_NAME = "Team Lead"


class EditAccessService:
    """
    Business logic for the per-ticket edit-access request/approve/
    reject workflow — letting someone who isn't the assigned agent
    (and doesn't already hold ticket:editother_ticket) work one specific
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
        notification_service: NotificationService | None = None,
    ):
        self.ticket_repository = ticket_repository
        self.user_repository = user_repository
        self.interaction_repository = interaction_repository
        self.edit_access_repository = edit_access_repository
        self.notification_service = notification_service

    async def _resolve_reviewer_ids(self, ticket) -> set[UUID]:
        """
        Every user who could approve/reject an edit-access request for
        this ticket — mirrors ensure_can_review_edit_access's own gate
        (view access + ticket:editother_ticket) rather than re-deriving a
        different notion of "reviewer".
        """

        reviewer_ids: set[UUID] = set()

        for role_name in UNRESTRICTED_EDIT_ACCESS_ROLE_NAMES:
            users = await self.user_repository.list_active_by_role_name(role_name)
            reviewer_ids.update(u.user_id for u in users)

        team_leads = await self.user_repository.list_active_by_role_and_category(
            CATEGORY_SCOPED_EDIT_ACCESS_ROLE_NAME, ticket.ticket_type
        )
        reviewer_ids.update(u.user_id for u in team_leads)

        return reviewer_ids

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

        if has_permission_for_ticket(
            current_user, "ticket:editother_ticket", ticket.ticket_id
        ):
            return True

        return await self.edit_access_repository.has_active_grant(
            ticket.ticket_id, current_user.user_id
        )

    async def _record(
        self,
        *,
        ticket_id: UUID,
        actor_id: UUID | None,
        actor_name: str,
        actor_role,
        event_type: AuditEventType,
        old_values: dict | None = None,
        new_values: dict | None = None,
    ) -> None:
        """
        Writes the AuditLog row for an edit-access transition. No
        longer also writes an Interaction row — EDIT_ACCESS_REQUESTED/
        APPROVED/REJECTED are retired timeline-only types (see
        services/audit_to_interaction.py); this AuditLog row is now
        the sole record, and the Timeline/Interactions-list endpoints
        synthesize a display row back from it.
        """

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
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            event_type=AuditEventType.EDIT_ACCESS_REQUESTED,
            new_values={
                "request_id": edit_request.request_id,
                "requested_by": current_user.user_id,
                "reason": request.reason,
            },
        )

        if self.notification_service is not None:
            reviewer_ids = await self._resolve_reviewer_ids(ticket)
            reviewer_ids.discard(current_user.user_id)
            await self.notification_service.notify(
                reviewer_ids,
                NotificationType.EDIT_ACCESS_REQUESTED,
                title=f"{current_user.name} requested edit access",
                message=f"Ticket: {ticket.title}",
                link=f"/tickets/{ticket_id}",
                related_entity_type="ticket_edit_access_request",
                related_entity_id=edit_request.request_id,
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
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            event_type=AuditEventType.EDIT_ACCESS_APPROVED,
            old_values={"status": EditAccessStatus.PENDING},
            new_values={
                "status": EditAccessStatus.APPROVED,
                "requested_by": edit_request.requested_by,
                "expires_at": edit_request.expires_at,
            },
        )

        if self.notification_service is not None:
            await self.notification_service.notify(
                edit_request.requested_by,
                NotificationType.EDIT_ACCESS_APPROVED,
                title="Your edit-access request was approved",
                message=f"Ticket: {ticket.title}",
                link=f"/tickets/{ticket_id}",
                related_entity_type="ticket_edit_access_request",
                related_entity_id=edit_request.request_id,
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
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            event_type=AuditEventType.EDIT_ACCESS_REJECTED,
            old_values={"status": EditAccessStatus.PENDING},
            new_values={
                "status": EditAccessStatus.REJECTED,
                "requested_by": edit_request.requested_by,
                "review_note": request.review_note,
            },
        )

        if self.notification_service is not None:
            await self.notification_service.notify(
                edit_request.requested_by,
                NotificationType.EDIT_ACCESS_REJECTED,
                title="Your edit-access request was rejected",
                message=f"Ticket: {ticket.title}",
                link=f"/tickets/{ticket_id}",
                related_entity_type="ticket_edit_access_request",
                related_entity_id=edit_request.request_id,
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
