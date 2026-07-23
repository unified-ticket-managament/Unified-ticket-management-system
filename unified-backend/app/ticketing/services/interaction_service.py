# interaction_service.py


import asyncio
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, UploadFile
from fastapi import status as http_status
from sqlalchemy.exc import IntegrityError

from shared_models.models import User

from app.core.config import get_settings
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import (
    InteractionRepository,
)
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.ticket_edit_access_repository import (
    TicketEditAccessRequestRepository,
)
from app.ticketing.repositories.ticket_repository import (
    TicketRepository,
)
from app.ticketing.repositories.user_repository import UserRepository
from app.notifications.service import NotificationService, NotificationType
from app.ticketing.schemas.interaction import (
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
    InteractionTagsResponse,
    InteractionUpdate,
    TagsUpdateRequest,
    ThreadResponse,
)
from app.ticketing.schemas.note import (
    InternalNoteCreate,
    InternalNoteResponse,
)
from app.ticketing.schemas.ticket import TicketUpdate
from app.ticketing.schemas.ticket_action import (
    InteractionReplyRequest,
    InteractionReplyResponse,
    PriorityChangeRequest,
    ReplyCreate,
    StatusChangeRequest,
    TicketActionResponse,
    TransferAgentRequest,
)
from app.ticketing.repositories.audit_log_repository import AuditLogRepository
from app.ticketing.schemas.audit_log import AuditLogResponse
from app.ticketing.services.access_control import (
    ACCOUNT_MANAGER_ROLE_NAME,
    GLOBAL_INBOX_ROLE_NAMES,
    SITE_LEAD_ROLE_NAME,
    SUPER_ADMIN_ROLE_NAME,
    SUPERVISOR_ROLE_NAMES,
    TEAM_LEAD_TRANSFER_ROLE_NAMES,
    ensure_account_manager_owns_ticket_client,
    ensure_agent_can_act_on_ticket,
    ensure_agent_can_view_pending_interaction,
    ensure_agent_can_view_ticket,
    ensure_can_close_ticket,
    ensure_can_compose_for_client,
    ensure_can_reassign_ticket,
    ensure_can_reopen_ticket,
    ensure_has_permission,
    ensure_ticket_not_closed,
    ensure_ticket_not_frozen_by_escalation,
)
from app.ticketing.services.audit_log_service import AuditLogService
from app.ticketing.services.audit_to_interaction import (
    SYNTHESIZABLE_EVENT_TYPES,
    synthesize_interaction_from_audit,
)
from app.ticketing.services.email_envelope import build_compose_envelope, build_reply_envelope
from app.ticketing.services.email_service import resolve_shared_mailbox_address
from app.ticketing.services.escalation_service import EscalationService
from app.ticketing.services.interaction_summary import trim_payload_for_list
from app.ticketing.services.outbound_dispatcher import OutboundDispatchError, OutboundDispatcher
from app.ticketing.services.sla_escalation_rules import TEAM_LEAD_ROLE_NAME
from app.ticketing.services.sla_service import SLAService
from app.ticketing.services.sla_escalation_rules import (
    RecipientContext,
    resolve_account_manager,
    resolve_assigned_agent,
    resolve_team_lead,
)

from app.ticketing.enums import (
    AuditEntityType,
    AuditEventType,
    InteractionDirection,
    InteractionStatus,
    TicketStatus,
)

from typing import Any
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.schemas.attachment import AttachmentMetadata
from app.ticketing.schemas.compose import ComposeEmailRequest, ComposeEmailResponse
from app.ticketing.schemas.payloads import EmailPayload, OutboundEnvelope
from app.ticketing.services.attachment_service import AttachmentService, attachments_to_metadata
from app.ticketing.storage.base import StorageService


def _to_response(
    interaction: Interaction,
    attachments: list[AttachmentMetadata] | None = None,
    performed_by_name: str | None = None,
    trim: bool = False,
) -> InteractionResponse:
    """
    Builds an InteractionResponse without touching
    `interaction.attachments` — that relationship is lazy and
    unloaded on every query in this file, so letting pydantic's
    from_attributes machinery read it directly would trigger an
    unawaited lazy load. Callers that need real attachments (the
    ticket timeline) fetch them separately and pass them in.

    `trim=True` (used only by the list-view timeline) keeps just the
    handful of payload keys the frontend's summarize() actually reads
    for this row's type, instead of the full payload — see
    interaction_summary.trim_payload_for_list.
    """

    return InteractionResponse(
        interaction_id=interaction.interaction_id,
        ticket_id=interaction.ticket_id,
        interaction_type=interaction.interaction_type,
        status=interaction.status,
        direction=interaction.direction,
        performed_by=interaction.performed_by,
        performed_by_name=performed_by_name,
        payload=trim_payload_for_list(interaction) if trim else interaction.payload,
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
        edit_access_repository: TicketEditAccessRequestRepository | None = None,
        notification_service: NotificationService | None = None,
        sla_service: SLAService | None = None,
        escalation_service: EscalationService | None = None,
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
        self.edit_access_repository = edit_access_repository
        self.notification_service = notification_service
        self.sla_service = sla_service
        self.escalation_service = escalation_service

    def _escalation_handling_sla_repository_or_none(self):
        """
        Threaded into ensure_agent_can_act_on_ticket alongside the
        escalation repository below so the freeze check can tell
        "acknowledged" apart from "actually accepted (assigned)" — see
        that function's own docstring. Reached through
        escalation_service rather than constructed directly here,
        since EscalationService already owns/builds one.
        """

        if self.escalation_service is None:
            return None
        return getattr(
            self.escalation_service.escalation_handling_sla_service,
            "escalation_handling_sla_repository",
            None,
        )

    async def _resolve_ticket_stakeholder_ids(
        self,
        ticket,
        exclude_user_id: UUID | None = None,
    ) -> set[UUID]:
        """
        "Who has a stake in this ticket" for the core ticket-lifecycle
        notification triggers (status change, priority change,
        resolution, internal note added) — the ticket's own assigned
        agent, that agent's Team Lead, and the client's Account
        Manager. Reuses the exact recipient-resolver functions the SLA
        sweep already established (sla_escalation_rules.py) instead of
        re-deriving the same hierarchy traversal a second time.
        `exclude_user_id` drops whoever performed the action, so an
        actor never gets notified about their own change.
        """

        client = None
        if self.client_repository is not None and ticket.client_company_id is not None:
            client = await self.client_repository.get_by_id(ticket.client_company_id)

        assigned_agent = None
        if ticket.agent_id is not None:
            assigned_agent = await self.user_repository.get_by_id(ticket.agent_id)

        ctx = RecipientContext(client=client, assigned_agent=assigned_agent)
        ids = resolve_account_manager(ctx) | resolve_team_lead(ctx) | resolve_assigned_agent(ctx)
        if exclude_user_id is not None:
            ids.discard(exclude_user_id)
        return ids

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
        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )

        interactions = (
            await self.interaction_repository
            .list_by_ticket_id(ticket_id)
        )

        # This list view never renders attachments or full payload
        # text directly — only the click-to-open thread/email detail
        # does, via a separate endpoint that keeps doing full
        # signing — so skip the per-attachment signed-URL generation
        # and full JSONB payload that used to make this slow.
        performer_ids = [
            i.performed_by for i in interactions if i.performed_by is not None
        ]
        names_by_id = await self.user_repository.get_names_by_ids(performer_ids)

        rows = [
            _to_response(
                interaction,
                performed_by_name=(
                    names_by_id.get(interaction.performed_by)
                    if interaction.performed_by is not None
                    else None
                ),
                trim=True,
            )
            for interaction in interactions
        ]

        # STATUS_CHANGE/PRIORITY_CHANGE/AGENT_TRANSFER/CLAIM/EDIT_ACCESS_*
        # no longer get their own Interaction row (see
        # audit_to_interaction.py) — synthesize a display row back
        # from the ticket_audit_logs entry each of those actions
        # still writes, so the Timeline keeps showing every one of
        # them exactly as before.
        if self.audit_log_repository is not None:
            audit_logs = await self.audit_log_repository.list_by_ticket(ticket_id)
            synthetic_rows = [
                synthesize_interaction_from_audit(log, ticket_id, ticket.title)
                for log in audit_logs
                if log.event_type in SYNTHESIZABLE_EVENT_TYPES
            ]
            rows.extend(synthetic_rows)

        rows.sort(key=lambda item: item.created_at)

        return rows

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
        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )
        ensure_has_permission(current_user, "ticket:view_audit_trail")

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

    async def _dispatch_and_record(
        self, interaction: Interaction, envelope: OutboundEnvelope
    ) -> None:
        """
        Calls OutboundDispatcher.dispatch() and updates the
        already-persisted interaction's dispatch_status to the two
        states outbound_dispatcher.py's own docstring always intended
        it to reach: "SENT" (with the real provider_message_id) or
        "FAILED" (with an error message), instead of staying "QUEUED"
        forever. Shared by every reply/compose call site so real Graph
        delivery is wired in exactly once.

        On failure, the FAILED status is committed explicitly before
        raising — get_db()'s own dependency wrapper rolls back the
        whole request's session on any exception, which would
        otherwise silently undo this write (and the interaction's own
        creation) along with it, defeating the point of keeping a
        failed send visible to the agent rather than vanishing it.
        """

        try:
            result = await self.outbound_dispatcher.dispatch(
                interaction.interaction_id, envelope
            )
        except OutboundDispatchError as exc:
            failed_payload = {
                **interaction.payload,
                "dispatch_status": "FAILED",
                "dispatch_error": str(exc),
            }
            await self.interaction_repository.update(
                interaction, InteractionUpdate(payload=failed_payload)
            )
            await self.interaction_repository.db.commit()

            raise HTTPException(
                status_code=http_status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to send email: {exc}",
            ) from exc

        sent_payload = {
            **interaction.payload,
            "dispatch_status": "SENT",
            "provider_message_id": result.provider_message_id,
        }
        await self.interaction_repository.update(
            interaction, InteractionUpdate(payload=sent_payload)
        )

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
        subject: str | None = None,
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

                subject=subject,

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
        await ensure_agent_can_act_on_ticket(
            ticket,
            current_user,
            self.edit_access_repository,
            self.escalation_service.ticket_escalation_repository
            if self.escalation_service is not None
            else None,
            self._escalation_handling_sla_repository_or_none(),
        )
        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )
        ensure_has_permission(current_user, "ticket:reply")
        ensure_has_permission(current_user, "communication:reply_internal")

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
            subject=request.subject,
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

        if self.notification_service is not None:
            stakeholder_ids = await self._resolve_ticket_stakeholder_ids(
                ticket, exclude_user_id=current_user.user_id
            )
            if stakeholder_ids:
                await self.notification_service.notify(
                    stakeholder_ids,
                    NotificationType.INTERNAL_NOTE_ADDED,
                    title="A new internal note was added",
                    message=f"{ticket.title}: {request.subject}",
                    link=f"/tickets/{ticket_id}",
                    related_entity_type="ticket",
                    related_entity_id=ticket_id,
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
        await ensure_agent_can_act_on_ticket(
            ticket,
            current_user,
            self.edit_access_repository,
            self.escalation_service.ticket_escalation_repository
            if self.escalation_service is not None
            else None,
            self._escalation_handling_sla_repository_or_none(),
        )
        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )
        ensure_has_permission(current_user, "ticket:reply")
        ensure_has_permission(current_user, "communication:reply_external")

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        # The latest inbound email on this ticket is both the envelope
        # source (recipient address, In-Reply-To) and the thread this
        # reply belongs to — resolved once, used for both, regardless
        # of whether envelope-building succeeds. Resolved to the true
        # root via a recursive walk-up (InteractionRepository
        # .find_thread_root), not a single hop, for the same reason
        # as get_thread/add_interaction_reply — see that method's
        # docstring.
        latest_email = await self.interaction_repository.get_latest_inbound_email_for_ticket(
            ticket_id
        )
        thread_root_id = None
        if latest_email is not None:
            root = await self.interaction_repository.find_thread_root(
                latest_email.interaction_id
            )
            thread_root_id = (
                root.interaction_id if root is not None else latest_email.interaction_id
            )

        envelope = None
        if latest_email is not None:
            inbound_payload = EmailPayload.model_validate(latest_email.payload)

            client = None
            if self.client_repository is not None and ticket.client_company_id is not None:
                client = await self.client_repository.get_by_id(ticket.client_company_id)

            # A reply always goes From the address the original message
            # arrived AT (the shared support mailbox), whether or not
            # a Client resolved for this ticket — never Client.inbox_email,
            # which now stores the client's own real address (the one
            # they send FROM, used to identify them on inbound), not an
            # address this platform can send from. This also covers the
            # ticket-with-no-resolvable-Client case (e.g. one created
            # from a Graph-mailbox Site Lead fallback message — see
            # email_service.is_configured_graph_mailbox()) for free,
            # since inbound_payload.to_email is populated either way.
            am_email = await self._resolve_account_manager_email(client) if client is not None else None
            reply_from_email = inbound_payload.to_email

            if reply_from_email:
                envelope = build_reply_envelope(
                    from_email=reply_from_email,
                    inbound_payload=inbound_payload,
                    inbound_message_id=latest_email.message_id,
                    body=request.message,
                    agent_name=current_user.name,
                    account_manager_email=am_email,
                    cc=request.cc,
                    bcc=request.bcc,
                    to_email_override=request.to_email,
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
            subject=latest_email.subject if latest_email is not None else None,
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
            await self._dispatch_and_record(interaction, envelope)

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

        # Resolve the thread root: replying on a reply (or a deeply
        # nested descendant) should still thread under the original
        # conversation, not fork a new one. A recursive CTE
        # (InteractionRepository.find_thread_root) — correct at any
        # nesting depth, see that method's own docstring.
        root = await self.interaction_repository.find_thread_root(interaction_id)

        if root is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        # This is the client-facing "reply on a not-yet-ticketed
        # communication" action — previously had no authorization check
        # of any kind (not even the pending-interaction visibility
        # scoping every other pending-interaction action already has).
        await self._ensure_can_act_on_pending_interaction(root, current_user)
        ensure_has_permission(current_user, "communication:reply_external")

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        inbound_payload = EmailPayload.model_validate(root.payload)

        client = None
        if self.client_repository is not None and root.client_id is not None:
            client = await self.client_repository.get_by_id(root.client_id)

        # A reply always goes From the address the original message
        # arrived AT (the shared support mailbox), whether or not this
        # thread has a resolved Client — never Client.inbox_email, which
        # now stores the client's own real address (the one they send
        # FROM, used to identify them on inbound), not an address this
        # platform can send from. This also covers a client-less thread
        # (the Graph-mailbox Site Lead fallback — see
        # email_service.is_configured_graph_mailbox()) for free, since
        # inbound_payload.to_email is populated either way.
        am_email = await self._resolve_account_manager_email(client) if client is not None else None
        reply_from_email = inbound_payload.to_email

        envelope = None
        if reply_from_email:
            envelope = build_reply_envelope(
                from_email=reply_from_email,
                inbound_payload=inbound_payload,
                inbound_message_id=root.message_id,
                body=request.message,
                agent_name=current_user.name,
                account_manager_email=am_email,
                cc=request.cc,
                bcc=request.bcc,
                to_email_override=request.to_email,
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
                subject=root.subject,
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
            await self._dispatch_and_record(interaction, envelope)

        # The root leaves the Pending triage queue once it's been
        # replied to — "general communication, no ticket needed" is
        # now handled, not waiting on anyone.
        if root.status == InteractionStatus.PENDING:
            await self.interaction_repository.update(
                root, InteractionUpdate(status=InteractionStatus.ASSIGNED)
            )

        if self.sla_service is not None:
            await self.sla_service.complete_first_response_clock(
                interaction_id=root.interaction_id,
                completion_reason="REPLIED",
            )

        return InteractionReplyResponse(
            interaction_id=interaction.interaction_id,
            parent_interaction_id=root.interaction_id,
            message=request.message,
            created_at=interaction.created_at,
        )

    # ---------------------------------------------------------
    # Compose — brand-new outbound email, no prior thread
    # ---------------------------------------------------------

    async def compose_email(
        self,
        request: ComposeEmailRequest,
        current_user: User,
    ) -> ComposeEmailResponse:
        """
        Authors a brand-new outbound email to one of the platform's
        clients — the one Mail action with no existing interaction to
        reply onto. Creates a new thread ROOT (interaction_type=
        "EMAIL", direction=OUTBOUND, parent_interaction_id=NULL,
        ticket_id=NULL) rather than reusing add_interaction_reply,
        which always requires an existing root to thread under.

        Stored with the same envelope/dispatch_status shape a reply
        gets (see build_compose_envelope) so it renders through the
        exact same Mail UI/thread-open code path afterward — nothing
        downstream needs to know a message started life as a Compose
        rather than a Reply.
        """

        if self.client_repository is None:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Client lookup is not available.",
            )

        client = await self.client_repository.get_by_id(request.client_id)

        if client is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Client not found.",
            )

        ensure_can_compose_for_client(client, current_user)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        am_email = await self._resolve_account_manager_email(client)
        shared_mailbox_address = resolve_shared_mailbox_address(get_settings())

        envelope = build_compose_envelope(
            from_email=shared_mailbox_address,
            to_email=request.to_email,
            subject=request.subject,
            body=request.message,
            cc=request.cc,
            bcc=request.bcc,
            agent_name=current_user.name,
            account_manager_email=am_email,
        )

        email_payload = EmailPayload(
            client_id=client.client_id,
            client_name=client.name,
            to_email=request.to_email,
            from_email=shared_mailbox_address,
            from_name=current_user.name,
            subject=request.subject,
            body=request.message,
            cc=request.cc,
            bcc=request.bcc,
        )

        interaction = await self.interaction_repository.create(
            InteractionCreate(
                ticket_id=None,
                interaction_type="EMAIL",
                direction=InteractionDirection.OUTBOUND,
                status=InteractionStatus.ASSIGNED,
                performed_by=actor_id,
                payload={
                    **email_payload.model_dump(mode="json"),
                    "envelope": envelope.model_dump(),
                    "dispatch_status": "QUEUED",
                },
                is_visible=True,
                message_id=envelope.message_id,
                client_id=client.client_id,
                parent_interaction_id=None,
                received_at=datetime.now(timezone.utc),
                subject=request.subject,
            )
        )

        await AuditLogService.log_event(
            self.interaction_repository.db,
            entity_type=AuditEntityType.INTERACTION,
            entity_id=interaction.interaction_id,
            # Reuses REPLY_ADDED rather than adding a new
            # AuditEventType member — that enum is a native Postgres
            # ENUM (see CLAUDE.md's "Postgres-enum migration gotcha"),
            # widening it needs a standalone migration against the
            # live DB. A Compose send is, audit-wise, the same kind of
            # event as a reply: an outbound communication was
            # recorded.
            event_type=AuditEventType.REPLY_ADDED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={"client_id": client.client_id, "to_email": request.to_email},
        )

        await self._dispatch_and_record(interaction, envelope)

        return ComposeEmailResponse(
            interaction_id=interaction.interaction_id,
            client_id=client.client_id,
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

        # A closed ticket is read-only, including via this generic
        # status-change route — Reopen Ticket (a dedicated, permission-
        # gated action, see reopen_ticket below) is now the only way
        # off CLOSED. This used to be exempt specifically so a plain
        # status change could reopen a ticket; that carve-out is gone
        # now that a real Reopen action exists.
        ensure_ticket_not_closed(ticket)
        await ensure_agent_can_act_on_ticket(
            ticket,
            current_user,
            self.edit_access_repository,
            self.escalation_service.ticket_escalation_repository
            if self.escalation_service is not None
            else None,
            self._escalation_handling_sla_repository_or_none(),
        )
        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )
        ensure_has_permission(current_user, "ticket:update_status")

        old_status = ticket.current_status
        old_closed_at = ticket.closed_at
        new_status = request.new_status

        # Closing must go through the dedicated Close Ticket action
        # (close_ticket below) — never this generic status-change
        # route — so it gets its own TICKET_CLOSED audit event,
        # closed_by stamp, and confirmation-dialog UX instead of being
        # just another status value.
        if new_status == TicketStatus.CLOSED:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Closing a ticket must be done via the Close Ticket action, not a status change.",
            )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        # Resolving a ticket stamps `closed_at`; moving off RESOLVED
        # clears it back to None — this is the single place that ever
        # sets or clears it for a non-CLOSED transition (close_ticket/
        # reopen_ticket own the CLOSED case now).
        was_closed = old_status == TicketStatus.RESOLVED
        will_be_closed = new_status == TicketStatus.RESOLVED

        update_fields: dict[str, Any] = {"current_status": new_status}
        if not was_closed and will_be_closed:
            update_fields["closed_at"] = datetime.now(timezone.utc)
        elif was_closed and not will_be_closed:
            update_fields["closed_at"] = None

        await self.ticket_repository.update(
            ticket,
            TicketUpdate(**update_fields),
        )

        # No longer written as an Interaction row — STATUS_CHANGE is
        # one of the retired timeline-only types (see
        # services/audit_to_interaction.py); the AuditLog row below is
        # its sole record now, and the Timeline/Interactions-list
        # endpoints synthesize a display row back from it.
        old_values: dict[str, Any] = {"current_status": old_status}
        new_values: dict[str, Any] = {"current_status": new_status}
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

        # ---------------------------------------------------------
        # Resolution SLA — pause/resume key off this chokepoint,
        # matching this repo's existing "change_status is the one place
        # status transitions happen" principle. Entering CLOSED is no
        # longer reachable through this method at all (see the gate
        # above) — close_ticket below still completes the clock too,
        # but for a ticket that already Resolved first, that later call
        # is a harmless no-op (see complete_resolution_clock's own
        # docstring) since this is the one that actually completes it.
        # ---------------------------------------------------------

        if self.sla_service is not None:
            if (
                new_status == TicketStatus.WAITING_FOR_CLIENT
                and old_status != TicketStatus.WAITING_FOR_CLIENT
            ):
                # STATUS_CHANGE no longer creates an Interaction row
                # (see the AuditLog-only note above) — there's nothing
                # to point triggering_interaction_id at anymore.
                await self.sla_service.pause_resolution_clock(
                    ticket_id=ticket_id,
                    reason="WAITING_FOR_CLIENT_STATUS",
                    triggering_interaction_id=None,
                )
                await AuditLogService.log_event(
                    self.ticket_repository.db,
                    entity_type=AuditEntityType.TICKET,
                    entity_id=ticket_id,
                    event_type=AuditEventType.SLA_PAUSED,
                    actor_id=actor_id,
                    actor_name=actor_name,
                    actor_role=actor_role,
                    new_values={"reason": "WAITING_FOR_CLIENT_STATUS"},
                )
            elif (
                old_status == TicketStatus.WAITING_FOR_CLIENT
                and new_status != TicketStatus.WAITING_FOR_CLIENT
            ):
                await self.sla_service.resume_resolution_clock(
                    ticket_id=ticket_id,
                    triggering_interaction_id=None,
                )
                if new_status in (TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED):
                    await AuditLogService.log_event(
                        self.ticket_repository.db,
                        entity_type=AuditEntityType.TICKET,
                        entity_id=ticket_id,
                        event_type=AuditEventType.SLA_RESUMED,
                        actor_id=actor_id,
                        actor_name=actor_name,
                        actor_role=actor_role,
                        new_values={"new_status": new_status.value},
                    )

            if not was_closed and will_be_closed:
                # Runs after the WAITING_FOR_CLIENT resume branch above
                # (not before) — a ticket resolved directly out of
                # WAITING_FOR_CLIENT must genuinely resume first (so
                # SLA_RESUMED's audit log stays accurate) and only then
                # complete, rather than completing against a clock
                # that's still PAUSED and making that resume call a
                # silent no-op behind a misleading audit row. The
                # Resolution SLA measures time-to-resolve, so it
                # completes the instant the ticket reaches RESOLVED,
                # not only once a supervisor later formally Closes it
                # for customer verification. close_escalation=False:
                # the separate internal escalation/ownership workflow
                # is untouched by this transition, only by an actual
                # Close (see close_for_ticket_resolution).
                await self.sla_service.complete_resolution_clock(
                    ticket_id=ticket_id, close_escalation=False
                )

        if self.notification_service is not None:
            stakeholder_ids = await self._resolve_ticket_stakeholder_ids(
                ticket, exclude_user_id=current_user.user_id
            )
            if stakeholder_ids:
                # A transition into RESOLVED fires TICKET_RESOLVED
                # instead of the generic TICKET_STATUS_CHANGED — not
                # both, so the same transition never produces two
                # notifications for one event. CLOSED can no longer be
                # reached through this method at all (see the gate
                # above) — close_ticket has its own audit event but no
                # notify trigger yet, same as reopen_ticket.
                if will_be_closed and not was_closed:
                    await self.notification_service.notify(
                        stakeholder_ids,
                        NotificationType.TICKET_RESOLVED,
                        title="A ticket was resolved",
                        message=ticket.title,
                        link=f"/tickets/{ticket_id}",
                        related_entity_type="ticket",
                        related_entity_id=ticket_id,
                    )
                else:
                    await self.notification_service.notify(
                        stakeholder_ids,
                        NotificationType.TICKET_STATUS_CHANGED,
                        title="A ticket's status changed",
                        message=f"{ticket.title}: {old_status.value} → {new_status.value}",
                        link=f"/tickets/{ticket_id}",
                        related_entity_type="ticket",
                        related_entity_id=ticket_id,
                    )

        return TicketActionResponse(
            interaction_id=None,
            ticket_id=ticket_id,
            message="Ticket status updated successfully.",
            created_at=datetime.now(timezone.utc),
        )

    # ---------------------------------------------------------
    # Close Ticket
    # ---------------------------------------------------------

    async def close_ticket(
        self,
        ticket_id: UUID,
        current_user: User,
    ) -> TicketActionResponse:
        """
        Closes a ticket — the only transition that completes the
        Resolution SLA clock. Split out of change_status into its own
        action (own permission gate, own audit event, own closed_by
        stamp) rather than treating CLOSED as just another status
        value.
        """

        ticket = await self._get_ticket_or_404(ticket_id)
        ensure_ticket_not_closed(ticket)
        await ensure_agent_can_act_on_ticket(
            ticket,
            current_user,
            self.edit_access_repository,
            self.escalation_service.ticket_escalation_repository
            if self.escalation_service is not None
            else None,
            self._escalation_handling_sla_repository_or_none(),
        )
        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )
        ensure_can_close_ticket(current_user)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        old_status = ticket.current_status
        old_closed_at = ticket.closed_at
        old_closed_by = ticket.closed_by
        now = datetime.now(timezone.utc)

        await self.ticket_repository.update(
            ticket,
            TicketUpdate(
                current_status=TicketStatus.CLOSED,
                closed_at=now,
                closed_by=current_user.user_id,
            ),
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.TICKET_CLOSED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={
                "current_status": old_status,
                "closed_at": old_closed_at,
                "closed_by": old_closed_by,
            },
            new_values={
                "current_status": TicketStatus.CLOSED,
                "closed_at": now,
                "closed_by": current_user.user_id,
                "closed_by_name": current_user.name,
            },
        )

        # Same Resolution SLA chokepoint change_status used to drive
        # for a CLOSED target: unpause first if the ticket happened to
        # be WAITING_FOR_CLIENT (so complete_resolution_clock below runs
        # against a correctly-unpaused clock), then complete it. No
        # separate SLA_RESUMED audit row here, matching change_status's
        # own prior behavior for this exact transition.
        if self.sla_service is not None:
            if old_status == TicketStatus.WAITING_FOR_CLIENT:
                await self.sla_service.resume_resolution_clock(
                    ticket_id=ticket_id,
                    triggering_interaction_id=None,
                )
            await self.sla_service.complete_resolution_clock(ticket_id=ticket_id)

        return TicketActionResponse(
            interaction_id=None,
            ticket_id=ticket_id,
            message="Ticket closed successfully.",
            created_at=now,
        )

    # ---------------------------------------------------------
    # Reopen Ticket
    # ---------------------------------------------------------

    async def reopen_ticket(
        self,
        ticket_id: UUID,
        current_user: User,
    ) -> TicketActionResponse:
        """
        Reopens a closed ticket, restoring it to OPEN and clearing
        closed_at/closed_by. This is the only way off CLOSED now that
        change_status refuses the transition (see ensure_ticket_not_closed
        there) — every other action's own ensure_ticket_not_closed guard
        starts working again for this ticket the instant this completes.
        """

        ticket = await self._get_ticket_or_404(ticket_id)

        if ticket.current_status != TicketStatus.CLOSED:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Only a closed ticket can be reopened.",
            )

        await ensure_agent_can_act_on_ticket(
            ticket,
            current_user,
            self.edit_access_repository,
            self.escalation_service.ticket_escalation_repository
            if self.escalation_service is not None
            else None,
            self._escalation_handling_sla_repository_or_none(),
        )
        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )
        ensure_can_reopen_ticket(current_user)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        old_closed_at = ticket.closed_at
        old_closed_by = ticket.closed_by

        await self.ticket_repository.update(
            ticket,
            TicketUpdate(
                current_status=TicketStatus.OPEN,
                closed_at=None,
                closed_by=None,
            ),
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.TICKET_REOPENED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={
                "current_status": TicketStatus.CLOSED,
                "closed_at": old_closed_at,
                "closed_by": old_closed_by,
            },
            new_values={
                "current_status": TicketStatus.OPEN,
                "closed_at": None,
                "closed_by": None,
            },
        )

        # Deliberately does NOT touch the Resolution SLA clock:
        # SLAService.create_or_resume_resolution_clock's own docstring
        # is explicit that a COMPLETED clock is never resurrected
        # ("never resurrect a clock on a closed ticket"), and closing
        # this ticket already completed it (see close_ticket above).
        # Reopening restores the ticket's own workflow state — edit
        # capability, replies, status/priority changes, transfer — but
        # not a past SLA measurement or the internal escalation
        # workflow (if one was closed alongside the original
        # completion); a future breach on the reopened ticket would
        # create a new escalation rather than resuming the old one.

        return TicketActionResponse(
            interaction_id=None,
            ticket_id=ticket_id,
            message="Ticket reopened successfully.",
            created_at=datetime.now(timezone.utc),
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
        # ensure_agent_can_view_ticket/ensure_account_manager_owns_ticket_client
        # were previously missing here — change_priority deliberately
        # skips the assigned-agent-only check (ensure_agent_can_act_on_ticket)
        # per its own docstring ("any permission holder can change
        # priority on any ticket in their visibility scope"), but the
        # visibility-scope half of that sentence was never actually
        # enforced: a Team Lead/Staff granted ticket:change_priority via
        # override could reach a ticket outside their own category, and
        # an Account Manager could reach any client's ticket.
        ensure_agent_can_view_ticket(ticket, current_user)
        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )
        # A narrower check than ensure_agent_can_act_on_ticket — this
        # method deliberately keeps its own ownership-skipping design
        # (see above), it only additionally refuses to run while the
        # ticket is frozen by an unaccepted escalation, same as every
        # other mutating action.
        await ensure_ticket_not_frozen_by_escalation(
            ticket,
            self.escalation_service.ticket_escalation_repository
            if self.escalation_service is not None
            else None,
            self._escalation_handling_sla_repository_or_none(),
        )
        ensure_has_permission(current_user, "ticket:change_priority")

        old_priority = ticket.current_priority

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await self.ticket_repository.update(
            ticket,
            TicketUpdate(current_priority=request.new_priority),
        )

        # No longer written as an Interaction row — PRIORITY_CHANGE is
        # one of the retired timeline-only types (see
        # services/audit_to_interaction.py); the AuditLog row below is
        # its sole record now.
        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.PRIORITY_CHANGED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"current_priority": old_priority},
            new_values={"current_priority": request.new_priority},
        )

        if self.sla_service is not None:
            await self.sla_service.reshift_resolution_clock_for_priority_change(
                ticket_id=ticket_id,
                new_priority=request.new_priority,
            )

        if self.notification_service is not None:
            stakeholder_ids = await self._resolve_ticket_stakeholder_ids(
                ticket, exclude_user_id=current_user.user_id
            )
            if stakeholder_ids:
                await self.notification_service.notify(
                    stakeholder_ids,
                    NotificationType.TICKET_PRIORITY_CHANGED,
                    title="A ticket's priority changed",
                    message=f"{ticket.title}: {old_priority.value} → {request.new_priority.value}",
                    link=f"/tickets/{ticket_id}",
                    related_entity_type="ticket",
                    related_entity_id=ticket_id,
                )

        return TicketActionResponse(
            interaction_id=None,
            ticket_id=ticket_id,
            message="Ticket priority updated successfully.",
            created_at=datetime.now(timezone.utc),
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
        # Previously missing: transfer_agent had no category/client
        # visibility check at all, only the role/permission gate below
        # — a Team Lead could transfer a ticket outside their own
        # category, and an Account Manager could reach any client's
        # ticket. The approved matrix scopes ticket:transfer to "team"
        # for Team Lead and "own clients" for Account Manager.
        ensure_agent_can_view_ticket(ticket, current_user)
        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )
        ensure_can_reassign_ticket(current_user)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        # Resolved once, up front, since both the widened candidate
        # check below and the pre-existing category guard need to know
        # whether this ticket is actively escalated right now.
        active_escalation = None
        if self.escalation_service is not None:
            active_escalation = (
                await self.escalation_service.ticket_escalation_repository.get_active_by_ticket_id(
                    ticket_id
                )
            )

        # Set whenever the candidate was resolved via a branch below
        # that already loaded the full row with role+category eager-
        # loaded (Team Lead, Site Lead, Account Manager, or self) — the
        # Staff category guard further down reuses it instead of a
        # second round trip.
        new_agent_full: User | None = None
        # True for every supervisor-tier target (self, Team Lead, Site
        # Lead, Account Manager) — none of these roles are scoped to a
        # work-specialization category the way Staff is (see
        # CATEGORY_SCOPED_ROLE_NAMES), so the Staff-only category check
        # below never applies to them.
        skip_category_check = False

        # Self-assignment: a Team Lead/Account Manager/Site Lead/Super
        # Admin assigning the ticket to *themselves*. Always valid,
        # unconditionally — they already own/are handling this
        # escalation/ticket by virtue of being the one making the call
        # (ensure_can_reassign_ticket above already authorized them to
        # act at all), so none of the "transfer to some other named
        # agent" candidate rules below apply. Previously this fell
        # through to the Staff-only / TEAM_LEAD_TRANSFER_ROLE_NAMES
        # branches below and was rejected outright — e.g. a Team Lead
        # selecting "Myself" was checked against "is the *caller* an
        # Account Manager/Site Lead/Super Admin transferring *to* a
        # Team Lead", which a Team Lead assigning to themselves can
        # never satisfy.
        if (
            request.new_agent_id == current_user.user_id
            and current_user.role.name in SUPERVISOR_ROLE_NAMES
            and current_user.is_active
        ):
            new_agent = current_user
            new_agent_full = current_user
            skip_category_check = True
        else:
            new_agent = await self.user_repository.get_active_staff_by_id(
                request.new_agent_id
            )

        if new_agent is None:
            candidate = await self.user_repository.get_by_id(request.new_agent_id)
            if candidate is not None and candidate.is_active:
                if (
                    candidate.role.name == TEAM_LEAD_ROLE_NAME
                    and current_user.role.name in TEAM_LEAD_TRANSFER_ROLE_NAMES
                ):
                    # Business rule (root CLAUDE.md's Organization
                    # Structure section): every Account Manager (and
                    # Site Lead/Super Admin) can hand a ticket directly
                    # to ANY Team Lead, regardless of department — the
                    # Account Manager decides which category should own
                    # it, so this is deliberately NOT scoped to the
                    # ticket's own ticket_type, unlike the Staff target
                    # check below. Allowed both during and outside an
                    # active escalation — this is the ordinary
                    # AM-assigns-to-Team-Lead workflow, not just the
                    # escalation acceptance path.
                    new_agent = candidate
                    new_agent_full = candidate
                    skip_category_check = True
                elif (
                    candidate.role.name == SITE_LEAD_ROLE_NAME
                    and current_user.role.name == SUPER_ADMIN_ROLE_NAME
                ):
                    # Only Super Admin may hand a ticket directly to a
                    # Site Lead (see the Acknowledge & Assign role
                    # table) — Site Lead is otherwise never a transfer
                    # target, including for itself via this branch
                    # (self-assignment is covered above).
                    new_agent = candidate
                    new_agent_full = candidate
                    skip_category_check = True
                elif (
                    active_escalation is not None
                    and candidate.role.name == ACCOUNT_MANAGER_ROLE_NAME
                    and current_user.role.name in GLOBAL_INBOX_ROLE_NAMES
                    and self.escalation_service is not None
                ):
                    # An actively-escalated ticket's "who owns it going
                    # forward" can legitimately be an Account Manager,
                    # but only when a Site Lead/Super Admin is the one
                    # assigning it (see the Acknowledge & Assign role
                    # table — Account Manager itself never hands a
                    # ticket to another Account Manager, and Team Lead
                    # never reaches this branch at all). Re-validated
                    # against the exact same candidate set
                    # EscalationService.get_acknowledge_candidates
                    # offers the caller — every Account Manager who is
                    # a Reporting Manager for the ticket's category
                    # (ReportingManagerTeam) — rather than trusting the
                    # submitted id alone, and rather than duplicating a
                    # second, independently-drifting definition of
                    # "valid Account Manager" here.
                    if await self.escalation_service.is_valid_account_manager_target(
                        ticket, candidate.user_id
                    ):
                        new_agent = candidate
                        new_agent_full = candidate
                        skip_category_check = True

        if new_agent is None:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=(
                    "New agent must be an active Staff member, an "
                    "active Team Lead when transferred by an Account "
                    "Manager, Site Lead, or Super Admin, an active "
                    "Account Manager when transferred by a Site Lead "
                    "or Super Admin during an active escalation, an "
                    "active Site Lead when transferred by a Super "
                    "Admin, or the caller themselves."
                ),
            )

        if ticket.agent_id == new_agent.user_id:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Ticket is already assigned to this agent.",
            )

        # A Staff target must belong to the ticket's own work-
        # specialization category (mirrors ensure_agent_can_view_ticket's
        # own category gate) — per the Organization Structure business
        # rule, a Team Lead must never be able to hand a ticket to
        # another category's Staff, escalated or not. This used to only
        # be enforced during an active escalation; it's unconditional
        # now. Doesn't apply to a supervisor-tier target
        # (skip_category_check above, deliberately unscoped by category
        # per that same rule — Team Lead/Site Lead/Account Manager/
        # self are none of them category-scoped roles).
        if not skip_category_check:
            if new_agent_full is None:
                new_agent_full = await self.user_repository.get_by_id(new_agent.user_id)
            new_agent_category = (
                new_agent_full.category.category_name.value
                if new_agent_full is not None and new_agent_full.category is not None
                else None
            )
            if new_agent_category != ticket.ticket_type:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="This staff member is not part of the ticket's category.",
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

        # No longer written as an Interaction row — AGENT_TRANSFER is
        # one of the retired timeline-only types (see
        # services/audit_to_interaction.py); the AuditLog row below is
        # its sole record now, and the Timeline/Interactions-list
        # endpoints synthesize a display row back from it. Agent
        # names are logged here (not just ids) precisely so that
        # synthesis is a pure JSON remap, with no extra name lookup.
        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.AGENT_TRANSFERRED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={
                "agent_id": old_agent_id,
                "agent_name": old_agent_name,
            },
            new_values={
                "agent_id": new_agent.user_id,
                "agent_name": new_agent.name,
                "reason": request.reason,
            },
        )

        if self.notification_service is not None:
            await self.notification_service.notify(
                new_agent.user_id,
                NotificationType.TICKET_ASSIGNED,
                title="A ticket was assigned to you",
                message=ticket.title,
                link=f"/tickets/{ticket_id}",
                related_entity_type="ticket",
                related_entity_id=ticket_id,
            )

            # Also notify the hierarchy that owns this ticket/agent —
            # the client's Account Manager and the new agent's own
            # Team Lead — so assignment/reassignment is visible beyond
            # just the new assignee. Reuses the same recipient-
            # resolution primitives the SLA sweep already established
            # rather than re-deriving them a second time.
            client = None
            if self.client_repository is not None and ticket.client_company_id is not None:
                client = await self.client_repository.get_by_id(ticket.client_company_id)
            new_agent_with_role = await self.user_repository.get_by_id(new_agent.user_id)
            stakeholder_ctx = RecipientContext(client=client, assigned_agent=new_agent_with_role)
            stakeholder_ids = (
                resolve_account_manager(stakeholder_ctx) | resolve_team_lead(stakeholder_ctx)
            ) - {new_agent.user_id}
            if stakeholder_ids:
                await self.notification_service.notify(
                    stakeholder_ids,
                    NotificationType.TICKET_ASSIGNED,
                    title="A ticket was reassigned" if old_agent_id is not None else "A ticket was assigned",
                    message=f"{ticket.title} — assigned to {new_agent.name}",
                    link=f"/tickets/{ticket_id}",
                    related_entity_type="ticket",
                    related_entity_id=ticket_id,
                )

        # Assigning an escalated ticket is treated as accepting it —
        # same rule a literal Acknowledge click follows, applied here
        # so a supervisor who assigns before ever clicking Acknowledge
        # doesn't leave the escalation stuck waiting on a separate step.
        # No-ops entirely if there's no active escalation, and is
        # idempotent if the escalation was already acknowledged — see
        # EscalationService.acknowledge_via_assignment's own docstring.
        if self.escalation_service is not None:
            await self.escalation_service.acknowledge_via_assignment(
                ticket_id, current_user
            )

        return TicketActionResponse(
            interaction_id=None,
            ticket_id=ticket_id,
            message=f"Ticket transferred to {new_agent.name}.",
            created_at=datetime.now(timezone.utc),
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

        # No longer written as an Interaction row — CLAIM is one of
        # the retired timeline-only types (see
        # services/audit_to_interaction.py); the AuditLog row below is
        # its sole record now. `agent_name` is logged here so the
        # Timeline/Interactions-list synthesis stays a pure JSON
        # remap, with no extra name lookup.
        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.TICKET_CLAIMED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"agent_id": None},
            new_values={
                "agent_id": current_user.user_id,
                "agent_name": current_user.name,
            },
        )

        # Claiming an escalated (unclaimed) ticket is exactly the same
        # "took ownership" act transfer_agent's own call below is —
        # without this, a supervisor who acknowledges an unclaimed
        # escalation and then assigns it to *themselves* via Claim
        # (rather than the Transfer picker) would never start the
        # Resolution SLA/handling SLA at all. No-ops entirely if there's
        # no active escalation on this ticket.
        if self.escalation_service is not None:
            await self.escalation_service.acknowledge_via_assignment(
                ticket_id, current_user
            )

        return TicketActionResponse(
            interaction_id=None,
            ticket_id=ticket_id,
            message=f"Ticket claimed by {current_user.name}.",
            created_at=datetime.now(timezone.utc),
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
        ensure_has_permission(current_user, "communication:archive")

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

        if self.sla_service is not None:
            await self.sla_service.complete_first_response_clock(
                interaction_id=archived.interaction_id,
                completion_reason="ARCHIVED",
            )

        return InteractionArchiveResponse(
            interaction_id=archived.interaction_id,
            status=archived.status,
            message="Archived.",
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
        root itself, a reply, a draft, or a deeply nested descendant —
        up to the thread root (InteractionRepository.find_thread_root,
        a recursive CTE — see that method's own docstring for why this
        is correct at any nesting depth, unlike a single-hop walk-up).
        Shared by the draft save/send/discard actions below, which all
        key off "the current thread", not the specific id a client
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

        root = await self.interaction_repository.find_thread_root(interaction_id)

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

    async def _get_or_create_draft(
        self,
        root: Interaction,
        current_user: User,
        message: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> Interaction:
        """
        Fetches current_user's existing draft on this thread, or
        creates an empty one — shared by save_draft (always has real
        text to save) and upload_draft_attachment (may run before the
        user has typed anything yet, e.g. attaching a file first).

        The frontend calls save_draft continuously (debounced) as the
        user types, so two near-simultaneous requests can both reach
        this method, both find no existing draft, and both attempt to
        create one — a check-then-insert race.
        ix_interactions_one_draft_per_thread_per_agent (a partial unique
        index on (parent_interaction_id, performed_by) WHERE is_draft
        AND is_visible) makes the LOSING insert fail with IntegrityError
        rather than silently creating a second row; caught here and
        re-fetched so the loser just returns the winner's draft instead
        of failing that request.
        """

        existing = await self.interaction_repository.get_draft(
            root.interaction_id, current_user.user_id
        )
        if existing is not None:
            return existing

        try:
            async with self.interaction_repository.db.begin_nested():
                return await self.interaction_repository.create(
                    InteractionCreate(
                        ticket_id=None,
                        interaction_type="REPLY",
                        direction=InteractionDirection.OUTBOUND,
                        status=InteractionStatus.PENDING,
                        performed_by=current_user.user_id,
                        payload={
                            "message": message,
                            "cc": cc or [],
                            "bcc": bcc or [],
                            "dispatch_status": "DRAFT",
                        },
                        is_visible=True,
                        client_id=root.client_id,
                        parent_interaction_id=root.interaction_id,
                        is_draft=True,
                    )
                )
        except IntegrityError:
            existing = await self.interaction_repository.get_draft(
                root.interaction_id, current_user.user_id
            )
            if existing is not None:
                return existing
            raise

    async def _fetch_draft_attachments(
        self, interaction_id: UUID
    ) -> list[AttachmentMetadata]:
        if self.attachment_repository is None or self.storage_service is None:
            return []

        raw = await self.attachment_repository.list_by_interaction_id(interaction_id)
        return await attachments_to_metadata(raw, self.storage_service)

    async def save_draft(
        self,
        interaction_id: UUID,
        request: DraftSaveRequest,
        current_user: User,
    ) -> DraftResponse:
        """
        Upserts current_user's draft reply on this thread — one
        active draft per thread per agent, overwritten (not
        versioned) on every save. Called continuously (debounced) by
        the frontend as the user edits To/Cc/Bcc/Subject/Body, so the
        draft never falls behind what's on screen.
        """

        root = await self._resolve_pending_thread_root(interaction_id)
        await self._ensure_can_act_on_pending_interaction(root, current_user)

        existing = await self.interaction_repository.get_draft(
            root.interaction_id, current_user.user_id
        )

        if existing is not None:
            draft = await self.interaction_repository.update_draft_message(
                existing, request.message, cc=request.cc, bcc=request.bcc
            )
        else:
            draft = await self._get_or_create_draft(
                root,
                current_user,
                message=request.message,
                cc=request.cc,
                bcc=request.bcc,
            )

        attachments = await self._fetch_draft_attachments(draft.interaction_id)

        return DraftResponse(
            interaction_id=draft.interaction_id,
            root_interaction_id=root.interaction_id,
            message=request.message,
            cc=request.cc,
            bcc=request.bcc,
            attachments=attachments,
            created_at=draft.created_at,
        )

    async def upload_draft_attachment(
        self,
        interaction_id: UUID,
        files: list[UploadFile],
        current_user: User,
    ) -> list[AttachmentMetadata]:
        """
        Attaches files directly to current_user's in-progress draft
        on this thread. Works before the thread is ever a ticket —
        like every other attachment in this codebase (inbound email
        intake, Compose), storage is keyed on `interaction_id` alone,
        never `ticket_id` (see AttachmentService.validate_and_store_
        files) — so this needed no new storage capability, only a
        route/service seam exposing the existing one for a draft.
        Creates an empty draft row first if the user attaches a file
        before typing/saving any text yet.
        """

        if not files:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="At least one file is required.",
            )

        if self.attachment_repository is None or self.storage_service is None:
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Attachment storage is not configured.",
            )

        root = await self._resolve_pending_thread_root(interaction_id)
        await self._ensure_can_act_on_pending_interaction(root, current_user)

        draft = await self._get_or_create_draft(root, current_user)

        attachment_service = AttachmentService(
            attachment_repository=self.attachment_repository,
            interaction_repository=self.interaction_repository,
            ticket_repository=self.ticket_repository,
            storage_service=self.storage_service,
        )

        stored = await attachment_service.validate_and_store_files(
            files, draft.interaction_id
        )

        return await attachments_to_metadata(stored, self.storage_service)

    async def send_draft(
        self,
        interaction_id: UUID,
        current_user: User,
        to_email: str | None = None,
    ) -> InteractionReplyResponse:
        """
        Sends current_user's draft on this thread — hands its saved
        text/Cc/Bcc to `add_interaction_reply`, which builds the same
        envelope/dispatch/audit trail a normal reply would get (there
        is deliberately no separate "draft becomes a reply" code path
        to keep that logic in exactly one place), then repoints any
        files already uploaded against the draft onto the newly
        created reply before deleting the now-obsolete draft row —
        otherwise those attachments would be left pointing at a
        deleted interaction.

        `to_email`, when the agent picked a contact from the "To"
        dropdown at send time, overrides the default recipient — it's
        deliberately not part of the auto-saved draft payload (unlike
        message/cc/bcc), since it's only meaningful at the moment of
        sending, not while still drafting.
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

        payload = draft.payload if isinstance(draft.payload, dict) else {}
        message = payload.get("message", "")
        cc = payload.get("cc") or []
        bcc = payload.get("bcc") or []
        draft_interaction_id = draft.interaction_id

        reply = await self.add_interaction_reply(
            interaction_id=root.interaction_id,
            request=InteractionReplyRequest(
                message=message, cc=cc, bcc=bcc, to_email=to_email
            ),
            current_user=current_user,
        )

        if self.attachment_repository is not None:
            await self.attachment_repository.reassign_interaction(
                draft_interaction_id, reply.interaction_id
            )

        await self.interaction_repository.delete_draft(draft)

        return reply

    async def discard_draft(
        self,
        interaction_id: UUID,
        current_user: User,
    ) -> DraftDeleteResponse:
        """
        Deletes current_user's draft on this thread without sending
        it — including any files already uploaded against it, since a
        discarded draft's attachments would otherwise linger in
        storage with no reachable row/UI to ever clean them up.
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

        if self.attachment_repository is not None and self.storage_service is not None:
            draft_attachments = await self.attachment_repository.list_by_interaction_id(
                draft.interaction_id
            )
            for attachment in draft_attachments:
                await self.storage_service.delete(object_key=attachment.storage_key)
                await self.attachment_repository.delete(attachment)

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
        Resolves any id within a conversation — the root itself, a
        direct reply, or a deeply nested descendant — up to the
        thread root (InteractionRepository.find_thread_root, a
        recursive CTE — correct at any nesting depth, see that
        method's own docstring), then returns that root plus every
        reply at any depth (InteractionRepository.list_thread, also
        recursive), oldest first. Access is gated the same way the
        rest of Mail/Tickets already are: a still-pending (pre-ticket)
        thread uses the Account-Manager-ownership-or-global-inbox
        check; a ticketed thread uses the same category/ownership
        gate as the ticket timeline.
        """

        interaction = await self.interaction_repository.get_by_id(interaction_id)

        if interaction is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        root = await self.interaction_repository.find_thread_root(interaction_id)

        if root is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        if root.ticket_id is not None:
            ticket = await self._get_ticket_or_404(root.ticket_id)
            ensure_agent_can_view_ticket(ticket, current_user)
            await ensure_account_manager_owns_ticket_client(
                ticket, current_user, self.client_repository
            )
        else:
            await self._ensure_can_act_on_pending_interaction(root, current_user)

        ensure_has_permission(current_user, "communication:view_timeline")

        replies = await self.interaction_repository.list_thread(root.interaction_id)
        ordered = [root, *replies]

        # Batch-fetch attachments for every message in the thread, same
        # batching shape as get_ticket_interactions — each message
        # renders its own attachments, not one bucket for the root only.
        attachments_by_interaction: dict[UUID, list[AttachmentMetadata]] = {}
        if self.attachment_repository is not None and self.storage_service is not None:
            interaction_ids = [item.interaction_id for item in ordered]
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

        def _with_attachments(item):
            return _to_response(
                item, attachments_by_interaction.get(item.interaction_id)
            )

        return ThreadResponse(
            parent_interaction=_with_attachments(root),
            child_interactions=[_with_attachments(reply) for reply in replies],
            ordered_thread=[_with_attachments(item) for item in ordered],
            reply_count=len(replies),
            latest_interaction=_with_attachments(ordered[-1]),
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

        # Previously this method had NO authorization check of any
        # kind — meaning any authenticated agent could hide any
        # interaction, ticketed or not, by id. Now gated:
        # - Ticketed (ticket_id is not None): same category/client
        #   visibility scope every other ticket action uses, plus the
        #   ticket:hide_interaction permission (Full for Super Admin/
        #   Site Lead/Account Manager-own-clients, Override for Team
        #   Lead/Staff — permission-only, like ticket:change_priority,
        #   not an ownership gate).
        # - Pre-ticket (ticket_id is None — POST /interactions/{id}/hide
        #   can reach a still-pending inbox item): the existing pending-
        #   interaction gate (own-client-scope-or-supervisor), since
        #   ticket:hide_interaction is a Ticket-module permission with
        #   no pre-ticket equivalent in the approved matrix.
        if ticket_id is not None:
            ticket = await self._get_ticket_or_404(ticket_id)
            ensure_ticket_not_closed(ticket)
            ensure_agent_can_view_ticket(ticket, current_user)
            await ensure_account_manager_owns_ticket_client(
                ticket, current_user, self.client_repository
            )
            ensure_has_permission(current_user, "ticket:hide_interaction")
        else:
            pending = await self.interaction_repository.get_by_id(interaction_id)
            if pending is not None:
                await self._ensure_can_act_on_pending_interaction(pending, current_user)

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