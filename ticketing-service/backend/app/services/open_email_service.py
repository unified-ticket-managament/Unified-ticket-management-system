from uuid import UUID

from fastapi import HTTPException, status
from pydantic import ValidationError
from shared_models.models import User

from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.client_repository import ClientRepository
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.ticket_repository import TicketRepository
from app.repositories.user_repository import UserRepository
from app.schemas.interaction import InteractionResponse
from app.schemas.open_email import OpenEmailResponse
from app.schemas.payloads import EmailPayload
from app.services.attachment_service import attachments_to_metadata
from app.storage.base import StorageService


def _reply_to_response(interaction) -> InteractionResponse:
    """
    Builds an InteractionResponse for a thread reply without
    touching `interaction.attachments` — that relationship is lazy
    and unloaded here, so letting pydantic's from_attributes
    machinery read it directly would trigger an unawaited lazy load
    (same reasoning as interaction_service.py's `_to_response`).
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
        attachments=[],
    )


class OpenEmailService:
    """
    Service responsible for returning the complete details of an
    inbox email — the root message plus its thread of replies.
    """

    def __init__(
        self,
        interaction_repository: InteractionRepository,
        attachment_repository: AttachmentRepository | None = None,
        storage_service: StorageService | None = None,
        user_repository: UserRepository | None = None,
        client_repository: ClientRepository | None = None,
        ticket_repository: TicketRepository | None = None,
    ):
        self.interaction_repository = interaction_repository
        self.attachment_repository = attachment_repository
        self.storage_service = storage_service
        self.user_repository = user_repository
        self.client_repository = client_repository
        self.ticket_repository = ticket_repository

    async def get_email_details(
        self,
        interaction_id: UUID,
        current_user: User | None = None,
    ) -> OpenEmailResponse:
        """
        Returns the complete email details for the specified
        interaction, including every reply already filed under it.
        """

        interaction = await self.interaction_repository.get_by_id(
            interaction_id
        )

        if interaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        # A reply/follow-up isn't itself a thread root — resolve up to
        # the root first (same walk-up as add_interaction_reply) so
        # this endpoint always shows the full conversation regardless
        # of which id within it the caller happened to pass. The Sent
        # view is the main caller that can hand in a non-root id (a
        # reply whose own thread root couldn't be resolved at send
        # time — legacy data predating the threading rule).
        if interaction.parent_interaction_id is not None:
            root = await self.interaction_repository.get_by_id(
                interaction.parent_interaction_id
            )
            if root is not None:
                interaction = root
                interaction_id = root.interaction_id

        try:
            payload = EmailPayload.model_validate(interaction.payload)
        except ValidationError:
            # Genuinely rootless reply (no resolvable EmailPayload at
            # all) — degrade gracefully using the reply's own fields
            # rather than 500ing the whole thread view.
            payload = EmailPayload(
                subject="(no subject)",
                body=(
                    interaction.payload.get("message", "")
                    if isinstance(interaction.payload, dict)
                    else ""
                ),
            )

        attachments = []

        if self.attachment_repository is not None and self.storage_service is not None:
            raw_attachments = await self.attachment_repository.list_by_interaction_id(
                interaction_id
            )
            attachments = await attachments_to_metadata(raw_attachments, self.storage_service)

        replies = await self.interaction_repository.list_thread(interaction_id)

        claimed_by_name = None
        if self.user_repository is not None and interaction.claimed_by is not None:
            claimer = await self.user_repository.get_by_id(interaction.claimed_by)
            claimed_by_name = claimer.name if claimer is not None else None

        account_manager_name = None
        if (
            self.client_repository is not None
            and self.user_repository is not None
            and interaction.client_id is not None
        ):
            client = await self.client_repository.get_by_id(interaction.client_id)
            if client is not None:
                manager = await self.user_repository.get_by_id(client.account_manager_id)
                account_manager_name = manager.name if manager is not None else None

        ticket_priority = None
        ticket_category = None
        if self.ticket_repository is not None and interaction.ticket_id is not None:
            ticket = await self.ticket_repository.get_by_id(interaction.ticket_id)
            if ticket is not None:
                ticket_priority = ticket.current_priority.value
                ticket_category = ticket.ticket_type

        draft_message = None
        if current_user is not None and interaction.ticket_id is None:
            draft = await self.interaction_repository.get_draft(
                interaction.interaction_id, current_user.user_id
            )
            if draft is not None and isinstance(draft.payload, dict):
                draft_message = draft.payload.get("message")

        return OpenEmailResponse(
            interaction_id=interaction.interaction_id,
            ticket_id=interaction.ticket_id,
            client_id=interaction.client_id,
            client_name=payload.client_name or "Unknown",
            to_email=payload.to_email,
            from_email=payload.from_email,
            from_name=payload.from_name,
            subject=payload.subject,
            body=payload.body,
            message_id=interaction.message_id,
            received_at=interaction.received_at or interaction.created_at,
            status=interaction.status,
            claimed_by=interaction.claimed_by,
            claimed_by_name=claimed_by_name,
            account_manager_name=account_manager_name,
            ticket_priority=ticket_priority,
            ticket_category=ticket_category,
            tags=interaction.tags,
            folder_id=interaction.folder_id,
            snoozed_until=interaction.snoozed_until,
            draft_message=draft_message,
            attachments=attachments,
            replies=[_reply_to_response(reply) for reply in replies],
        )
