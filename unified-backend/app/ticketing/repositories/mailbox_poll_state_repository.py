from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.mailbox_poll_state import MailboxPollState

# Same rationale as InboundMailFailureRepository's own
# _ERROR_SUMMARY_MAX_CHARS — a diagnostic summary for ops, not a place
# an unbounded stack trace (or a leaked secret/token buried in one)
# should accumulate.
_FAILURE_SUMMARY_MAX_CHARS = 4000


class MailboxPollStateRepository:
    """
    Persisted counterpart to graph_mail_poller.py's in-memory
    `_PollState` — see MailboxPollState's own docstring for why this
    table exists. Written to once per mailbox per poll tick (success
    or failure), read once per tick to seed a freshly-started
    process's checkpoints.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_checkpoints(self) -> dict[str, datetime]:
        """Every mailbox with a known checkpoint, lowercased address ->
        checkpoint_at. One bulk read per poll tick, not per mailbox."""

        result = await self.db.execute(
            select(MailboxPollState.mailbox_address, MailboxPollState.checkpoint_at).where(
                MailboxPollState.checkpoint_at.is_not(None)
            )
        )
        return {address: checkpoint_at for address, checkpoint_at in result.all()}

    async def record_success(self, *, mailbox_address: str, checkpoint_at: datetime) -> None:
        """Upsert on mailbox_address: advances checkpoint_at/
        last_success_at and resets the failure-streak columns — a
        mailbox that just succeeded is no longer "stalled" regardless
        of how many ticks it failed before this one."""

        now = datetime.now(timezone.utc)
        stmt = pg_insert(MailboxPollState).values(
            mailbox_address=mailbox_address,
            checkpoint_at=checkpoint_at,
            last_success_at=now,
            consecutive_failures=0,
            last_failure_at=None,
            last_failure_summary=None,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["mailbox_address"],
            set_={
                "checkpoint_at": stmt.excluded.checkpoint_at,
                "last_success_at": stmt.excluded.last_success_at,
                "consecutive_failures": 0,
                "last_failure_at": None,
                "last_failure_summary": None,
            },
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def record_failure(self, *, mailbox_address: str, error_summary: str) -> int:
        """Upsert on mailbox_address: bumps consecutive_failures in
        place (never touches checkpoint_at — a failed fetch has no
        new checkpoint to advance to) and returns the new streak
        count, so the caller can decide whether to alert without a
        second round trip."""

        now = datetime.now(timezone.utc)
        truncated_summary = (
            error_summary[:_FAILURE_SUMMARY_MAX_CHARS] if error_summary else None
        )

        stmt = pg_insert(MailboxPollState).values(
            mailbox_address=mailbox_address,
            consecutive_failures=1,
            last_failure_at=now,
            last_failure_summary=truncated_summary,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["mailbox_address"],
            set_={
                "consecutive_failures": MailboxPollState.consecutive_failures + 1,
                "last_failure_at": stmt.excluded.last_failure_at,
                "last_failure_summary": stmt.excluded.last_failure_summary,
            },
        )
        await self.db.execute(stmt)
        await self.db.flush()

        result = await self.db.execute(
            select(MailboxPollState.consecutive_failures).where(
                MailboxPollState.mailbox_address == mailbox_address
            )
        )
        return result.scalar_one()

    async def mark_alerted(self, *, mailbox_address: str) -> None:
        stmt = pg_insert(MailboxPollState).values(
            mailbox_address=mailbox_address,
            last_alerted_at=datetime.now(timezone.utc),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["mailbox_address"],
            set_={"last_alerted_at": stmt.excluded.last_alerted_at},
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def get(self, *, mailbox_address: str) -> MailboxPollState | None:
        # populate_existing=True: this repository's other methods
        # write via raw Core INSERT/ON CONFLICT statements (record_
        # success/record_failure/mark_alerted), which never touch the
        # ORM identity map — a caller that already loaded this exact
        # row earlier in the same session (e.g. get() called twice
        # around a record_failure() in between) would otherwise get
        # back the stale, pre-write in-memory object instead of a
        # fresh read, since a plain select() never overwrites an
        # already-identity-mapped instance's attributes by default.
        result = await self.db.execute(
            select(MailboxPollState)
            .where(MailboxPollState.mailbox_address == mailbox_address)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()
