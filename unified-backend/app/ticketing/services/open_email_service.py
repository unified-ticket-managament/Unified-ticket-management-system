import asyncio
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import ValidationError
from shared_models.models import User

from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import (
    InteractionRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.interaction import InteractionResponse
from app.ticketing.schemas.open_email import OpenEmailResponse
from app.ticketing.schemas.payloads import EmailPayload
from app.ticketing.services.access_control import (
    ensure_agent_can_view_pending_interaction,
    ensure_agent_can_view_ticket,
)
from app.ticketing.services.attachment_service import attachments_to_metadata
from app.ticketing.storage.base import StorageService


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
        conversation_id=interaction.conversation_id,
        in_reply_to_message_id=interaction.in_reply_to_message_id,
        references=interaction.references or [],
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

        # Access control — the same rule GET /inbox's list view
        # already applies (role-scoped visibility), now also enforced
        # on opening a specific thread by id, so a role that can't see
        # an item in its own list can't reach it by guessing/copying
        # its interaction_id either.
        ticket = None
        if interaction.ticket_id is not None:
            if self.ticket_repository is not None:
                ticket = await self.ticket_repository.get_by_id(interaction.ticket_id)
            if current_user is not None and ticket is not None:
                ensure_agent_can_view_ticket(ticket, current_user)
        elif current_user is not None:
            await ensure_agent_can_view_pending_interaction(
                interaction, current_user, self.client_repository
            )

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

        # None of these five reads depend on each other's results (the
        # one that used to run last, _recommend_ticket, needs `replies`
        # — so it stays a separate, later await instead of joining this
        # batch) — running them concurrently instead of one at a time
        # cuts this endpoint's round-trip count roughly in half.
        (
            replies,
            attachments,
            claimed_by_name,
            account_manager_name,
            draft_message,
        ) = await asyncio.gather(
            self.interaction_repository.list_thread(interaction_id),
            self._fetch_attachments(interaction_id),
            self._fetch_claimed_by_name(interaction.claimed_by),
            self._fetch_account_manager_name(interaction.client_id),
            self._fetch_draft_message(interaction, current_user),
        )

        ticket_priority = None
        ticket_category = None
        ticket_status = None
        if ticket is not None:
            ticket_priority = ticket.current_priority.value
            ticket_category = ticket.ticket_type
            ticket_status = ticket.current_status.value

        recommended_ticket_id, recommended_ticket_reason = (
            await self._recommend_ticket(interaction, replies)
        )

        return OpenEmailResponse(
            interaction_id=interaction.interaction_id,
            ticket_id=interaction.ticket_id,
            client_id=interaction.client_id,
            client_name=payload.client_name or "Unknown",
            to_email=payload.to_email,
            from_email=payload.from_email,
            from_name=payload.from_name,
            cc=payload.cc,
            bcc=payload.bcc,
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
            ticket_status=ticket_status,
            tags=interaction.tags,
            folder_id=interaction.folder_id,
            snoozed_until=interaction.snoozed_until,
            draft_message=draft_message,
            attachments=attachments,
            replies=[_reply_to_response(reply) for reply in replies],
            recommended_ticket_id=recommended_ticket_id,
            recommended_ticket_reason=recommended_ticket_reason,
        )

    async def _fetch_attachments(self, interaction_id: UUID) -> list:
        if self.attachment_repository is None or self.storage_service is None:
            return []

        raw_attachments = await self.attachment_repository.list_by_interaction_id(
            interaction_id
        )
        return await attachments_to_metadata(raw_attachments, self.storage_service)

    async def _fetch_claimed_by_name(self, claimed_by: UUID | None) -> str | None:
        if self.user_repository is None or claimed_by is None:
            return None

        claimer = await self.user_repository.get_by_id(claimed_by)
        return claimer.name if claimer is not None else None

    async def _fetch_account_manager_name(self, client_id: UUID | None) -> str | None:
        if (
            self.client_repository is None
            or self.user_repository is None
            or client_id is None
        ):
            return None

        client = await self.client_repository.get_by_id(client_id)
        if client is None:
            return None

        manager = await self.user_repository.get_by_id(client.account_manager_id)
        return manager.name if manager is not None else None

    async def _fetch_draft_message(self, interaction, current_user: User | None) -> str | None:
        if current_user is None or interaction.ticket_id is not None:
            return None

        draft = await self.interaction_repository.get_draft(
            interaction.interaction_id, current_user.user_id
        )
        if draft is not None and isinstance(draft.payload, dict):
            return draft.payload.get("message")
        return None

    async def _recommend_ticket(
        self,
        root,
        replies: list,
    ) -> tuple[UUID | None, str | None]:
        """
        "Attach to Existing Ticket" convenience for a thread that
        isn't already linked to one — best-effort, never a hard
        attach. Checked in order, first hit wins:

        1. The root itself already carries a ticket_id (defensive —
           by the time a thread reaches this far unticketed, this
           shouldn't fire, but a manual DB edit or a future code path
           could leave it set).
        2. Any reply already filed under this thread carries a
           ticket_id (same defensive reasoning).
        3. The root's own In-Reply-To/References headers resolve to
           an already-ticketed interaction — the same header match
           EmailService.receive_email runs at intake time, re-run
           here as a safety net for threads received before this
           feature existed (or where the match wasn't attempted).

        A subject-contains-ticket-reference tier is deliberately not
        implemented — this codebase has no human-readable ticket
        code/number, only UUID ticket_ids, so there's nothing
        meaningful to parse out of a subject line yet.
        """

        if root.ticket_id is not None:
            return root.ticket_id, "This thread is already linked to this ticket."

        for reply in replies:
            if reply.ticket_id is not None:
                return (
                    reply.ticket_id,
                    "A reply already filed under this thread is linked to this ticket.",
                )

        candidate_message_ids = list(root.references or [])
        if root.in_reply_to_message_id:
            candidate_message_ids.append(root.in_reply_to_message_id)

        if candidate_message_ids:
            matches = await self.interaction_repository.get_by_message_ids(
                candidate_message_ids
            )
            for match in matches:
                if match.ticket_id is not None:
                    return (
                        match.ticket_id,
                        "Matched from this email's In-Reply-To/References headers.",
                    )

        return None, None
