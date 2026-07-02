from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.interaction_repository import (
    InteractionRepository,
)

from app.schemas.inbox import (
    InboxItemResponse,
    InboxResponse,
)

from app.schemas.payloads import EmailPayload


class InboxService:
    """
    Service responsible for the Agent Inbox workflow.

    Responsibilities:
    - Retrieve pending inbox interactions
    - Transform database models into API response models
    """

    def __init__(
        self,
        interaction_repository: InteractionRepository,
        attachment_repository: AttachmentRepository | None = None,
    ):
        self.interaction_repository = interaction_repository
        self.attachment_repository = attachment_repository

    async def get_agent_inbox(
        self,
        agent_name: str,
    ) -> InboxResponse:
        """
        Returns all pending emails assigned
        to the specified agent.
        """

        interactions = (
            await self.interaction_repository
            .list_pending_inbox(agent_name)
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

            payload = EmailPayload.model_validate(
                interaction.payload
            )

            inbox_items.append(

                InboxItemResponse(

                    interaction_id=interaction.interaction_id,

                    client_name=payload.client_name,

                    subject=payload.subject,

                    message_id=interaction.message_id,

                    received_at=interaction.created_at,

                    status=interaction.status,

                    has_attachments=(
                        interaction.interaction_id in interactions_with_attachments
                    ),

                )

            )

        return InboxResponse(

            total=len(inbox_items),

            items=inbox_items,

        )