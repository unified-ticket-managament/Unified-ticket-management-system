import logging
from uuid import UUID

from pydantic import ValidationError
from shared_models.models import User

from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.interaction_repository import (
    InteractionRepository,
)

from app.schemas.inbox import (
    InboxItemResponse,
    InboxResponse,
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
    ):
        self.interaction_repository = interaction_repository
        self.attachment_repository = attachment_repository

    async def get_inbox(
        self,
        current_user: User,
        client_id: UUID | None = None,
        view: str = "pending",
        scope: str = "mine",
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
        )

        interactions_with_attachments: set = set()

        if self.attachment_repository is not None:
            interactions_with_attachments = (
                await self.attachment_repository
                .has_attachments_for_interactions(
                    [i.interaction_id for i in interactions]
                )
            )

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

                )

            )

        return InboxResponse(

            total=len(inbox_items),

            items=inbox_items,

        )
