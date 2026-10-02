import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

#rule_run.py


class RuleRunStatus:
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # Stopped on purpose at the historical-forward safety cap — see
    # rule_run_service.HISTORICAL_FORWARD_CAP.
    CAPPED = "capped"

    ACTIVE = (QUEUED, RUNNING)
    TERMINAL = (COMPLETED, FAILED, CANCELLED, CAPPED)


class RuleRunPhase:
    # Main keyset scan over created_at <= cutoff_at.
    SCAN = "scan"
    # Short, bounded re-scan of the window just before cutoff_at, for an
    # intake transaction that began before the rule was committed but
    # committed after the main scan had already passed its created_at.
    RECONCILE = "reconcile"
    DONE = "done"


class RuleRunItemStatus:
    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"
    SKIPPED = "skipped"
    # forward_to only: committed *before* the external Graph send so a
    # crash between the send and the follow-up commit is detectable on
    # resume (see RuleRunItem's docstring).
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    # forward_to only: a SENDING item found after a restart, or a send
    # followed by a DB failure — whether the external email went out
    # can't be determined, so it is never re-sent automatically.
    UNKNOWN = "unknown"


class RuleRun(Base):
    """
    One "Run rule now" execution — a one-time, retroactive pass of a
    single rule over existing inbound mail, processed in the background
    by rule_run_worker (an APScheduler job, same architecture as the
    SLA sweep). Never re-runs on its own: a new row is only created by
    an explicit run_now=true on rule create/update.

    The run executes against `rule_snapshot` (the rule as it was when
    triggered) and `precedence_snapshot` (every enabled rule ahead of it
    in the live pipeline that has stop_processing set) — later edits,
    reorders or new rules never change an in-flight run. Disabling or
    deleting the rule cancels it; `rule_id` is SET NULL on delete so the
    run row survives for audit, with `rule_name` kept alongside.

    Mail scope is never stored as a list of ids: it is the intersection
    of what `rule_owner_id` and `triggered_by` are each independently
    authorized to act on, re-evaluated per email by
    rule_run_authorization (see that module) — `scope` only records
    which model and roles were in force, for audit.
    """

    __tablename__ = "rule_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rules.rule_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)

    rule_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    triggered_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )

    # The real Super Admin behind a "Login as User" session, when the
    # trigger happened inside one — triggered_by is still the
    # impersonated user, whose scope is what the run uses.
    impersonator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    impersonator_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RuleRunStatus.QUEUED, index=True
    )

    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    phase: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RuleRunPhase.SCAN
    )

    rule_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    precedence_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Keyset cursor — the last (created_at, interaction_id) fully
    # processed. Persisted only after a whole page has been handled.
    cursor_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cursor_interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    scanned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    already_applied_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    forwards_sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    skipped_by_reason: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Capped list (rule_run_service.MAX_ERROR_SAMPLES) of
    # {interaction_id, action, error} — never email content.
    error_samples: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Infrastructure-level failures retried from the saved cursor.
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        # One active (queued/running) run per rule — enforced by the
        # database, not just application code, so a double click or two
        # users triggering at once can never produce two concurrent runs.
        Index(
            "uq_rule_runs_one_active_per_rule",
            "rule_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index("ix_rule_runs_rule_id_created_at", "rule_id", "created_at"),
    )


class RuleRunItem(Base):
    """
    One action outcome for one interaction within one RuleRun — the
    per-email record that answers "why was this email changed, and by
    whose run". Written only for emails the rule actually matched (and
    that were in scope), never for the much larger set merely scanned.

    forward_to items follow an at-most-once state machine:
    SENDING is committed before the external send; SENT after the send
    and its Interaction/Notification records commit. A SENDING item
    seen again (worker restart, crash, DB failure after the send) is
    moved to UNKNOWN and never re-sent automatically, and any UNKNOWN/
    SENDING forward item for the same interaction from an earlier run
    also blocks a new run's forward of it — a possible missed forward
    is preferred over a possible duplicate external email.
    """

    __tablename__ = "rule_run_items"

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rule_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    interaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interactions.interaction_id"),
        nullable=False,
    )

    # Denormalized (no FK) so the record survives rule deletion.
    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    action_index: Mapped[int] = mapped_column(Integer, nullable=False)

    action_type: Mapped[str] = mapped_column(String(30), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False)

    skip_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Small structured outcome only (folder ids, recipient user ids) —
    # never email content.
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id", "interaction_id", "action_index",
            name="uq_rule_run_items_run_interaction_action",
        ),
        Index(
            "ix_rule_run_items_interaction_action_status",
            "interaction_id", "action_type", "status",
        ),
    )
