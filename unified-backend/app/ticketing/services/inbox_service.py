import logging
from uuid import UUID

from pydantic import ValidationError
from shared_models.models import User

from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.interaction_repository import (
    InteractionRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository

from app.ticketing.schemas.inbox import (
    DraftItemResponse,
    DraftListResponse,
    InboxItemResponse,
    InboxResponse,
    SentItemResponse,
    SentResponse,
)

from app.ticketing.schemas.payloads import EmailPayload
from app.ticketing.services.access_control import (
    ACCOUNT_MANAGER_ROLE_NAME,
    GLOBAL_INBOX_ROLE_NAMES,
)

logger = logging.getLogger(__name__)


class InboxService:
    """
    Service responsible for the role-scoped Mail inbox workflow.

    Role-based visibility (Part 2/3 of the Outlook-style threading
    work — see CLAUDE.md and the propagation model it documents):
    - Site Lead / Super Admin: every thread, every client, every
      team — the global inbox. `client_id`/`scope`/`view` are the
      only narrowing knobs available to them.
    - Account Manager: only threads belonging to clients they own
      (`clients.account_manager_id`) — never every client's mail,
      there is no "all" escape hatch for this role anymore.
    - Team Lead: only threads whose ticket is filed under their own
      category — never a still-pending, pre-ticket item (those only
      belong to the owning client's Account Manager until a ticket
      exists). A Team Lead with no category assigned sees nothing,
      matching ensure_agent_can_view_ticket's own safe-failure
      convention.
    - Staff: only threads whose ticket is currently assigned to them
      — same "ticketed only" restriction as Team Lead, scoped by
      agent_id instead of category.

    Because a reply is stored once on the shared thread row (never
    duplicated per viewer), this same scoped query automatically
    picks up new replies for every role authorized to see that
    thread — there's no separate "fan out to N inboxes" step.
    """

    def __init__(
        self,
        interaction_repository: InteractionRepository,
        attachment_repository: AttachmentRepository | None = None,
        user_repository: UserRepository | None = None,
        ticket_repository: TicketRepository | None = None,
    ):
        self.interaction_repository = interaction_repository
        self.attachment_repository = attachment_repository
        self.user_repository = user_repository
        self.ticket_repository = ticket_repository

    async def get_inbox(
        self,
        current_user: User,
        client_id: UUID | None = None,
        view: str = "pending",
        scope: str = "mine",
        folder_id: UUID | None = None,
    ) -> InboxResponse:
        """
        Returns the role-scoped inbox for the current user.

        `scope`/`view="all"` only ever widens anything for Site Lead/
        Super Admin (the global-inbox roles) — for every other role
        it's ignored and their fixed scope (own clients / own
        category / own assignments) always applies, so a crafted
        request can't peek at another user's mail.
        """

        role_name = current_user.role.name

        account_manager_id: UUID | None = None
        ticket_type: str | None = None
        assigned_agent_id: UUID | None = None

        if role_name in GLOBAL_INBOX_ROLE_NAMES:
            # No filter at all when they've asked to see everything;
            # otherwise `client_id` (if provided) is the only
            # narrowing already applied below.
            pass
        elif role_name == ACCOUNT_MANAGER_ROLE_NAME:
            account_manager_id = current_user.user_id
        elif role_name == "Team Lead":
            ticket_type = (
                current_user.category.category_name.value
                if current_user.category is not None
                else "__no_category__"
            )
        elif role_name == "Staff":
            assigned_agent_id = current_user.user_id
        else:
            # Shouldn't happen — get_current_agent already blocks
            # Viewer, and every other AGENT_ROLE_NAMES member is
            # handled above. Safe fallback: scope to "owns nothing",
            # same as an Account Manager with no clients.
            account_manager_id = current_user.user_id

        interactions = await self.interaction_repository.list_inbox(
            account_manager_id=account_manager_id,
            client_id=client_id,
            view=view,
            folder_id=folder_id,
            ticket_type=ticket_type,
            assigned_agent_id=assigned_agent_id,
        )

        interactions_with_attachments: set = set()

        if self.attachment_repository is not None:
            interactions_with_attachments = (
                await self.attachment_repository
                .has_attachments_for_interactions(
                    [i.interaction_id for i in interactions]
                )
            )

        claimer_names: dict[UUID, str] = {}

        if self.user_repository is not None:
            claimer_ids = [
                i.claimed_by for i in interactions if i.claimed_by is not None
            ]
            claimer_names = await self.user_repository.get_names_by_ids(claimer_ids)

        # Outlook-style "latest message" preview per row — one batched
        # query for every root on this page rather than an N+1 fetch.
        thread_summaries = await self.interaction_repository.list_thread_summaries(
            [i.interaction_id for i in interactions]
        )

        # Priority/category only exist once a root has become a ticket
        # — one batched lookup for every ticketed row on this page
        # (mirrors thread_summaries/claimer_names above) rather than a
        # get_by_id call per row.
        tickets_by_id: dict[UUID, object] = {}
        if self.ticket_repository is not None:
            ticket_ids = [i.ticket_id for i in interactions if i.ticket_id is not None]
            tickets = await self.ticket_repository.list_by_ids(ticket_ids)
            tickets_by_id = {t.ticket_id: t for t in tickets}

        latest_sender_names: dict[UUID, str] = {}
        if self.user_repository is not None:
            performed_by_ids = [
                latest.performed_by
                for _count, latest in thread_summaries.values()
                if latest is not None and latest.performed_by is not None
            ]
            latest_sender_names = await self.user_repository.get_names_by_ids(
                performed_by_ids
            )

        def _latest_reply_preview(latest: Interaction | None) -> tuple[str | None, str | None]:
            """Returns (message_snippet, sender_label) for a thread's latest reply."""

            if latest is None:
                return None, None

            if latest.interaction_type == "REPLY":
                message = latest.payload.get("message") if isinstance(latest.payload, dict) else None
                sender = (
                    latest_sender_names.get(latest.performed_by)
                    if latest.performed_by is not None
                    else None
                ) or "Agent"
                return message, sender

            if latest.interaction_type == "EMAIL":
                # A client follow-up email chained under the root via
                # In-Reply-To/References — the "Client Reply" node in
                # the Outlook-style thread diagram.
                message = latest.payload.get("body") if isinstance(latest.payload, dict) else None
                sender = (
                    (latest.payload.get("from_name") or latest.payload.get("from_email"))
                    if isinstance(latest.payload, dict)
                    else None
                )
                return message, sender

            return None, None

        inbox_items: list[InboxItemResponse] = []

        for interaction in interactions:

            # Defense in depth: the repository query already restricts
            # "all activity" to EMAIL/REPLY rows, but a single
            # unparseable payload (e.g. stale pre-Day-1 dev data)
            # should never take down the whole inbox listing.
            try:
                payload = EmailPayload.model_validate(
                    interaction.payload
                )
            except ValidationError:
                logger.warning(
                    "Skipping interaction %s in inbox listing — payload "
                    "doesn't match EmailPayload.",
                    interaction.interaction_id,
                )
                continue

            reply_count, latest_reply = thread_summaries.get(
                interaction.interaction_id, (0, None)
            )
            latest_message, latest_sender = _latest_reply_preview(latest_reply)

            ticket = (
                tickets_by_id.get(interaction.ticket_id)
                if interaction.ticket_id is not None
                else None
            )

            inbox_items.append(

                InboxItemResponse(

                    interaction_id=interaction.interaction_id,

                    client_id=interaction.client_id,

                    client_name=payload.client_name or "Unknown",

                    from_email=payload.from_email,

                    to_email=payload.to_email,

                    subject=payload.subject,

                    message_id=interaction.message_id,

                    received_at=interaction.received_at or interaction.created_at,

                    status=interaction.status,

                    direction=interaction.direction,

                    ticket_id=interaction.ticket_id,

                    ticket_priority=ticket.current_priority if ticket is not None else None,

                    ticket_category=ticket.ticket_type if ticket is not None else None,

                    has_attachments=(
                        interaction.interaction_id in interactions_with_attachments
                    ),

                    claimed_by=interaction.claimed_by,

                    claimed_by_name=(
                        claimer_names.get(interaction.claimed_by)
                        if interaction.claimed_by is not None
                        else None
                    ),

                    tags=interaction.tags,

                    folder_id=interaction.folder_id,

                    snoozed_until=interaction.snoozed_until,

                    reply_count=reply_count,

                    latest_message=latest_message,

                    latest_sender=latest_sender,

                    latest_at=(
                        latest_reply.created_at
                        if latest_reply is not None
                        else None
                    ),

                )

            )

        return InboxResponse(

            total=len(inbox_items),

            items=inbox_items,

        )

    async def get_sent(self, current_user: User) -> SentResponse:
        """
        Every reply `current_user` has sent, pre-ticket or
        ticket-level alike, plus every brand-new Compose email they've
        authored — a separate shape from `get_inbox` since a sent
        reply is a thread child, not a root, and carries no subject/
        client_name of its own (borrowed from its thread root here).
        A Compose-authored row is itself a root (parent_interaction_id
        is None) and its own EmailPayload already has subject/
        client_name/body — no separate root lookup needed for those.
        """

        replies = await self.interaction_repository.list_sent(current_user.user_id)

        root_ids = {
            reply.parent_interaction_id
            for reply in replies
            if reply.parent_interaction_id is not None
        }
        roots = await self.interaction_repository.list_by_ids(list(root_ids))
        roots_by_id = {root.interaction_id: root for root in roots}

        items: list[SentItemResponse] = []

        for reply in replies:
            if reply.parent_interaction_id is None:
                # A Compose-authored root — subject/client_name/body
                # live on this row's own payload, not a separate
                # thread root (there isn't one; this row IS the root).
                client_name = "Unknown"
                subject = "(no subject)"
                message = ""
                try:
                    own_payload = EmailPayload.model_validate(reply.payload)
                    client_name = own_payload.client_name or "Unknown"
                    subject = own_payload.subject
                    message = own_payload.body
                except ValidationError:
                    logger.warning(
                        "Skipping subject/client resolution for sent Compose "
                        "email %s — its own payload doesn't match EmailPayload.",
                        reply.interaction_id,
                    )

                items.append(
                    SentItemResponse(
                        interaction_id=reply.interaction_id,
                        root_interaction_id=reply.interaction_id,
                        ticket_id=reply.ticket_id,
                        client_id=reply.client_id,
                        client_name=client_name,
                        subject=subject,
                        message=message,
                        sent_at=reply.created_at,
                    )
                )
                continue

            root = roots_by_id.get(reply.parent_interaction_id)

            client_name = "Unknown"
            subject = "(no subject)"

            if root is not None:
                try:
                    payload = EmailPayload.model_validate(root.payload)
                    client_name = payload.client_name or "Unknown"
                    subject = payload.subject
                except ValidationError:
                    logger.warning(
                        "Skipping subject/client resolution for sent reply %s "
                        "— thread root payload doesn't match EmailPayload.",
                        reply.interaction_id,
                    )

            message = reply.payload.get("message", "") if isinstance(reply.payload, dict) else ""

            items.append(
                SentItemResponse(
                    interaction_id=reply.interaction_id,
                    root_interaction_id=reply.parent_interaction_id,
                    ticket_id=reply.ticket_id,
                    client_id=reply.client_id,
                    client_name=client_name,
                    subject=subject,
                    message=message,
                    sent_at=reply.created_at,
                )
            )

        return SentResponse(total=len(items), items=items)

    async def get_drafts(self, current_user: User) -> DraftListResponse:
        """
        Every draft `current_user` currently has saved, across every
        thread — same subject/client_name-borrowed-from-root shape as
        `get_sent`.
        """

        drafts = await self.interaction_repository.list_drafts(current_user.user_id)

        root_ids = {
            draft.parent_interaction_id
            for draft in drafts
            if draft.parent_interaction_id is not None
        }
        roots = await self.interaction_repository.list_by_ids(list(root_ids))
        roots_by_id = {root.interaction_id: root for root in roots}

        items: list[DraftItemResponse] = []

        for draft in drafts:
            root = roots_by_id.get(draft.parent_interaction_id)

            client_name = "Unknown"
            subject = "(no subject)"

            if root is not None:
                try:
                    payload = EmailPayload.model_validate(root.payload)
                    client_name = payload.client_name or "Unknown"
                    subject = payload.subject
                except ValidationError:
                    logger.warning(
                        "Skipping subject/client resolution for draft %s "
                        "— thread root payload doesn't match EmailPayload.",
                        draft.interaction_id,
                    )

            message = draft.payload.get("message", "") if isinstance(draft.payload, dict) else ""

            items.append(
                DraftItemResponse(
                    interaction_id=draft.interaction_id,
                    root_interaction_id=draft.parent_interaction_id,
                    client_id=draft.client_id,
                    client_name=client_name,
                    subject=subject,
                    message=message,
                    created_at=draft.created_at,
                )
            )

        return DraftListResponse(total=len(items), items=items)
