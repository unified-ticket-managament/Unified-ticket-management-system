from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.inbound_mail_failure import InboundMailFailure

# Never persist an unbounded exception string — this is a diagnostic
# summary for ops, not a place a leaked secret/token could hide in a
# long stack trace.
_ERROR_SUMMARY_MAX_CHARS = 4000


class InboundMailFailureRepository:
    """
    Phase 2 hardening — see InboundMailFailure's own docstring. Written
    to only from graph_mail_poller.py/mail_integration.py's genuine-
    failure branches (never for the benign duplicate-message-id race).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record_or_increment(
        self, *, message_id: str, mailbox_address: str, error_summary: str
    ) -> None:
        """
        Upsert on (message_id, mailbox_address): the first failure
        inserts attempt_count=1; a repeat failure bumps attempt_count/
        last_seen_at/error_summary in place. `resolved` is reset to
        False on conflict — a message that starts failing again after
        having been marked resolved reopens automatically rather than
        staying silently hidden from the unresolved list.
        """

        truncated_summary = (
            error_summary[:_ERROR_SUMMARY_MAX_CHARS] if error_summary else None
        )

        stmt = pg_insert(InboundMailFailure).values(
            message_id=message_id,
            mailbox_address=mailbox_address,
            error_summary=truncated_summary,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["message_id", "mailbox_address"],
            set_={
                "attempt_count": InboundMailFailure.attempt_count + 1,
                "last_seen_at": datetime.now(timezone.utc),
                "error_summary": stmt.excluded.error_summary,
                "resolved": False,
            },
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def mark_resolved(self, *, message_id: str, mailbox_address: str) -> None:
        """No-op if no matching row exists — called unconditionally on
        eventual success, not gated on "was there ever a failure"."""

        await self.db.execute(
            update(InboundMailFailure)
            .where(
                InboundMailFailure.message_id == message_id,
                InboundMailFailure.mailbox_address == mailbox_address,
            )
            .values(resolved=True)
        )
        await self.db.flush()

    async def list_unresolved(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[InboundMailFailure], int]:
        total_result = await self.db.execute(
            select(func.count()).select_from(InboundMailFailure).where(
                InboundMailFailure.resolved.is_(False)
            )
        )
        total = total_result.scalar_one()

        result = await self.db.execute(
            select(InboundMailFailure)
            .where(InboundMailFailure.resolved.is_(False))
            .order_by(InboundMailFailure.last_seen_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total
