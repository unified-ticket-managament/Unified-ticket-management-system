# interaction_service.py


import asyncio
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from fastapi import status as http_status

from shared_models.models import User

from app.repositories.client_repository import ClientRepository
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.mail_folder_repository import MailFolderRepository
from app.repositories.ticket_repository import (
    TicketRepository,
)
from app.repositories.user_repository import UserRepository
from app.schemas.interaction import (
    DraftDeleteResponse,
    DraftResponse,
    DraftSaveRequest,
    FolderAssignRequest,
    HideInteractionRequest,
    HideInteractionResponse,
    InteractionArchiveResponse,
    InteractionClaimResponse,
    InteractionCreate,
    InteractionFolderResponse,
    InteractionResponse,
    InteractionSnoozeResponse,
    InteractionTagsResponse,
    InteractionUpdate,
    SnoozeRequest,
    TagsUpdateRequest,
    ThreadResponse,
)
from app.schemas.note import (
    InternalNoteCreate,
    InternalNoteResponse,
)
from app.schemas.ticket import TicketUpdate
from app.schemas.ticket_action import (
    InteractionReplyRequest,
    InteractionReplyResponse,
    PriorityChangeRequest,
    ReplyCreate,
    StatusChangeRequest,
    TicketActionResponse,
    TransferAgentRequest,
)
from app.repositories.audit_log_repository import AuditLogRepository
from app.schemas.audit_log import AuditLogResponse
from app.services.access_control import (
    ensure_agent_can_view_pending_interaction,
    ensure_agent_can_view_ticket,
    ensure_can_reassign_ticket,
    ensure_ticket_not_closed,
)
from app.services.audit_log_service import AuditLogService
from app.services.email_envelope import build_reply_envelope
from app.services.outbound_dispatcher import OutboundDispatcher

from app.enums import (
    AuditEntityType,
    AuditEventType,
    InteractionDirection,
    InteractionStatus,
    TicketStatus,
)

from typing import Any
from app.models.interaction import Interaction
from app.repositories.attachment_repository import AttachmentRepository
from app.schemas.attachment import AttachmentMetadata
from app.schemas.payloads import EmailPayload
from app.services.attachment_service import attachments_to_metadata
from app.storage.base import StorageService


def _to_response(
    interaction: Interaction,
    attachments: list[AttachmentMetadata] | None = None,
) -> InteractionResponse:
    """
    Builds an InteractionResponse without touching
    `interaction.attachments` — that relationship is lazy and
    unloaded on every query in this file, so letting pydantic's
    from_attributes machinery read it directly would trigger an
    unawaited lazy load. Callers that need real attachments (the
    ticket timeline) fetch them separately and pass them in.
    """

    return InteractionResponse(
        interaction_id=interaction.interaction_id,
        ticket_id=interaction.ticket_id,
        interaction_type=interaction.interaction_type,
        status=interaction.status,
        direction=interaction.direction,
        performed_by=interaction.performed_by,
        payload=interaction.payload,
        is_visible=interaction.is_visible,
        removed_by=interaction.removed_by,
        removed_at=interaction.removed_at,
        message_id=interaction.message_id,
        client_id=interaction.client_id,
        parent_interaction_id=interaction.parent_interaction_id,
        received_at=interaction.received_at,
        created_at=interaction.created_at,
        attachments=attachments or [],
        conversation_id=interaction.conversation_id,
        in_reply_to_message_id=interaction.in_reply_to_message_id,
        references=interaction.references or [],
    )




class InteractionService:
    """
    Service layer for Interaction operations.
    """

    def __init__(
        self,
        interaction_repository: InteractionRepository,
        ticket_repository: TicketRepository,
        user_repository: UserRepository,
        attachment_repository: AttachmentRepository | None = None,
        storage_service: StorageService | None = None,
        audit_log_repository: AuditLogRepository | None = None,
        client_repository: ClientRepository | None = None,
        outbound_dispatcher: OutboundDispatcher | None = None,
        mail_folder_repository: MailFolderRepository | None = None,
    ):
        self.interaction_repository = interaction_repository
        self.ticket_repository = ticket_repository
        self.user_repository = user_repository
        self.attachment_repository = attachment_repository
        self.storage_service = storage_service
        self.audit_log_repository = audit_log_repository
        self.client_repository = client_repository
        self.outbound_dispatcher = outbound_dispatcher or OutboundDispatcher()
        self.mail_folder_repository = mail_folder_repository

    # ---------------------------------------------------------
    # Create Interaction
    # ---------------------------------------------------------

    async def create(
        self,
        request: InteractionCreate,
    ) -> InteractionResponse:

        interaction = await self.interaction_repository.create(
            request
        )

        return _to_response(interaction)

    # ---------------------------------------------------------
    # Get Interaction By ID
    # ---------------------------------------------------------

    async def get_by_id(
        self,
        interaction_id: UUID,
    ) -> InteractionResponse:

        interaction = await self.interaction_repository.get_by_id(
            interaction_id
        )

        if interaction is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        return _to_response(interaction)

    # ---------------------------------------------------------
    # Update Interaction
    # ---------------------------------------------------------

    async def update(
        self,
        interaction_id: UUID,
        request: InteractionUpdate,
    ) -> InteractionResponse:

        interaction = await self.interaction_repository.get_by_id(
            interaction_id
        )

        if interaction is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        interaction = await self.interaction_repository.update(
            interaction,
            request,
        )

        return _to_response(interaction)

    # ---------------------------------------------------------
    # Ticket Timeline
    # ---------------------------------------------------------

    async def get_ticket_interactions(
        self,
        ticket_id: UUID,
        current_user: User,
    ) -> list[InteractionResponse]:
        """
        Returns the complete timeline for a ticket.

        Interactions are ordered chronologically by created_at
        (oldest first). Gated by ensure_agent_can_view_ticket — a
        Team Lead/Staff only sees this if the ticket is in their own
        category; every other agent role is unrestricted.
        """

        ticket = await self._get_ticket_or_404(ticket_id)

        ensure_agent_can_view_ticket(ticket, current_user)

        interactions = (
            await self.interaction_repository
            .list_by_ticket_id(ticket_id)
        )

        attachments_by_interaction: dict[UUID, list[AttachmentMetadata]] = {}

        if self.attachment_repository is not None and self.storage_service is not None:
            interaction_ids = [i.interaction_id for i in interactions]
            attachments_map = await self.attachment_repository.list_by_interaction_ids(
                interaction_ids
            )
            interaction_ids_with_files = list(attachments_map.keys())
            metadata_lists = await asyncio.gather(
                *(
                    attachments_to_metadata(attachments_map[iid], self.storage_service)
                    for iid in interaction_ids_with_files
                )
            )
            attachments_by_interaction = dict(zip(interaction_ids_with_files, metadata_lists))

        return [
            _to_response(
                interaction,
                attachments_by_interaction.get(interaction.interaction_id),
            )
            for interaction in interactions
        ]

    # ---------------------------------------------------------
    # Ticket Audit Trail
    # ---------------------------------------------------------

    async def get_ticket_audit_logs(
        self,
        ticket_id: UUID,
        current_user: User,
    ) -> list[AuditLogResponse]:
        """
        Returns the full, immutable audit trail for a ticket, newest
        first — both the direct TICKET rows (create, update, status/
        priority change, transfer) and the INTERACTION / ATTACHMENT
        rows (note, reply, hide, upload) tagged with this ticket_id.

        This is deliberately separate from get_ticket_interactions:
        the timeline above is the business record agents act on;
        this is the compliance/security record of who changed what.
        Same access gate as the timeline — see
        ensure_agent_can_view_ticket's category scoping.
        """

        ticket = await self._get_ticket_or_404(ticket_id)

        ensure_agent_can_view_ticket(ticket, current_user)

        audit_logs = await self.audit_log_repository.list_by_ticket(ticket_id)

        # actor_name / actor_role are stored directly on the row at
        # write time (not resolved via a join here) — an audit trail
        # should keep saying who did something even if that user's
        # name changes later, so no name-resolution step is needed.
        return [AuditLogResponse.model_validate(log) for log in audit_logs]

    # ---------------------------------------------------------
    # Shared Helpers
    # ---------------------------------------------------------

    async def _get_ticket_or_404(self, ticket_id: UUID):

        ticket = await self.ticket_repository.get_by_id(ticket_id)

        if ticket is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )

        return ticket

    async def _resolve_account_manager_email(self, client) -> str | None:
        """
        Looks up the email of the client's Account Manager, for the
        auto-Cc on outbound replies. Best-effort — a missing/removed
        user just means no Cc, not a failed reply.
        """

        manager = await self.user_repository.get_by_id(client.account_manager_id)
        return manager.email if manager is not None else None

    async def _create_ticket_interaction(
        self,
        *,
        ticket_id: UUID,
        interaction_type: str,
        direction: InteractionDirection,
        payload: dict[str, Any],
        performed_by: UUID | None = None,
        interaction_status: InteractionStatus = InteractionStatus.ASSIGNED,
        message_id: str | None = None,
        client_id: UUID | None = None,
        parent_interaction_id: UUID | None = None,
    ) -> Interaction:
        """
        Creates any interaction that belongs to a ticket.

        Used by:
        - Reply
        - Internal Note
        - Status Change
        - Priority Change
        - Assignment Change
        - Claim
        - Attachments

        `message_id` is set on outbound replies so a future inbound
        answer's In-Reply-To can be matched back to this ticket.
        `client_id` propagates the ticket's client onto the
        interaction row so it also surfaces in that client's
        "All activity" inbox view. `parent_interaction_id` threads a
        reply under the ticket's original email thread root — only
        Reply passes it; every other caller leaves it NULL since
        notes/status/priority/transfer/claim/attachments aren't part
        of the client email conversation.
        """

        await self._get_ticket_or_404(ticket_id)

        interaction = await self.interaction_repository.create(

            InteractionCreate(

                ticket_id=ticket_id,

                interaction_type=interaction_type,

                direction=direction,

                status=interaction_status,

                performed_by=performed_by,

                payload=payload,

                is_visible=True,

                message_id=message_id,

                client_id=client_id,

                parent_interaction_id=parent_interaction_id,

            )

        )

        return interaction

    # ---------------------------------------------------------
    # Internal Note
    # ---------------------------------------------------------

    async def add_internal_note(
        self,
        ticket_id: UUID,
        request: InternalNoteCreate,
        current_user: User,
    ) -> InternalNoteResponse:
        """
        Adds an internal note to a ticket.

        Every internal note is stored as an Interaction.
        """

        ticket = await self._get_ticket_or_404(ticket_id)
        ensure_ticket_not_closed(ticket)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        interaction = await self._create_ticket_interaction(
            ticket_id=ticket_id,
            interaction_type="INTERNAL_NOTE",
            direction=InteractionDirection.INTERNAL,
            payload={
                "note": request.note,
            },
            performed_by=actor_id,
        )

        # Metadata only — the note text itself is never written to
        # the audit trail.
        await AuditLogService.log_event(
            self.interaction_repository.db,
            entity_type=AuditEntityType.INTERACTION,
            entity_id=interaction.interaction_id,
            event_type=AuditEventType.NOTE_ADDED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={"ticket_id": ticket_id},
        )

        return InternalNoteResponse(

            interaction_id=interaction.interaction_id,

            ticket_id=ticket_id,

            message="Internal note added successfully.",

            created_at=interaction.created_at,

        )

    # ---------------------------------------------------------
    # Reply To Client
    # ---------------------------------------------------------

    async def add_reply(
        self,
        ticket_id: UUID,
        request: ReplyCreate,
        current_user: User,
    ) -> TicketActionResponse:
        """
        Adds a reply to the client on a ticket.

        Stored as an OUTBOUND interaction, visible to the client.
        When the ticket has a resolvable client and a prior inbound
        email, this also builds a full outbound envelope (From the
        client's shared inbox, To the original sender, threaded
        Subject/Message-ID) and hands it to the dispatch seam — the
        actual send is Task 1's transport layer.
        """

        ticket = await self._get_ticket_or_404(ticket_id)
        ensure_ticket_not_closed(ticket)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        # The latest inbound email on this ticket is both the envelope
        # source (recipient address, In-Reply-To) and the thread this
        # reply belongs to — resolved once, used for both, regardless
        # of whether envelope-building succeeds.
        latest_email = await self.interaction_repository.get_latest_inbound_email_for_ticket(
            ticket_id
        )
        thread_root_id = (
            (latest_email.parent_interaction_id or latest_email.interaction_id)
            if latest_email is not None
            else None
        )

        envelope = None
        if self.client_repository is not None and ticket.client_company_id is not None:
            client = await self.client_repository.get_by_id(ticket.client_company_id)
            if client is not None and latest_email is not None:
                inbound_payload = EmailPayload.model_validate(latest_email.payload)
                am_email = await self._resolve_account_manager_email(client)
                envelope = build_reply_envelope(
                    client=client,
                    inbound_payload=inbound_payload,
                    inbound_message_id=latest_email.message_id,
                    body=request.message,
                    agent_name=current_user.name,
                    account_manager_email=am_email,
                )

        payload: dict[str, Any] = {"message": request.message}
        if envelope is not None:
            payload["envelope"] = envelope.model_dump()
            payload["dispatch_status"] = "QUEUED"
        else:
            payload["dispatch_status"] = "NO_RECIPIENT"

        interaction = await self._create_ticket_interaction(
            ticket_id=ticket_id,
            interaction_type="REPLY",
            direction=InteractionDirection.OUTBOUND,
            payload=payload,
            performed_by=actor_id,
            message_id=envelope.message_id if envelope is not None else None,
            client_id=ticket.client_company_id,
            parent_interaction_id=thread_root_id,
        )

        # Metadata only — the reply body itself is never written to
        # the audit trail.
        await AuditLogService.log_event(
            self.interaction_repository.db,
            entity_type=AuditEntityType.INTERACTION,
            entity_id=interaction.interaction_id,
            event_type=AuditEventType.REPLY_ADDED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={"ticket_id": ticket_id},
        )

        if envelope is not None:
            await self.outbound_dispatcher.dispatch(interaction.interaction_id, envelope)

        return TicketActionResponse(
            interaction_id=interaction.interaction_id,
            ticket_id=ticket_id,
            message="Reply sent successfully.",
            created_at=interaction.created_at,
        )

    # ---------------------------------------------------------
    # Reply To A Bare (Not-Yet-Ticketed) Interaction
    # ---------------------------------------------------------

    async def add_interaction_reply(
        self,
        interaction_id: UUID,
        request: InteractionReplyRequest,
        current_user: User,
    ) -> InteractionReplyResponse:
        """
        Replies to a client on an inbox conversation that hasn't
        (and may never) become a ticket — the "general communication,
        no ticket needed" path. Builds the same kind of outbound
        envelope as a ticket reply, just addressed from the thread's
        root email instead of a ticket's email history.
        """

        root_interaction = await self.interaction_repository.get_by_id(interaction_id)

        if root_interaction is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        if root_interaction.ticket_id is not None:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="This interaction already belongs to a ticket — use the ticket reply endpoint.",
            )

        # Resolve the thread root: replying on a reply should still
        # thread under the original conversation, not fork a new one.
        root_id = root_interaction.parent_interaction_id or root_interaction.interaction_id
        root = (
            root_interaction
            if root_interaction.parent_interaction_id is None
            else await self.interaction_repository.get_by_id(root_id)
        )

        if root is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        inbound_payload = EmailPayload.model_validate(root.payload)

        envelope = None
        if self.client_repository is not None and root.client_id is not None:
            client = await self.client_repository.get_by_id(root.client_id)
            if client is not None:
                am_email = await self._resolve_account_manager_email(client)
                envelope = build_reply_envelope(
                    client=client,
                    inbound_payload=inbound_payload,
                    inbound_message_id=root.message_id,
                    body=request.message,
                    agent_name=current_user.name,
                    account_manager_email=am_email,
                )

        payload: dict[str, Any] = {"message": request.message}
        if envelope is not None:
            payload["envelope"] = envelope.model_dump()
            payload["dispatch_status"] = "QUEUED"
        else:
            payload["dispatch_status"] = "NO_RECIPIENT"

        interaction = await self.interaction_repository.create(
            InteractionCreate(
                ticket_id=None,
                interaction_type="REPLY",
                direction=InteractionDirection.OUTBOUND,
                status=InteractionStatus.ASSIGNED,
                performed_by=actor_id,
                payload=payload,
                is_visible=True,
                message_id=envelope.message_id if envelope is not None else None,
                client_id=root.client_id,
                parent_interaction_id=root.interaction_id,
            )
        )

        # Metadata only — the reply body itself is never written to
        # the audit trail.
        await AuditLogService.log_event(
            self.interaction_repository.db,
            entity_type=AuditEntityType.INTERACTION,
            entity_id=interaction.interaction_id,
            event_type=AuditEventType.REPLY_ADDED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={"parent_interaction_id": root.interaction_id},
        )

        if envelope is not None:
            await self.outbound_dispatcher.dispatch(interaction.interaction_id, envelope)

        # The root leaves the Pending triage queue once it's been
        # replied to — "general communication, no ticket needed" is
        # now handled, not waiting on anyone.
        if root.status == InteractionStatus.PENDING:
            await self.interaction_repository.update(
                root, InteractionUpdate(status=InteractionStatus.ASSIGNED)
            )

        return InteractionReplyResponse(
            interaction_id=interaction.interaction_id,
            parent_interaction_id=root.interaction_id,
            message=request.message,
            created_at=interaction.created_at,
        )

    # ---------------------------------------------------------
    # Status Change
    # ---------------------------------------------------------

    async def change_status(
        self,
        ticket_id: UUID,
        request: StatusChangeRequest,
        current_user: User,
    ) -> TicketActionResponse:
        """
        Changes a ticket's status and records the
        change as an interaction on the timeline.
        """

        ticket = await self._get_ticket_or_404(ticket_id)

        old_status = ticket.current_status
        old_closed_at = ticket.closed_at
        new_status = request.new_status

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        # Resolving or closing a ticket stamps `closed_at`; reopening
        # one (moving off RESOLVED/CLOSED) clears it back to None.
        # Moving between RESOLVED and CLOSED leaves the original stamp
        # alone — this is the single place that ever sets or clears
        # it, since the dedicated "Resolve" action was folded in here
        # to avoid two ways of doing the same thing.
        was_closed = old_status in (TicketStatus.RESOLVED, TicketStatus.CLOSED)
        will_be_closed = new_status in (TicketStatus.RESOLVED, TicketStatus.CLOSED)

        update_fields: dict[str, Any] = {"current_status": new_status}
        if not was_closed and will_be_closed:
            update_fields["closed_at"] = datetime.now(timezone.utc)
        elif was_closed and not will_be_closed:
            update_fields["closed_at"] = None

        await self.ticket_repository.update(
            ticket,
            TicketUpdate(**update_fields),
        )

        interaction = await self._create_ticket_interaction(
            ticket_id=ticket_id,
            interaction_type="STATUS_CHANGE",
            direction=InteractionDirection.INTERNAL,
            payload={
                "from": old_status.value,
                "to": new_status.value,
            },
            performed_by=actor_id,
        )

        old_values: dict[str, Any] = {"current_status": old_status}
        new_values: dict[str, Any] = {
            "current_status": new_status,
            "interaction_id": interaction.interaction_id,
        }
        if "closed_at" in update_fields:
            old_values["closed_at"] = old_closed_at
            new_values["closed_at"] = update_fields["closed_at"]

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.STATUS_CHANGED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values=old_values,
            new_values=new_values,
        )

        return TicketActionResponse(
            interaction_id=interaction.interaction_id,
            ticket_id=ticket_id,
            message="Ticket status updated successfully.",
            created_at=interaction.created_at,
        )

    # ---------------------------------------------------------
    # Priority Change
    # ---------------------------------------------------------

    async def change_priority(
        self,
        ticket_id: UUID,
        request: PriorityChangeRequest,
        current_user: User,
    ) -> TicketActionResponse:
        """
        Changes a ticket's priority and records the
        change as an interaction on the timeline.
        """

        ticket = await self._get_ticket_or_404(ticket_id)
        ensure_ticket_not_closed(ticket)

        old_priority = ticket.current_priority

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await self.ticket_repository.update(
            ticket,
            TicketUpdate(current_priority=request.new_priority),
        )

        interaction = await self._create_ticket_interaction(
            ticket_id=ticket_id,
            interaction_type="PRIORITY_CHANGE",
            direction=InteractionDirection.INTERNAL,
            payload={
                "from": old_priority.value,
                "to": request.new_priority.value,
            },
            performed_by=actor_id,
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.PRIORITY_CHANGED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"current_priority": old_priority},
            new_values={
                "current_priority": request.new_priority,
                "interaction_id": interaction.interaction_id,
            },
        )

        return TicketActionResponse(
            interaction_id=interaction.interaction_id,
            ticket_id=ticket_id,
            message="Ticket priority updated successfully.",
            created_at=interaction.created_at,
        )

    # ---------------------------------------------------------
    # Transfer Agent
    # ---------------------------------------------------------

    async def transfer_agent(
        self,
        ticket_id: UUID,
        request: TransferAgentRequest,
        current_user: User,
    ) -> TicketActionResponse:
        """
        Transfers full ownership of a ticket to a different
        active Staff member. The previous agent loses all
        rights on the ticket the moment this completes — the
        new agent_id fully replaces the old one, it isn't
        shared or co-owned.
        """

        ticket = await self._get_ticket_or_404(ticket_id)
        ensure_ticket_not_closed(ticket)
        ensure_can_reassign_ticket(current_user)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        new_agent = await self.user_repository.get_active_staff_by_id(
            request.new_agent_id
        )

        if new_agent is None:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="New agent must be an active Staff member.",
            )

        if ticket.agent_id == new_agent.user_id:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Ticket is already assigned to this agent.",
            )

        old_agent_id = ticket.agent_id
        old_agent_name = None

        if old_agent_id is not None:
            old_agent = await self.user_repository.get_by_id(old_agent_id)
            old_agent_name = old_agent.name if old_agent else None

        await self.ticket_repository.update(
            ticket,
            TicketUpdate(agent_id=new_agent.user_id),
        )

        interaction = await self._create_ticket_interaction(
            ticket_id=ticket_id,
            interaction_type="AGENT_TRANSFER",
            direction=InteractionDirection.INTERNAL,
            payload={
                "from_agent_id": str(old_agent_id) if old_agent_id else None,
                "from_agent_name": old_agent_name,
                "to_agent_id": str(new_agent.user_id),
                "to_agent_name": new_agent.name,
            },
            performed_by=actor_id,
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.AGENT_TRANSFERRED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"agent_id": old_agent_id},
            new_values={
                "agent_id": new_agent.user_id,
                "interaction_id": interaction.interaction_id,
            },
        )

        return TicketActionResponse(
            interaction_id=interaction.interaction_id,
            ticket_id=ticket_id,
            message=f"Ticket transferred to {new_agent.name}.",
            created_at=interaction.created_at,
        )

    # ---------------------------------------------------------
    # Claim Ticket
    # ---------------------------------------------------------

    async def claim_ticket(
        self,
        ticket_id: UUID,
        current_user: User,
    ) -> TicketActionResponse:
        """
        Lets an agent pick up an unclaimed open ticket from the
        shared pool — the CEO's "team members can pick any ticket"
        model. Ownership of the client relationship stays with the
        Account Manager; this only records who is currently working
        the ticket.

        Race-guarded at the repository level: if two agents claim
        the same ticket at once, exactly one succeeds and the other
        gets a 409 rather than silently overwriting the winner.
        """

        ticket = await self._get_ticket_or_404(ticket_id)
        ensure_ticket_not_closed(ticket)

        if ticket.agent_id is not None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="This ticket has already been claimed.",
            )

        claimed = await self.ticket_repository.claim(ticket, current_user.user_id)

        if claimed is None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="This ticket has already been claimed by another agent.",
            )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        interaction = await self._create_ticket_interaction(
            ticket_id=ticket_id,
            interaction_type="CLAIM",
            direction=InteractionDirection.INTERNAL,
            payload={
                "agent_id": str(current_user.user_id),
                "agent_name": current_user.name,
            },
            performed_by=actor_id,
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.AGENT_TRANSFERRED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"agent_id": None},
            new_values={
                "agent_id": current_user.user_id,
                "interaction_id": interaction.interaction_id,
            },
        )

        return TicketActionResponse(
            interaction_id=interaction.interaction_id,
            ticket_id=ticket_id,
            message=f"Ticket claimed by {current_user.name}.",
            created_at=interaction.created_at,
        )

    # ---------------------------------------------------------
    # Pending Inbox Item Actions (claim / archive)
    # ---------------------------------------------------------

    async def _ensure_can_act_on_pending_interaction(
        self,
        interaction: Interaction,
        current_user: User,
    ) -> None:
        """
        Thin wrapper around the shared access_control check — kept as
        a method since every call site in this class already calls
        `self._ensure_can_act_on_pending_interaction(...)`.
        """

        await ensure_agent_can_view_pending_interaction(
            interaction, current_user, self.client_repository
        )

    async def claim_interaction(
        self,
        interaction_id: UUID,
        current_user: User,
    ) -> InteractionClaimResponse:
        """
        Lets an agent pick up an unclaimed, unticketed pending inbox
        item — "Assign to me". Distinct from claim_ticket: this acts
        on a pre-ticket Interaction (the shared inbox pool), which has
        no agent_id-equivalent column — InteractionRepository.claim
        guards on the new claimed_by column instead, with the same
        atomic race-guard shape as the ticket-level version.
        """

        interaction = await self.interaction_repository.get_by_id(interaction_id)

        if interaction is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        if interaction.ticket_id is not None:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="This item has already become a ticket.",
            )

        await self._ensure_can_act_on_pending_interaction(interaction, current_user)

        claimed = await self.interaction_repository.claim(
            interaction, current_user.user_id
        )

        if claimed is None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="This item has already been claimed by someone else.",
            )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await AuditLogService.log_event(
            self.interaction_repository.db,
            entity_type=AuditEntityType.INTERACTION,
            entity_id=claimed.interaction_id,
            event_type=AuditEventType.INTERACTION_CLAIMED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"claimed_by": None},
            new_values={"claimed_by": current_user.user_id},
        )

        return InteractionClaimResponse(
            interaction_id=claimed.interaction_id,
            claimed_by=claimed.claimed_by,
            claimed_by_name=current_user.name,
            claimed_at=claimed.claimed_at,
            message=f"Assigned to {current_user.name}.",
        )

    async def archive_interaction(
        self,
        interaction_id: UUID,
        current_user: User,
    ) -> InteractionArchiveResponse:
        """
        The "Informational / Archive" reviewer decision: store the
        communication, no ticket, no work assignment — still
        searchable later under the inbox's "archived" view.
        """

        interaction = await self.interaction_repository.get_by_id(interaction_id)

        if interaction is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        if interaction.ticket_id is not None:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="This item has already become a ticket.",
            )

        await self._ensure_can_act_on_pending_interaction(interaction, current_user)

        archived = await self.interaction_repository.archive(interaction)

        if archived is None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="This item is no longer pending.",
            )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await AuditLogService.log_event(
            self.interaction_repository.db,
            entity_type=AuditEntityType.INTERACTION,
            entity_id=archived.interaction_id,
            event_type=AuditEventType.INTERACTION_ARCHIVED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"status": InteractionStatus.PENDING},
            new_values={"status": InteractionStatus.IGNORED},
        )

        return InteractionArchiveResponse(
            interaction_id=archived.interaction_id,
            status=archived.status,
            message="Archived.",
        )

    async def snooze_interaction(
        self,
        interaction_id: UUID,
        request: SnoozeRequest,
        current_user: User,
    ) -> InteractionSnoozeResponse:
        """
        Hides a pending, unticketed inbox item from the "pending"
        view until `request.snooze_until` — it resurfaces on its own,
        no background job needed, since every read just compares
        against `now()`.
        """

        snooze_until = request.snooze_until
        interaction = await self.interaction_repository.get_by_id(interaction_id)

        if interaction is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        if interaction.ticket_id is not None:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="This item has already become a ticket.",
            )

        await self._ensure_can_act_on_pending_interaction(interaction, current_user)

        snoozed = await self.interaction_repository.snooze(interaction, snooze_until)

        if snoozed is None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="This item is no longer pending.",
            )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await AuditLogService.log_event(
            self.interaction_repository.db,
            entity_type=AuditEntityType.INTERACTION,
            entity_id=snoozed.interaction_id,
            event_type=AuditEventType.INTERACTION_SNOOZED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"snoozed_until": None},
            new_values={"snoozed_until": snooze_until.isoformat()},
        )

        return InteractionSnoozeResponse(
            interaction_id=snoozed.interaction_id,
            snoozed_until=snoozed.snoozed_until,
            message=f"Snoozed until {snooze_until.isoformat()}.",
        )

    async def unsnooze_interaction(
        self,
        interaction_id: UUID,
        current_user: User,
    ) -> InteractionSnoozeResponse:
        """
        Clears an active snooze early, returning the item to
        "pending" immediately.
        """

        interaction = await self.interaction_repository.get_by_id(interaction_id)

        if interaction is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        await self._ensure_can_act_on_pending_interaction(interaction, current_user)

        unsnoozed = await self.interaction_repository.unsnooze(interaction)

        if unsnoozed is None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="This item isn't currently snoozed.",
            )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await AuditLogService.log_event(
            self.interaction_repository.db,
            entity_type=AuditEntityType.INTERACTION,
            entity_id=unsnoozed.interaction_id,
            event_type=AuditEventType.INTERACTION_UNSNOOZED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"snoozed_until": "..."},
            new_values={"snoozed_until": None},
        )

        return InteractionSnoozeResponse(
            interaction_id=unsnoozed.interaction_id,
            snoozed_until=None,
            message="Unsnoozed.",
        )

    async def set_interaction_tags(
        self,
        interaction_id: UUID,
        request: TagsUpdateRequest,
        current_user: User,
    ) -> InteractionTagsResponse:
        """
        Full-replaces the tag list on a mail item. Not race-guarded
        like claim/archive/snooze — tagging isn't a contested "only
        one winner" action, and it stays available regardless of
        ticket/claim state (unlike those, which stop being valid once
        the item leaves the pending pool).
        """

        interaction = await self.interaction_repository.get_by_id(interaction_id)

        if interaction is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        await self._ensure_can_act_on_pending_interaction(interaction, current_user)

        old_tags = list(interaction.tags)
        updated = await self.interaction_repository.set_tags(interaction, request.tags)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await AuditLogService.log_event(
            self.interaction_repository.db,
            entity_type=AuditEntityType.INTERACTION,
            entity_id=updated.interaction_id,
            event_type=AuditEventType.INTERACTION_TAGGED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"tags": old_tags},
            new_values={"tags": updated.tags},
        )

        return InteractionTagsResponse(
            interaction_id=updated.interaction_id,
            tags=updated.tags,
            message="Tags updated.",
        )

    async def set_interaction_folder(
        self,
        interaction_id: UUID,
        request: FolderAssignRequest,
        current_user: User,
    ) -> InteractionFolderResponse:
        """
        Files (or unfiles, if `request.folder_id` is None) a mail item
        into a custom folder. Orthogonal to status — available
        regardless of pending/replied/ticketed/archived state, same
        reasoning as tags.
        """

        interaction = await self.interaction_repository.get_by_id(interaction_id)

        if interaction is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        await self._ensure_can_act_on_pending_interaction(interaction, current_user)

        folder_id = request.folder_id

        if folder_id is not None and self.mail_folder_repository is not None:
            folder = await self.mail_folder_repository.get_by_id(folder_id)
            if folder is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail="Folder not found.",
                )

        old_folder_id = interaction.folder_id
        updated = await self.interaction_repository.set_folder(interaction, folder_id)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await AuditLogService.log_event(
            self.interaction_repository.db,
            entity_type=AuditEntityType.INTERACTION,
            entity_id=updated.interaction_id,
            event_type=AuditEventType.INTERACTION_FOLDER_CHANGED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"folder_id": old_folder_id},
            new_values={"folder_id": updated.folder_id},
        )

        return InteractionFolderResponse(
            interaction_id=updated.interaction_id,
            folder_id=updated.folder_id,
            message="Folder updated.",
        )

    # ---------------------------------------------------------
    # Drafts
    # ---------------------------------------------------------

    async def _resolve_pending_thread_root(
        self,
        interaction_id: UUID,
    ) -> Interaction:
        """
        Resolves any id within a bare (pre-ticket) Mail thread — the
        root itself, one of its replies, or a draft — up to the
        thread root, same walk-up as `add_interaction_reply`. Shared
        by the draft save/send/discard actions below, which all key
        off "the current thread", not the specific id a client
        happened to pass. 404s on a missing id, 400s if the thread
        has already become a ticket (drafts, like the rest of Mail,
        are pre-ticket only — see `add_interaction_reply`'s own
        matching guard for already-ticketed threads).
        """

        interaction = await self.interaction_repository.get_by_id(interaction_id)

        if interaction is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        root_id = interaction.parent_interaction_id or interaction.interaction_id
        root = (
            interaction
            if interaction.parent_interaction_id is None
            else await self.interaction_repository.get_by_id(root_id)
        )

        if root is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        if root.ticket_id is not None:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="This interaction already belongs to a ticket — use the ticket reply endpoint.",
            )

        return root

    async def save_draft(
        self,
        interaction_id: UUID,
        request: DraftSaveRequest,
        current_user: User,
    ) -> DraftResponse:
        """
        Upserts current_user's draft reply on this thread — one
        active draft per thread per agent, overwritten (not
        versioned) on every save.
        """

        root = await self._resolve_pending_thread_root(interaction_id)
        await self._ensure_can_act_on_pending_interaction(root, current_user)

        existing = await self.interaction_repository.get_draft(
            root.interaction_id, current_user.user_id
        )

        if existing is not None:
            draft = await self.interaction_repository.update_draft_message(
                existing, request.message
            )
        else:
            draft = await self.interaction_repository.create(
                InteractionCreate(
                    ticket_id=None,
                    interaction_type="REPLY",
                    direction=InteractionDirection.OUTBOUND,
                    status=InteractionStatus.PENDING,
                    performed_by=current_user.user_id,
                    payload={"message": request.message, "dispatch_status": "DRAFT"},
                    is_visible=True,
                    client_id=root.client_id,
                    parent_interaction_id=root.interaction_id,
                    is_draft=True,
                )
            )

        return DraftResponse(
            interaction_id=draft.interaction_id,
            root_interaction_id=root.interaction_id,
            message=request.message,
            created_at=draft.created_at,
        )

    async def send_draft(
        self,
        interaction_id: UUID,
        current_user: User,
    ) -> InteractionReplyResponse:
        """
        Sends current_user's draft on this thread — converts it into
        a real reply by deleting the draft row and handing its saved
        text to `add_interaction_reply`, which builds the same
        envelope/dispatch/audit trail a normal reply would get. There
        is deliberately no separate "draft becomes a reply" code path
        to keep that logic in exactly one place.
        """

        root = await self._resolve_pending_thread_root(interaction_id)
        await self._ensure_can_act_on_pending_interaction(root, current_user)

        draft = await self.interaction_repository.get_draft(
            root.interaction_id, current_user.user_id
        )

        if draft is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="No draft found on this thread.",
            )

        message = draft.payload.get("message", "") if isinstance(draft.payload, dict) else ""

        await self.interaction_repository.delete_draft(draft)

        return await self.add_interaction_reply(
            interaction_id=root.interaction_id,
            request=InteractionReplyRequest(message=message),
            current_user=current_user,
        )

    async def discard_draft(
        self,
        interaction_id: UUID,
        current_user: User,
    ) -> DraftDeleteResponse:
        """Deletes current_user's draft on this thread without sending it."""

        root = await self._resolve_pending_thread_root(interaction_id)
        await self._ensure_can_act_on_pending_interaction(root, current_user)

        draft = await self.interaction_repository.get_draft(
            root.interaction_id, current_user.user_id
        )

        if draft is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="No draft found on this thread.",
            )

        await self.interaction_repository.delete_draft(draft)

        return DraftDeleteResponse(message="Draft discarded.")

    # ---------------------------------------------------------
    # Hide / Delete Interaction
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # Thread Fetch — Outlook-style "open the conversation"
    # ---------------------------------------------------------

    async def get_thread(
        self,
        interaction_id: UUID,
        current_user: User,
    ) -> ThreadResponse:
        """
        Resolves any id within a conversation — the root itself, or
        any reply filed under it — up to the thread root, then
        returns that root plus every reply, oldest first. Access is
        gated the same way the rest of Mail/Tickets already are: a
        still-pending (pre-ticket) thread uses the Account-Manager-
        ownership-or-global-inbox check; a ticketed thread uses the
        same category/ownership gate as the ticket timeline.
        """

        interaction = await self.interaction_repository.get_by_id(interaction_id)

        if interaction is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        root_id = interaction.parent_interaction_id or interaction.interaction_id
        root = (
            interaction
            if interaction.parent_interaction_id is None
            else await self.interaction_repository.get_by_id(root_id)
        )

        if root is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        if root.ticket_id is not None:
            ticket = await self._get_ticket_or_404(root.ticket_id)
            ensure_agent_can_view_ticket(ticket, current_user)
        else:
            await self._ensure_can_act_on_pending_interaction(root, current_user)

        replies = await self.interaction_repository.list_thread(root.interaction_id)

        return ThreadResponse(
            root=_to_response(root),
            replies=[_to_response(reply) for reply in replies],
            reply_count=len(replies),
            latest_reply=_to_response(replies[-1]) if replies else None,
        )

    async def hide_interaction(
        self,
        ticket_id: UUID,
        interaction_id: UUID,
        request: HideInteractionRequest,
        current_user: User,
    ) -> HideInteractionResponse:
        """
        Soft-deletes (hides) an interaction that
        belongs to the given ticket.
        """

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        interaction = await self.interaction_repository.get_by_id(
            interaction_id
        )

        if interaction is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        if interaction.ticket_id != ticket_id:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Interaction does not belong to this ticket.",
            )

        if not interaction.is_visible:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Interaction is already hidden.",
            )

        interaction = await self.interaction_repository.hide(
            interaction,
            removed_by=request.removed_by or actor_id,
        )

        await AuditLogService.log_event(
            self.interaction_repository.db,
            entity_type=AuditEntityType.INTERACTION,
            entity_id=interaction.interaction_id,
            event_type=AuditEventType.INTERACTION_HIDDEN,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"is_visible": True},
            new_values={
                "is_visible": False,
                "ticket_id": interaction.ticket_id,
                "removed_at": interaction.removed_at,
            },
        )

        return HideInteractionResponse(
            interaction_id=interaction.interaction_id,
            ticket_id=interaction.ticket_id,
            is_visible=interaction.is_visible,
            removed_by=interaction.removed_by,
            removed_at=interaction.removed_at,
            message="Interaction hidden successfully.",
        )