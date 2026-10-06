from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.enums import InteractionDirection
from app.ticketing.models.email_read_receipt import (
    RECEIPT_STATUS_CONFIRMED,
    RECEIPT_STATUS_REQUESTED,
    EmailReadReceipt,
)
from app.ticketing.models.interaction import Interaction


class EmailReadReceiptRepository:
    """
    Persistence for per-recipient read-receipt state. Never commits —
    every method flushes into the caller's transaction, so the caller
    (the send recorder, or the receipt branch inside its own
    savepoint) owns the transaction boundary.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_requested(
        self, interaction_id: UUID, recipient_emails: list[str]
    ) -> None:
        """
        One REQUESTED row per recipient; idempotent (ON CONFLICT DO
        NOTHING on (interaction_id, recipient_email)) so a retried
        record-step can never raise or duplicate.
        """

        if not recipient_emails:
            return

        await self.db.execute(
            pg_insert(EmailReadReceipt)
            .values(
                [
                    {
                        "interaction_id": interaction_id,
                        "recipient_email": email,
                        "status": RECEIPT_STATUS_REQUESTED,
                    }
                    for email in recipient_emails
                ]
            )
            .on_conflict_do_nothing(
                constraint="uq_email_read_receipts_interaction_recipient"
            )
        )
        await self.db.flush()

    async def list_for_interactions(
        self, interaction_ids: list[UUID]
    ) -> dict[UUID, list[EmailReadReceipt]]:
        """Batched lookup for response annotation; empty input is a no-op."""

        if not interaction_ids:
            return {}

        rows = (
            (
                await self.db.execute(
                    select(EmailReadReceipt)
                    .where(EmailReadReceipt.interaction_id.in_(interaction_ids))
                    .order_by(
                        EmailReadReceipt.created_at, EmailReadReceipt.recipient_email
                    )
                )
            )
            .scalars()
            .all()
        )

        grouped: dict[UUID, list[EmailReadReceipt]] = {}
        for row in rows:
            grouped.setdefault(row.interaction_id, []).append(row)
        return grouped

    async def find_outbound_by_internet_message_id(
        self, internet_message_id: str
    ) -> Interaction | None:
        """
        The authoritative match: the OUTBOUND interaction whose real
        Graph `internetMessageId` equals the receipt's
        `Original-Message-ID`. Exact match first; a case-insensitive
        retry is accepted ONLY when it yields exactly one row. Never
        matches on conversation, subject, timestamps or the local
        placeholder `message_id`.
        """

        exact = (
            (
                await self.db.execute(
                    select(Interaction).where(
                        Interaction.internet_message_id == internet_message_id,
                        Interaction.direction == InteractionDirection.OUTBOUND,
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            return None

        folded = (
            (
                await self.db.execute(
                    select(Interaction).where(
                        func.lower(Interaction.internet_message_id)
                        == internet_message_id.lower(),
                        Interaction.direction == InteractionDirection.OUTBOUND,
                    )
                )
            )
            .scalars()
            .all()
        )
        return folded[0] if len(folded) == 1 else None

    async def get_for_update(
        self, interaction_id: UUID, recipient_email: str
    ) -> EmailReadReceipt | None:
        return (
            await self.db.execute(
                select(EmailReadReceipt)
                .where(
                    EmailReadReceipt.interaction_id == interaction_id,
                    EmailReadReceipt.recipient_email == recipient_email,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def mdn_already_recorded(self, mdn_message_id: str) -> bool:
        return (
            await self.db.execute(
                select(EmailReadReceipt.receipt_id).where(
                    EmailReadReceipt.mdn_message_id == mdn_message_id
                )
            )
        ).first() is not None

    async def confirm(
        self,
        row: EmailReadReceipt,
        *,
        read_at: datetime | None,
        disposition: str | None,
        mdn_message_id: str | None,
        received_at: datetime | None,
    ) -> None:
        """
        REQUESTED -> CONFIRMED. Callers have already ruled out an
        already-CONFIRMED row (that path is the duplicate branch, which
        only ever moves read_at EARLIER, never regresses status).
        """

        row.status = RECEIPT_STATUS_CONFIRMED
        row.read_at = read_at
        row.disposition = disposition
        row.mdn_message_id = mdn_message_id
        row.received_at = received_at
        await self.db.flush()

    async def keep_earliest_read_at(
        self, row: EmailReadReceipt, candidate: datetime | None
    ) -> None:
        if candidate is not None and (row.read_at is None or candidate < row.read_at):
            row.read_at = candidate
            await self.db.flush()
