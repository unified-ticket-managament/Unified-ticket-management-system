import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean
from sqlalchemy import Enum as SQLEnum
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
#interaction.py
from app.ticketing.enums import (
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
        index=True,
    )

    interaction_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    status: Mapped[InteractionStatus] = mapped_column(
        SQLEnum(
            InteractionStatus,
            name="interaction_status_enum",
        ),
        default=InteractionStatus.PENDING,
        nullable=False,
        index=True,
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
        index=True,
    )

    # Set only when this row was written during an active "Login as
    # User" impersonation session (app/core/impersonation_context.py,
    # InteractionRepository.create) — the real, physically-
    # authenticated Super Admin, distinct from `performed_by` above,
    # which continues to mean whoever's identity actually performed
    # the action (the target — unchanged business meaning; this is
    # deliberately the same convention as ticket_audit_logs'
    # actor_id/impersonator_id split, see root CLAUDE.md's
    # impersonation section). Denormalized at write time (name, not
    # just id) rather than resolved via the same `names_by_id` batch
    # lookup `performed_by_name` uses, so every existing read path
    # that already builds an InteractionResponse from these columns
    # picks it up for free with no additional query. NULL for every
    # ordinary, non-impersonated row.
    impersonator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    impersonator_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    payload: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    # A real, queryable one-line summary — populated for EMAIL/REPLY/
    # INTERNAL_NOTE rows (the only types this service creates going
    # forward) so list endpoints can show it without extracting from
    # `payload` on every read. NULL for every other historical type
    # (ATTACHMENT, and the retired STATUS_CHANGE/PRIORITY_CHANGE/
    # AGENT_TRANSFER/CLAIM/EDIT_ACCESS_* rows) — never meant to have one.
    subject: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    is_visible: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
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
        index=True,
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
        index=True,
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
        index=True,
    )

    # Which category this interaction belongs to — the CATEGORY-
    # mailbox counterpart to client_id above, set on every inbound
    # email that landed at a category's own shared inbox
    # (Category.inbox_email) rather than a client's. Mutually
    # exclusive with client_id in practice (an inbox address is either
    # a client mailbox or a category mailbox, never both — enforced at
    # mailbox-creation time), but not DB-constrained as such since
    # nothing here needs to enforce it beyond that creation-time check.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.category_id"),
        nullable=True,
        index=True,
    )

    # Self-referencing thread link: a reply or a follow-up email
    # points at the root interaction of its conversation. NULL means
    # "this interaction is itself a thread root" (or doesn't belong
    # to a thread at all, e.g. a ticket-timeline status change).
    parent_interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interactions.interaction_id"),
        nullable=True,
        index=True,
    )

    # Mailbox arrival time reported by the transport layer for
    # inbound emails — the SLA clock start. NULL for interaction
    # types that were never "received" (replies, notes, status
    # changes, claims); those aren't part of the SLA calculation.
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
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
    index=True,
    )

    # Real-column mirror of the same-named keys long carried inside
    # `payload` for every outbound (Compose/Reply/Reply-All/Forward/
    # Draft) interaction — "PENDING_SEND"/"SENT"/"FAILED"/"CANCELED"/
    # "NO_RECIPIENT"/"DRAFT". `payload` remains the source of truth
    # every existing read site (cancel_pending_send, undo_send's own
    # re-check) already reads and keeps reading unchanged; these
    # columns exist so "show me every failed/pending send" can be a
    # real, indexed query instead of a full-table JSONB scan, and so
    # API responses can expose it as a typed field instead of an
    # untyped blob. NULL for every interaction that was never an
    # outbound dispatch attempt (the overwhelming majority of rows).
    # Plain String, not a native Postgres enum — this value set has
    # already grown once (CANCELED, NO_RECIPIENT, DRAFT added after
    # the original PENDING_SEND/SENT/FAILED/QUEUED trio) and a native
    # enum would need its own migration each time it grows again.
    dispatch_status: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        index=True,
    )

    dispatch_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # The Undo-Send deadline for a PENDING_SEND row — mirrors
    # payload["send_after"] (stored there as an ISO string; here as a
    # real timestamp).
    send_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Microsoft Graph's own id for the message this interaction
    # actually dispatched as, once known (mirrors
    # payload["provider_message_id"]) — a real, indexed column so a
    # future Sent-Items-reconciliation or reply-threading feature can
    # look one up directly instead of scanning JSONB.
    provider_message_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    # Client-generated key for Send/Retry-Send idempotency — never
    # server-derived from content, so two genuinely separate sends
    # with identical content never collide. Scoped (performed_by, key)
    # via a partial unique index (see the
    # add_dispatch_idempotency_key migration) rather than a bare
    # global unique column, so one user's key can never collide with
    # (or be guessed to read) another user's interaction — the same
    # "this is your own action" scoping cancel_pending_send already
    # uses. NULL for every interaction whose caller didn't supply one
    # (the overwhelming majority of rows, and every inbound one).
    dispatch_idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # True only for a row created by EmailService._receive_bounce — a
    # detected non-delivery report/bounce (see bounce_detection.py),
    # never a real client message. Always paired with is_visible=False
    # (kept out of every inbox/ticket list query for free via that
    # existing filter) and never has rules/SLA run against it — see
    # _receive_bounce's own docstring for the anti-loop reasoning.
    is_bounce: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        server_default="false",
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