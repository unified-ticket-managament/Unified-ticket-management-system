from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.enums import (
    AuditEntityType,
    AuditEventType,
    InteractionStatus,
    TicketStatus,
)
from app.ticketing.repositories.interaction_repository import (
    InteractionRepository,
)
from app.ticketing.repositories.ticket_repository import (
    TicketRepository,
)
from app.ticketing.schemas.attach_interaction import (
    AttachInteractionRequest,
    AttachInteractionResponse,
)
from app.ticketing.schemas.ticket import TicketCreate
from app.ticketing.schemas.ticket_action import (
    PriorityChangeRequest,
    StatusChangeRequest,
    TransferAgentRequest,
)
from app.ticketing.schemas.ticket_from_interaction import (
    TicketFromInteractionCreate,
    TicketFromInteractionResponse,
)
from app.ticketing.services.access_control import (
    ensure_account_manager_owns_ticket_client,
    ensure_has_permission,
)
from app.ticketing.services.assignment_service import AssignmentService
from app.ticketing.services.audit_log_service import AuditLogService
from app.ticketing.services.sla_service import SLAService
from app.notifications.service import NotificationType


class InboxTicketService:
    """
    Business workflows related to inbox interactions.

    Supported workflows:
    - Create ticket from inbox interaction
    - Attach inbox interaction to an existing ticket (reopening it
      first, via interaction_service, if it was CLOSED)
    """

    def __init__(
        self,
        ticket_repository: TicketRepository,
        interaction_repository: InteractionRepository,
        assignment_service: AssignmentService | None = None,
        sla_service: SLAService | None = None,
        client_repository=None,
        interaction_service=None,
    ):
        self.ticket_repository = ticket_repository
        self.interaction_repository = interaction_repository
        self.assignment_service = assignment_service
        self.sla_service = sla_service
        self.client_repository = client_repository
        # Only required for attach_to_existing_ticket's closed-ticket
        # (reopen) branch — reused as-is rather than duplicated, see
        # that method's own comments. Not needed for
        # create_ticket_from_interaction.
        self.interaction_service = interaction_service

    # ---------------------------------------------------------
    # Shared Validation
    # ---------------------------------------------------------

    async def _get_pending_interaction(self, interaction_id):
        """
        Returns a not-yet-ticketed interaction — the single real gate
        for "can this become/be attached to a ticket" is `ticket_id is
        None`, matching the frontend's own `isTicketed` check
        (MessageDetailsView.tsx), which shows the Create Ticket/Attach
        buttons for any un-ticketed email regardless of its triage
        `status`.

        Deliberately does NOT also require `status == PENDING` — that
        used to be checked here too, but `status` is a separate,
        orthogonal concept (triage/response state: PENDING -> ASSIGNED
        once replied to, or IGNORED once archived — see
        InteractionRepository's "pending"/"replied"/"archived" inbox
        views) from "is this on a ticket yet." A brand-new Compose
        email and any email an agent has already replied to are both
        created/moved to ASSIGNED (see InteractionService.compose_email
        and .add_interaction_reply) while still correctly having
        ticket_id=None — "already replied, no ticket needed yet" is a
        real, common, and reversible state, not a terminal one. The
        old stricter check made every such interaction permanently
        un-convertible into a ticket, a real reported bug (400 "not
        pending" on an interaction the UI still showed a working
        Create Ticket button for).
        """

        interaction = await self.interaction_repository.get_by_id(
            interaction_id
        )

        if interaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        if interaction.ticket_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Interaction already belongs to a ticket.",
            )

        return interaction

    # ---------------------------------------------------------
    # Workflow 1
    # Create Ticket
    # ---------------------------------------------------------

    async def create_ticket_from_interaction(
        self,
        request: TicketFromInteractionCreate,
        current_user: User,
    ) -> TicketFromInteractionResponse:

        ensure_has_permission(current_user, "communication:convert_to_ticket")

        interaction = await self._get_pending_interaction(
            request.interaction_id
        )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        # Tickets are born unclaimed (agent_id=None) unless the Create
        # Ticket dialog's "Assigned To" picker chose someone — resolved
        # (and validated against the actor's own hierarchy) via
        # AssignmentService, never trusted as-is. `created_by` still
        # separately records who actually did the promoting.
        resolved_agent_id = (
            await self.assignment_service.resolve_target(
                current_user, request.agent_id, request.ticket_type
            )
            if self.assignment_service is not None
            else None
        )

        ticket = await self.ticket_repository.create(

            TicketCreate(

                client_id=None,

                client_company_id=interaction.client_id,

                agent_id=resolved_agent_id,

                created_by=actor_id,

                title=request.title,

                ticket_type=request.ticket_type,

                current_priority=request.current_priority,

                custom_fields={},

            )

        )

        # Moves the interaction AND every reply already filed under
        # it (if this was already a thread) onto the new ticket.
        await self.interaction_repository.assign_thread_to_ticket(
            root_interaction_id=interaction.interaction_id,
            ticket_id=ticket.ticket_id,
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket.ticket_id,
            event_type=AuditEventType.TICKET_CREATED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={
                "title": ticket.title,
                "ticket_type": ticket.ticket_type,
                "current_priority": ticket.current_priority,
                "client_company_id": ticket.client_company_id,
                "interaction_id": interaction.interaction_id,
            },
        )

        if self.sla_service is not None:
            await self.sla_service.complete_first_response_clock(
                interaction_id=interaction.interaction_id,
                completion_reason="TICKET_CREATED",
                resulting_ticket_id=ticket.ticket_id,
            )
            await self.sla_service.start_resolution_clock(
                ticket_id=ticket.ticket_id,
                client_id=ticket.client_company_id,
                priority=ticket.current_priority,
            )

        return TicketFromInteractionResponse(
            message="Ticket created successfully.",
            ticket_id=ticket.ticket_id,
            interaction_id=interaction.interaction_id,
            status=InteractionStatus.ASSIGNED.value,
        )

    # ---------------------------------------------------------
    # Workflow 2
    # Attach Interaction to Existing Ticket
    # ---------------------------------------------------------

    async def attach_to_existing_ticket(
        self,
        ticket_id,
        request: AttachInteractionRequest,
        current_user: User,
    ) -> AttachInteractionResponse:

        ensure_has_permission(current_user, "communication:attach_to_ticket")

        # Validate interaction
        interaction = await self._get_pending_interaction(
            request.interaction_id
        )

        # Validate ticket
        ticket = await self.ticket_repository.get_by_id(
            ticket_id
        )

        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )

        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )

        was_closed = ticket.current_status == TicketStatus.CLOSED

        if was_closed:
            if self.interaction_service is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Reopening a closed ticket requires interaction_service.",
                )

            # Same ticket, history, interactions, audit log — reuses
            # InteractionService.reopen_ticket end-to-end (its own
            # CLOSED-only guard, ticket:reopen permission check, and
            # TICKET_REOPENED audit row) instead of duplicating any of
            # it here. Raises 403 if this caller lacks ticket:reopen —
            # attaching an email doesn't bypass that permission.
            await self.interaction_service.reopen_ticket(ticket_id, current_user)

            # reopen_ticket alone only ever restores OPEN (its own
            # docstring: "restores it to OPEN") — this workflow needs
            # the ticket to land on an actively-worked state instead,
            # so it moves one step further via the same, ordinary
            # change_status transition every other status change already
            # goes through (OPEN -> IN_PROGRESS is a pre-existing, valid
            # transition; no new status value, no separate "reopened"
            # state).
            await self.interaction_service.change_status(
                ticket_id,
                StatusChangeRequest(new_status=TicketStatus.IN_PROGRESS),
                current_user,
            )

            # Final priority for reopen: only touched if the caller
            # actually chose to change it — reuses
            # InteractionService.change_priority as-is (its own
            # PRIORITY_CHANGED audit row, stakeholder notification, and
            # SLA reshift call, the last of which safely no-ops here
            # since the clock is still COMPLETED at this point — the
            # real reshift for reopen happens below via
            # reopen_resolution_clock, using whatever priority ends up
            # set on the ticket).
            if (
                request.new_priority is not None
                and request.new_priority != ticket.current_priority
            ):
                await self.interaction_service.change_priority(
                    ticket_id,
                    PriorityChangeRequest(new_priority=request.new_priority),
                    current_user,
                )

        # Attach the interaction AND every reply already filed
        # under it (if this was already a thread) to the ticket.
        await self.interaction_repository.assign_thread_to_ticket(
            root_interaction_id=interaction.interaction_id,
            ticket_id=ticket.ticket_id,
        )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        # Reuses TICKET_UPDATED (no new enum value / migration needed
        # for this) — the new_values payload's own "action" key is
        # what distinguishes this from any other ticket-field edit.
        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket.ticket_id,
            event_type=AuditEventType.TICKET_UPDATED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={
                "action": "existing_email_attached",
                "interaction_id": interaction.interaction_id,
            },
        )

        if was_closed:
            if request.new_agent_id is not None:
                # Reuses InteractionService.transfer_agent as-is — its
                # own eligibility rules, AGENT_TRANSFERRED audit row,
                # and new-assignee notification.
                await self.interaction_service.transfer_agent(
                    ticket_id,
                    TransferAgentRequest(
                        new_agent_id=request.new_agent_id,
                        reason="Reassigned while reopening via attached email.",
                    ),
                    current_user,
                )
            else:
                previous_agent_id = ticket.agent_id
                await AuditLogService.log_event(
                    self.ticket_repository.db,
                    entity_type=AuditEntityType.TICKET,
                    entity_id=ticket.ticket_id,
                    event_type=AuditEventType.TICKET_UPDATED,
                    actor_id=actor_id,
                    actor_name=actor_name,
                    actor_role=actor_role,
                    new_values={
                        "action": "assignment_strategy",
                        "strategy": "keep_existing",
                        "agent_id": previous_agent_id,
                    },
                )
                notification_service = self.interaction_service.notification_service
                if notification_service is not None and previous_agent_id is not None:
                    await notification_service.notify(
                        previous_agent_id,
                        NotificationType.TICKET_STATUS_CHANGED,
                        title="A closed ticket you own was reopened",
                        message=f"{ticket.title}: reopened via a newly attached email.",
                        link=f"/tickets/{ticket_id}",
                        related_entity_type="ticket",
                        related_entity_id=ticket_id,
                    )

        if self.sla_service is not None:
            await self.sla_service.complete_first_response_clock(
                interaction_id=interaction.interaction_id,
                completion_reason="ATTACHED_TO_TICKET",
                resulting_ticket_id=ticket.ticket_id,
            )
            if was_closed:
                # FINAL priority (possibly just changed above) drives
                # the new Resolution SLA — revives the ticket's own
                # completed clock rather than creating a second row
                # (ResolutionSLA.ticket_id is unique).
                await self.sla_service.reopen_resolution_clock(
                    ticket_id=ticket.ticket_id,
                    client_id=ticket.client_company_id,
                    priority=ticket.current_priority,
                )
            else:
                # Creates a fresh Resolution clock if this ticket somehow
                # never had one (pre-dates this feature), or resumes it if
                # paused — see SLAService.create_or_resume_resolution_clock's
                # own docstring for the full RUNNING/PAUSED/COMPLETED
                # decision table.
                await self.sla_service.create_or_resume_resolution_clock(
                    ticket_id=ticket.ticket_id,
                    client_id=ticket.client_company_id,
                    priority=ticket.current_priority,
                )

        return AttachInteractionResponse(
            message=(
                "Ticket reopened and interaction attached successfully."
                if was_closed
                else "Interaction attached successfully."
            ),
            ticket_id=ticket.ticket_id,
            interaction_id=interaction.interaction_id,
            status=InteractionStatus.ASSIGNED,
            ticket_reopened=was_closed,
        )