from fastapi import HTTPException, status

from app.enums import ActorRole, AuditEntityType, AuditEventType, InteractionStatus
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.ticket_repository import (
    TicketRepository,
)
from app.schemas.attach_interaction import (
    AttachInteractionRequest,
    AttachInteractionResponse,
)
from app.schemas.payloads import EmailPayload
from app.schemas.ticket import TicketCreate
from app.schemas.ticket_from_interaction import (
    TicketFromInteractionCreate,
    TicketFromInteractionResponse,
)
from app.services.audit_log_service import AuditLogService


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
    ):
        self.ticket_repository = ticket_repository
        self.interaction_repository = interaction_repository

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
    ) -> TicketFromInteractionResponse:

        interaction = await self._get_pending_interaction(
            request.interaction_id
        )

        payload = EmailPayload.model_validate(
            interaction.payload
        )

        ticket = await self.ticket_repository.create(

            TicketCreate(

                client_id=payload.client_id,

                agent_id=payload.agent_id,

                created_by=payload.agent_id,

                title=request.title,

                ticket_type=request.ticket_type,

                current_priority=request.current_priority,

                custom_fields={},

            )

        )

        await self.interaction_repository.assign_to_ticket(
            interaction=interaction,
            ticket_id=ticket.ticket_id,
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket.ticket_id,
            event_type=AuditEventType.TICKET_CREATED,
            actor_id=payload.agent_id,
            actor_name=payload.agent_name,
            actor_role=ActorRole.AGENT,
            new_values={
                "title": ticket.title,
                "ticket_type": ticket.ticket_type,
                "current_priority": ticket.current_priority,
                "client_id": ticket.client_id,
                "agent_id": ticket.agent_id,
                "interaction_id": interaction.interaction_id,
            },
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

        # Attach interaction
        await self.interaction_repository.assign_to_ticket(
            interaction=interaction,
            ticket_id=ticket.ticket_id,
        )

        return AttachInteractionResponse(
            message="Interaction attached successfully.",
            ticket_id=ticket.ticket_id,
            interaction_id=interaction.interaction_id,
            status=InteractionStatus.ASSIGNED,
        )