import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean
from sqlalchemy import Enum as SQLEnum
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
#interaction.py
from app.enums import (
    InteractionDirection,
    InteractionStatus,
)
from shared_models.database import Base

if TYPE_CHECKING:
    from shared_models.models import User
    from .attachment import Attachment
    from .ticket import Ticket


class Interaction(Base):
    """
    Interaction Model
    """

    __tablename__ = "interactions"

    interaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.ticket_id"),
        nullable=True,
    )

    interaction_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    status: Mapped[InteractionStatus] = mapped_column(
        SQLEnum(
            InteractionStatus,
            name="interaction_status_enum",
        ),
        default=InteractionStatus.PENDING,
        nullable=False,
    )

    direction: Mapped[InteractionDirection] = mapped_column(
        SQLEnum(
            InteractionDirection,
            name="interaction_direction_enum",
        ),
        nullable=False,
    )

    performed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    payload: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    is_visible: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    removed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    removed_at:Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Who has claimed this pending (pre-ticket) interaction from the
    # shared inbox pool — "Assign to me". NULL means unclaimed. Only
    # meaningful while ticket_id IS NULL and status == PENDING; once
    # converted to a ticket, ownership moves to Ticket.agent_id
    # instead (a completely separate concept — see TicketRepository.claim).
    claimed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Free-form labels — a plain JSON string list, not a join table,
    # matching this repo's existing pattern for lightweight per-row
    # metadata (see `payload`/`Ticket.custom_fields`). Full-replace
    # semantics on write (no per-tag add/remove endpoint).
    tags: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )

    # Which custom folder (Billing/Claims/General/...) this item has
    # been filed into — orthogonal to `status`; assigning a folder
    # never changes pending/replied/ticketed/archived state.
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mail_folders.folder_id"),
        nullable=True,
    )

    # Set to hide this item from the "pending" view until this time,
    # after which it resurfaces automatically — no background job
    # needed, `list_inbox`'s "pending"/"snoozed" filters just compare
    # against `now()` on every read. Only meaningful pre-ticket, same
    # as `claimed_by`.
    snoozed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # A saved-but-unsent reply — a normal REPLY/OUTBOUND row
    # (parent_interaction_id set to the thread root) that's never
    # dispatched until explicitly sent. One active draft per thread
    # per agent: saving again overwrites the same row rather than
    # creating a second one (see InteractionRepository.get_draft).
    is_draft: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    message_id: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
    )

    # Which client (company) this interaction belongs to — set on
    # every inbound email by resolving the receiving shared-inbox
    # address, and propagated onto every reply in the same thread.
    # Real column (not payload-only) because the inbox query filters
    # on it directly.
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.client_id"),
        nullable=True,
    )

    # Self-referencing thread link: a reply or a follow-up email
    # points at the root interaction of its conversation. NULL means
    # "this interaction is itself a thread root" (or doesn't belong
    # to a thread at all, e.g. a ticket-timeline status change).
    parent_interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interactions.interaction_id"),
        nullable=True,
    )

    # Mailbox arrival time reported by the transport layer for
    # inbound emails — the SLA clock start. NULL for interaction
    # types that were never "received" (replies, notes, status
    # changes, claims); those aren't part of the SLA calculation.
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Graph-ready threading headers — real columns (not payload-only)
    # so future lookups can index/query them directly instead of
    # scanning JSON. `conversation_id` is Microsoft Graph's own
    # thread identifier (unavailable until Task 1 ships; NULL for
    # every dummy-mail-flow interaction today). `in_reply_to_message_id`
    # and `references` mirror the RFC 5322 headers already carried in
    # `payload["in_reply_to"]`/`payload["references"]` for a fresh
    # inbound EMAIL row, promoted to first-class columns so thread
    # matching doesn't need to deserialize payload JSON.
    conversation_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    in_reply_to_message_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    references: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    default=lambda: datetime.now(timezone.utc),
    nullable=False,
    )

    # ------------------------

    ticket: Mapped["Ticket"] = relationship(
        "Ticket",
        back_populates="interactions",
    )

    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment",
        back_populates="interaction",
        cascade="all, delete-orphan",
    )