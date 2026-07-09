import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.ticketing.enums import ActorRole, AuditEntityType, AuditEventType
from shared_models.database import Base

#audit_log.py
class AuditLog(Base):
    """
    Immutable, append-only record of who changed what on a ticket
    (and related entities), and what the values were before/after.

    This is deliberately NOT the same thing as Interaction:
    - Interaction rows are the visible ticket timeline agents read
      day to day (emails, replies, notes, status/priority changes,
      attachment uploads...). They're a business record, and can be
      hidden (soft-deleted) via `is_visible`.
    - AuditLog rows are a compliance/security record of every
      meaningful change. They are never shown to agents as
      "activity", and are never updated or deleted — there is
      intentionally no update()/delete() anywhere in
      AuditLogRepository for this table.

    Table is `ticket_audit_logs` (not `audit_logs`) because an
    unrelated `audit_logs` table, owned by a different service,
    already exists in this shared database.
    """

    # Named `ticket_audit_logs`, not `audit_logs` — an unrelated
    # `audit_logs` table (different schema, different owner) already
    # exists in this shared database. This table is owned solely by
    # the Ticket Management service, same as tickets/interactions/
    # attachments.
    __tablename__ = "ticket_audit_logs"

    audit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    entity_type: Mapped[AuditEntityType] = mapped_column(
        SQLEnum(
            AuditEntityType,
            name="audit_entity_type_enum",
        ),
        nullable=False,
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    event_type: Mapped[AuditEventType] = mapped_column(
        SQLEnum(
            AuditEventType,
            name="audit_event_type_enum",
        ),
        nullable=False,
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    # Stored at write time (not resolved via a join at read time) —
    # deliberately, since an audit trail should keep saying who did
    # something even if that user's name changes later or the row
    # is later deleted from `users`.
    actor_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    actor_role: Mapped[ActorRole] = mapped_column(
        SQLEnum(
            ActorRole,
            name="audit_actor_role_enum",
        ),
        nullable=False,
    )

    old_values: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    new_values: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        # Mixed ASC/DESC composite indexes — declared via text() for
        # the DESC columns since declarative __table_args__ can't
        # reference `.desc()` on a not-yet-built mapped column.
        Index(
            "idx_audit_entity",
            "entity_type",
            "entity_id",
            text("created_at DESC"),
        ),
        Index(
            "idx_audit_user",
            "actor_id",
            text("created_at DESC"),
        ),
        Index(
            "idx_audit_event_type",
            "event_type",
            text("created_at DESC"),
        ),
    )
