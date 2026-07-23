import logging
from datetime import datetime, timezone

from fastapi import UploadFile

from app.ticketing.enums import (
    ActorRole,
    AuditEntityType,
    AuditEventType,
    InteractionDirection,
    InteractionStatus,
)
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import (
    InteractionRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.attachment import AttachmentMetadata
from app.ticketing.schemas.email import (
    EmailRequest,
    EmailResponse,
)
from app.ticketing.schemas.interaction import (
    InteractionCreate,
)
from app.core.config import Settings, get_settings
from app.ticketing.services.access_control import (
    ACCOUNT_MANAGER_ROLE_NAME,
    GLOBAL_INBOX_ROLE_NAMES,
)
from app.ticketing.services.attachment_service import (
    AttachmentService,
    attachments_to_metadata,
)
from app.ticketing.services.audit_log_service import AuditLogService
from app.ticketing.services.sla_service import SLAService
from app.ticketing.services.sla_escalation_rules import RecipientContext, resolve_team_lead
from app.notifications.service import NotificationService, NotificationType

logger = logging.getLogger(__name__)


def is_configured_graph_mailbox(to_email: str, settings: Settings) -> bool:
    """
    True when `to_email` is the one Graph-connected shared mailbox
    configured via GRAPH_MAILBOX_ADDRESS — the mailbox this platform's
    Microsoft Graph integration actually sends from/receives into (see
    graph_client.py), which is not necessarily tied to any single
    Client.inbox_email the way every other client-specific shared
    inbox is. Used by receive_email's client-lookup fallback below:
    mail landing on this specific address is never rejected as
    "Unknown inbox address" purely for lacking a Client row — it
    routes to Site Lead instead (see the notification branch).
    """

    return bool(
        settings.graph_mailbox_address
        and to_email.strip().lower() == settings.graph_mailbox_address.strip().lower()
    )


def resolve_shared_mailbox_address(settings: Settings) -> str:
    """
    The one address every outbound Compose/Reply-with-no-inbound-thread
    is sent From — the configured Microsoft Graph shared mailbox, or a
    placeholder for local/dev environments still running
    MockMailProviderClient with no real Graph credentials set. Never
    Client.inbox_email, which stores the client's own real address
    (the one they send FROM), not an address this platform can send
    from — see build_compose_envelope's own docstring.
    """

    return settings.graph_mailbox_address or "support@probeps.com"


class EmailService:
    """
    Handles incoming emails.

    Workflow

    Receive Email
            │
            ▼
    Validate Duplicate
            │
            ▼
    Resolve Client — by the message's `from` address for mail arriving
    at the one configured Graph shared mailbox (GRAPH_MAILBOX_ADDRESS,
    where every real client sends today; see is_configured_graph_mailbox()),
    since every client shares the same `to` address there; by the
    message's `to` address for any other, legacy dedicated-inbox-per-
    client address. Either way, no matching Client is never rejected
    outright when it happened at the Graph shared mailbox — that
    routes to Site Lead instead of "Unknown inbox address."
            │
            ▼
    Thread Check (In-Reply-To / References against stored
    message_ids — lands on a ticket, joins an inbox thread, or
    becomes a new inbox item)
            │
            ▼
    Create Interaction
            │
            ▼
    Return Response

    No agent is assigned here anymore — every client's mail routes to
    the client's Account Manager (via ClientRepository), who triages
    it from their inbox; staff pick up resulting tickets from the
    shared pool instead of being auto-assigned at intake.

    Routing is always 1:1 via `client.account_manager_id` — there is
    no round-robin anywhere in this runtime path (round-robin only
    ever existed in `scripts/seed_clients.py`'s demo-data assignment,
    which has since been replaced with an explicit mapping too).
    """

    def __init__(
        self,
        interaction_repository: InteractionRepository,
        client_repository: ClientRepository,
        attachment_service: AttachmentService,
        user_repository: UserRepository | None = None,
        ticket_repository: TicketRepository | None = None,
        notification_service: NotificationService | None = None,
        sla_service: SLAService | None = None,
    ):
        self.interaction_repository = interaction_repository
        self.client_repository = client_repository
        self.attachment_service = attachment_service
        self.user_repository = user_repository
        self.ticket_repository = ticket_repository
        self.notification_service = notification_service
        self.sla_service = sla_service

    async def receive_email(
        self,
        email: EmailRequest,
        files: list[UploadFile] | None = None,
    ) -> EmailResponse:

        # ---------------------------------------
        # Duplicate Message-ID Check
        # ---------------------------------------

        exists = (
            await self.interaction_repository
            .exists_by_message_id(email.message_id)
        )

        if exists:
            raise ValueError(
                "Email already processed."
            )

        # ---------------------------------------
        # Client Lookup
        #
        # Every client now sends into the one Graph-connected shared
        # mailbox (GRAPH_MAILBOX_ADDRESS) rather than each having its
        # own dedicated arrival address, so `to_email` is the same for
        # every client and can no longer identify which one this is —
        # the sender's own address (Client.inbox_email, despite the
        # name, now stores that real personal/company address) does.
        # A legacy/dedicated-inbox-per-client address (anything other
        # than the configured shared mailbox — e.g. a still-dummy demo
        # client, or another transport that hands each client its own
        # arrival address) keeps the original to_email-based match.
        # ---------------------------------------

        settings = get_settings()
        arrived_at_shared_mailbox = is_configured_graph_mailbox(email.to_email, settings)

        if arrived_at_shared_mailbox:
            client = (
                await self.client_repository.get_active_by_inbox_email(email.from_email)
                if email.from_email
                else None
            )
        else:
            client = await self.client_repository.get_active_by_inbox_email(
                email.to_email
            )

        # The Graph-connected shared mailbox (GRAPH_MAILBOX_ADDRESS) is
        # not necessarily mapped to any one Client — unlike every other
        # inbox address, which is always a specific client's dedicated
        # address. Mail arriving there from a sender with no matching
        # Client row is never rejected as an unknown address; it's
        # routed to Site Lead instead (see the notification branch
        # further down). Everything else keeps the original,
        # unconditional rejection.
        routes_to_site_lead = client is None and arrived_at_shared_mailbox

        if client is None and not routes_to_site_lead:
            raise ValueError(
                "Unknown inbox address."
            )

        # Defense in depth: the mapped Account Manager was valid when
        # this client was onboarded (ClientService.create validates
        # it), but nothing revalidates that later — a role change or
        # deactivation leaves account_manager_id pointing at a real
        # user who no longer qualifies. Never drop/bounce real
        # customer email over this; just make it loud in the logs so
        # it gets fixed. Supervisors' existing scope=all inbox view
        # already covers visibility in the meantime. N/A when there's
        # no client at all (the Site Lead fallback above).
        if client is not None and self.user_repository is not None:
            manager = await self.user_repository.get_by_id(client.account_manager_id)
            if (
                manager is None
                or not manager.is_active
                or manager.role.name != ACCOUNT_MANAGER_ROLE_NAME
            ):
                logger.warning(
                    "Client %s (%s) has a stale account_manager_id %s — that user is "
                    "no longer an active Account Manager. Mail will only be visible "
                    "via the 'all inboxes' supervisor view until this is fixed.",
                    client.client_id,
                    client.inbox_email,
                    client.account_manager_id,
                )

        received_at = email.received_at or datetime.now(timezone.utc)

        # ---------------------------------------
        # Thread Check — priority order: conversation_id (Graph's own
        # thread id, once Task 1 ships) -> in_reply_to -> references.
        # First tier that resolves to a stored interaction wins; we
        # don't merge candidates from lower tiers once a higher one
        # matches, so a conversation_id match can't be second-guessed
        # by an unrelated References entry.
        # ---------------------------------------

        matched = None

        if email.conversation_id:
            conversation_matches = await self.interaction_repository.get_by_conversation_id(
                email.conversation_id
            )
            if conversation_matches:
                matched = conversation_matches[0]

        if matched is None and email.in_reply_to:
            in_reply_to_matches = await self.interaction_repository.get_by_message_ids(
                [email.in_reply_to]
            )
            if in_reply_to_matches:
                matched = in_reply_to_matches[0]

        if matched is None and email.references:
            reference_matches = await self.interaction_repository.get_by_message_ids(
                email.references
            )
            if reference_matches:
                matched = reference_matches[0]

        ticket_id = None
        parent_interaction_id = None
        interaction_status = InteractionStatus.PENDING

        if matched is not None:
            # Walk to the thread root either way, so every reply in a
            # thread points at the same root, not a chain of parents
            # — without this, a follow-up email lands with
            # parent_interaction_id NULL and shows up as a brand-new,
            # duplicate root in the AM inbox instead of nesting under
            # the conversation it's actually replying to. A recursive
            # resolve (InteractionRepository.find_thread_root) rather
            # than a single hop — `matched` is usually already a root
            # by this point (this same flattening keeps it that way),
            # but resolving correctly regardless of depth is what
            # actually keeps the invariant true rather than assuming it.
            root = await self.interaction_repository.find_thread_root(
                matched.interaction_id
            )
            parent_interaction_id = (
                root.interaction_id if root is not None else matched.interaction_id
            )

            if matched.ticket_id is not None:
                # The match already lives on a ticket — this reply
                # joins that ticket's timeline directly.
                ticket_id = matched.ticket_id
                interaction_status = InteractionStatus.ASSIGNED

        # ---------------------------------------
        # Build Interaction Payload
        # ---------------------------------------

        payload = {

            "client_id": str(client.client_id) if client is not None else None,

            "client_name": client.name if client is not None else None,

            "to_email": email.to_email,

            "from_email": email.from_email,

            "from_name": email.from_name,

            "subject": email.subject,

            "body": email.body,

            "html_body": email.html_body,

            "in_reply_to": email.in_reply_to,

            "references": email.references,

            # Graph's own native message id (None for the N8N
            # transport, which has no such concept) — unused today,
            # kept for a future native reply/replyAll/forward or
            # Sent-Items reconciliation feature. See
            # EmailRequest.provider_message_id's own docstring.
            "provider_message_id": email.provider_message_id,
        }

        # ---------------------------------------
        # Convert Email → Interaction
        # ---------------------------------------

        interaction = InteractionCreate(

    ticket_id=ticket_id,

    interaction_type="EMAIL",

    status=interaction_status,

    direction=InteractionDirection.INBOUND,

    # No authenticated user exists yet.
    # The email has only been received.
    # The client information is stored inside payload.
    performed_by=None,

    payload=payload,

    is_visible=True,

    message_id=email.message_id,

    client_id=client.client_id if client is not None else None,

    parent_interaction_id=parent_interaction_id,

    received_at=received_at,

    conversation_id=email.conversation_id,

    in_reply_to_message_id=email.in_reply_to,

    references=email.references or None,

    subject=email.subject,
)

        created = (
            await self.interaction_repository
            .create(interaction)
        )

        # ---------------------------------------
        # SLA
        #
        # A genuinely new thread root (matched is None, so
        # parent_interaction_id stayed None) starts a First Response
        # clock — never a reply threading onto an existing pending
        # item or ticket, which would otherwise double-clock the same
        # conversation (see the plan doc's gap #7). A reply that
        # landed directly on an existing ticket (ticket_id is not
        # None) instead resumes that ticket's Resolution clock if it
        # was paused — independent of whether the ticket's status
        # label has been changed back off WAITING_FOR_CLIENT yet (gap
        # #4's customer-driven resume path).
        # ---------------------------------------

        if self.sla_service is not None:
            if parent_interaction_id is None and ticket_id is None:
                await self.sla_service.start_first_response_clock(interaction=created)
            elif ticket_id is not None:
                await self.sla_service.resume_resolution_clock(
                    ticket_id=ticket_id,
                    triggering_interaction_id=created.interaction_id,
                )

        # ---------------------------------------
        # Audit Trail — the client is the actor here,
        # not an assigning agent (there is none anymore).
        # ---------------------------------------

        await AuditLogService.log_event(
            self.interaction_repository.db,
            entity_type=AuditEntityType.INTERACTION,
            entity_id=created.interaction_id,
            event_type=AuditEventType.EMAIL_RECEIVED,
            actor_id=None,
            actor_name=email.from_name or email.from_email,
            actor_role=ActorRole.CLIENT,
            new_values={
                "subject": email.subject,
                "message_id": email.message_id,
                "client_id": client.client_id if client is not None else None,
                "client_name": client.name if client is not None else None,
                "ticket_id": ticket_id,
            },
        )

        # ---------------------------------------
        # Notifications
        #
        # Three distinct audiences: a brand-new pending item on a
        # client's own inbox goes to that client's Account Manager
        # plus the always-global Site Lead/Super Admin inboxes; a
        # brand-new item with no Client at all (the Graph-mailbox
        # fallback above — routes_to_site_lead) goes to Site Lead only,
        # since there's no Account Manager to notify; a reply on an
        # already-ticketed thread goes to whoever is actually working
        # that ticket (its assigned agent), not the AM.
        # ---------------------------------------

        if self.notification_service is not None:
            if ticket_id is None:
                if client is not None:
                    recipient_ids = {client.account_manager_id}
                    mail_source_label = client.name
                else:
                    # routes_to_site_lead: no Client, so no Account
                    # Manager to seed the recipient set with — Site Lead
                    # (added via GLOBAL_INBOX_ROLE_NAMES just below) is
                    # the only audience.
                    recipient_ids = set()
                    mail_source_label = f"the {email.to_email} mailbox"

                if self.user_repository is not None:
                    for role_name in GLOBAL_INBOX_ROLE_NAMES:
                        global_inbox_users = await self.user_repository.list_active_by_role_name(
                            role_name
                        )
                        recipient_ids.update(u.user_id for u in global_inbox_users)

                await self.notification_service.notify(
                    recipient_ids,
                    NotificationType.MAIL_RECEIVED,
                    title=f"New mail from {mail_source_label}",
                    message=email.subject or "(no subject)",
                    link="/inbox",
                    related_entity_type="interaction",
                    related_entity_id=created.interaction_id,
                )
            elif self.ticket_repository is not None:
                ticket = await self.ticket_repository.get_by_id(ticket_id)

                if ticket is not None and ticket.agent_id is not None:
                    reply_recipient_ids = {ticket.agent_id}

                    # Also notify the agent's own Team Lead — matches
                    # Team Lead's "Replies" notification bullet.
                    # Deliberately not fanned out to Site Lead/Super
                    # Admin here too: every single client reply would
                    # flood their bell at any real ticket volume (see
                    # this repo's CLAUDE.md on the notification
                    # hierarchy's scope decisions).
                    if self.user_repository is not None:
                        assigned_agent = await self.user_repository.get_by_id(ticket.agent_id)
                        team_lead_ctx = RecipientContext(assigned_agent=assigned_agent)
                        reply_recipient_ids |= resolve_team_lead(team_lead_ctx)

                    # client can be None here too (a Graph-mailbox-
                    # fallback message that happened to thread onto an
                    # existing ticket's own ticketed conversation) —
                    # the ticket's own client relationship, not this
                    # possibly-absent lookup, is the source of truth
                    # for who the ticket belongs to.
                    reply_source_label = client.name if client is not None else "the client"

                    await self.notification_service.notify(
                        reply_recipient_ids,
                        NotificationType.CLIENT_REPLY,
                        title=f"New reply from {reply_source_label}",
                        message=email.subject or "(no subject)",
                        link=f"/tickets/{ticket_id}",
                        related_entity_type="ticket",
                        related_entity_id=ticket_id,
                    )

        # ---------------------------------------
        # Attachments (optional)
        # ---------------------------------------

        attachment_metas: list[AttachmentMetadata] = []

        if files:
            attachments = await self.attachment_service.validate_and_store_files(
                files, created.interaction_id
            )
            attachment_metas = await attachments_to_metadata(
                attachments, self.attachment_service.storage_service
            )

        # ---------------------------------------
        # Response
        # ---------------------------------------

        return EmailResponse(

            message="Email received successfully.",

            interaction_id=str(
                created.interaction_id
            ),

            client_id=str(client.client_id) if client is not None else None,

            client_name=client.name if client is not None else None,

            ticket_id=str(ticket_id) if ticket_id else None,

            threaded_under=(
                str(parent_interaction_id) if parent_interaction_id else None
            ),

            status=created.status.value,

            attachments=attachment_metas,
        )
