import logging
from datetime import datetime, timezone

from fastapi import UploadFile

from app.enums import (
    ActorRole,
    AuditEntityType,
    AuditEventType,
    InteractionDirection,
    InteractionStatus,
)
from app.repositories.client_repository import ClientRepository
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.user_repository import UserRepository
from app.schemas.attachment import AttachmentMetadata
from app.schemas.email import (
    EmailRequest,
    EmailResponse,
)
from app.schemas.interaction import (
    InteractionCreate,
)
from app.services.access_control import ACCOUNT_MANAGER_ROLE_NAME
from app.services.attachment_service import (
    AttachmentService,
    attachments_to_metadata,
)
from app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


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
    Resolve Client (by the shared inbox address it arrived at,
    NOT by matching the sender to a platform user)
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
    ):
        self.interaction_repository = interaction_repository
        self.client_repository = client_repository
        self.attachment_service = attachment_service
        self.user_repository = user_repository

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
        # Client Lookup — by the shared inbox address this
        # email arrived at, not by who sent it.
        # ---------------------------------------

        client = await self.client_repository.get_active_by_inbox_email(
            email.to_email
        )

        if client is None:
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
        # already covers visibility in the meantime.
        if self.user_repository is not None:
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
            # the conversation it's actually replying to.
            parent_interaction_id = (
                matched.parent_interaction_id or matched.interaction_id
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

            "client_id": str(client.client_id),

            "client_name": client.name,

            "to_email": email.to_email,

            "from_email": email.from_email,

            "from_name": email.from_name,

            "subject": email.subject,

            "body": email.body,

            "html_body": email.html_body,

            "in_reply_to": email.in_reply_to,

            "references": email.references,
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

    client_id=client.client_id,

    parent_interaction_id=parent_interaction_id,

    received_at=received_at,

    conversation_id=email.conversation_id,

    in_reply_to_message_id=email.in_reply_to,

    references=email.references or None,
)

        created = (
            await self.interaction_repository
            .create(interaction)
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
                "client_id": client.client_id,
                "client_name": client.name,
                "ticket_id": ticket_id,
            },
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

            client_id=str(client.client_id),

            client_name=client.name,

            ticket_id=str(ticket_id) if ticket_id else None,

            threaded_under=(
                str(parent_interaction_id) if parent_interaction_id else None
            ),

            status=created.status.value,

            attachments=attachment_metas,
        )
