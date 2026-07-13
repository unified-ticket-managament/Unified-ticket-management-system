from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.sla_breach_notification import SLABreachNotification

#sla_breach_notification_repository.py
class SLABreachNotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def try_record(
        self,
        *,
        clock_type: str,
        clock_id: UUID,
        threshold: str,
    ) -> bool:
        """
        Attempts to record that this (clock, threshold) pair has been
        notified. Returns True only if this call actually inserted the
        row — a caller should only fire the real notification in that
        case. Safe against two overlapping sweep runs racing on the
        same clock: the unique index on (clock_type, clock_id,
        threshold) means at most one of them ever sees `True`, no
        application-level lock required.
        """

        stmt = (
            insert(SLABreachNotification)
            .values(
                clock_type=clock_type,
                clock_id=clock_id,
                threshold=threshold,
            )
            .on_conflict_do_nothing(
                index_elements=["clock_type", "clock_id", "threshold"]
            )
            .returning(SLABreachNotification.sla_breach_notification_id)
        )

        result = await self.db.execute(stmt)
        inserted_id = result.scalar_one_or_none()

        await self.db.flush()

        return inserted_id is not None

    async def try_record_many(
        self, entries: list[tuple[str, UUID, str]]
    ) -> set[tuple[str, UUID, str]]:
        """
        Batch form of try_record — one INSERT ... ON CONFLICT DO
        NOTHING ... RETURNING for every (clock_type, clock_id,
        threshold) triple crossed in a single sweep tick, instead of
        one network round trip per triple. Returns exactly the subset
        that was newly inserted (i.e. genuinely crossed for the first
        time); already-recorded triples are silently skipped by ON
        CONFLICT DO NOTHING, same idempotency guarantee as try_record,
        just amortized across the whole batch — this is what keeps a
        sweep with many simultaneously-crossing clocks from spending
        one Neon round trip per clock-threshold pair just to check
        "has this already fired," which otherwise dominates the
        sweep's wall-clock time at any real scale.

        Trade-off worth knowing: unlike try_record (whose single
        INSERT a caller wraps in the same SAVEPOINT as its own
        notify-and-audit-log work, so a notify failure rolls back the
        marker with it), a batch-inserted marker here is committed to
        the outer transaction independently of whatever the caller
        does afterward with the returned set. If a caller's own
        post-processing for one specific triple then fails, that one
        triple's marker still stands — it will NOT be retried on the
        next sweep tick, even though its notification may not have
        gone out. Acceptable here because notify() is a simple insert
        essentially never expected to fail in isolation (a real
        failure at that point usually means the whole request/
        connection is compromised, which surfaces as a logged error
        and an incremented `errors` count in SLASweepResponse, not a
        silent loss) — but this is a deliberate trade-off, not an
        oversight, should this method ever grow more failure-prone
        callers.
        """

        if not entries:
            return set()

        stmt = (
            insert(SLABreachNotification)
            .values(
                [
                    {"clock_type": clock_type, "clock_id": clock_id, "threshold": threshold}
                    for clock_type, clock_id, threshold in entries
                ]
            )
            .on_conflict_do_nothing(
                index_elements=["clock_type", "clock_id", "threshold"]
            )
            .returning(
                SLABreachNotification.clock_type,
                SLABreachNotification.clock_id,
                SLABreachNotification.threshold,
            )
        )

        result = await self.db.execute(stmt)
        inserted = {(row.clock_type, row.clock_id, row.threshold) for row in result}

        await self.db.flush()

        return inserted
