from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.enums import AuditEntityType, AuditEventType, InteractionStatus
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
from app.ticketing.schemas.ticket_from_interaction import (
    TicketFromInteractionCreate,
    TicketFromInteractionResponse,
)
from app.ticketing.services.assignment_service import AssignmentService
from app.ticketing.services.audit_log_service import AuditLogService
from app.ticketing.services.sla_service import SLAService


class InboxTicketService:
    """
    Business workflows related to inbox interactions.

    Supported workflows:
    - Create ticket from inbox interaction
    - Attach inbox interaction to an existing ticket
    """

    def __init__(
        self,
        ticket_repository: TicketRepository,
        interaction_repository: InteractionRepository,
        assignment_service: AssignmentService | None = None,
        sla_service: SLAService | None = None,
    ):
        self.ticket_repository = ticket_repository
        self.interaction_repository = interaction_repository
        self.assignment_service = assignment_service
        self.sla_service = sla_service

    # ---------------------------------------------------------
    # Shared Validation
    # ---------------------------------------------------------

    async def _get_pending_interaction(self, interaction_id):
        """
        Returns a pending interaction that has not yet been
        attached to any ticket.
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

        if interaction.status != InteractionStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Interaction is not pending.",
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
            await self.assignment_service.resolve_target(current_user, request.agent_id)
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

        if self.sla_service is not None:
            await self.sla_service.complete_first_response_clock(
                interaction_id=interaction.interaction_id,
                completion_reason="ATTACHED_TO_TICKET",
                resulting_ticket_id=ticket.ticket_id,
            )
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
            message="Interaction attached successfully.",
            ticket_id=ticket.ticket_id,
            interaction_id=interaction.interaction_id,
            status=InteractionStatus.ASSIGNED,
        )