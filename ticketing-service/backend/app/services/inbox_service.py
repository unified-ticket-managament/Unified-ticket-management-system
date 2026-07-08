import logging
from uuid import UUID

from pydantic import ValidationError
from shared_models.models import User

from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.user_repository import UserRepository

from app.schemas.inbox import (
    DraftItemResponse,
    DraftListResponse,
    InboxItemResponse,
    InboxResponse,
    SentItemResponse,
    SentResponse,
)

from app.schemas.payloads import EmailPayload
from app.services.access_control import SUPERVISOR_ROLE_NAMES

logger = logging.getLogger(__name__)


class InboxService:
    """
    Service responsible for the Account Manager Inbox workflow.

    Responsibilities:
    - Scope the inbox to the clients the current user manages
      (Manager/Super Admin see every client's inbox — the escape
      hatch for when an Account Manager is on leave).
    - Retrieve pending inbox interactions, or the full activity feed.
    - Transform database models into API response models.
    """

    def __init__(
        self,
        interaction_repository: InteractionRepository,
        attachment_repository: AttachmentRepository | None = None,
        user_repository: UserRepository | None = None,
    ):
        self.interaction_repository = interaction_repository
        self.attachment_repository = attachment_repository
        self.user_repository = user_repository

    async def get_inbox(
        self,
        current_user: User,
        client_id: UUID | None = None,
        view: str = "pending",
        scope: str = "mine",
        folder_id: UUID | None = None,
    ) -> InboxResponse:
        """
        Returns the inbox for the current user.

        `scope="mine"` (default): only clients this user manages.
        `scope="all"`: every client's mail — the "All Inboxes"
        overview. Only meaningful for Manager/Super Admin; silently
        falls back to "mine" for anyone else so a crafted request
        can't peek at other Account Managers' mail.
        """

        is_supervisor = current_user.role.name in SUPERVISOR_ROLE_NAMES
        wants_every_client = scope == "all" or view == "all"

        account_manager_id = (
            None
            if is_supervisor and wants_every_client
            else current_user.user_id
        )

        interactions = await self.interaction_repository.list_inbox(
            account_manager_id=account_manager_id,
            client_id=client_id,
            view=view,
            folder_id=folder_id,
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

                )

            )

        return InboxResponse(

            total=len(inbox_items),

            items=inbox_items,

        )

    async def get_sent(self, current_user: User) -> SentResponse:
        """
        Every reply `current_user` has sent, pre-ticket or
        ticket-level alike — a separate shape from `get_inbox` since
        a sent reply is a thread child, not a root, and carries no
        subject/client_name of its own (borrowed from its thread
        root here).
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
