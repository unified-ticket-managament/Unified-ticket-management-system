# test_email_read_receipts_db.py
#
# Real-DB (rolled-back) coverage of the read-receipt schema:
# email_read_receipts + interactions.internet_message_id. Same
# prerequisites as test_message_marks_db.py: a database migrated to
# head, DATABASE_URL pointed at a throwaway database (NEVER the shared
# RDS). Skipped when the new table is absent (database not migrated).

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.email_read_receipt import (
    RECEIPT_STATUS_CONFIRMED,
    RECEIPT_STATUS_REQUESTED,
    EmailReadReceipt,
)
from app.ticketing.models.interaction import Interaction


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            probe = await session.execute(
                text(
                    "select count(*) from information_schema.tables "
                    "where table_name = 'email_read_receipts'"
                )
            )
            if probe.scalar_one() == 0:
                pytest.skip("database is not migrated to the read-receipt revision")
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _outbound(session, *, internet_message_id=None) -> Interaction:
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="REPLY",
        direction=InteractionDirection.OUTBOUND,
        status=InteractionStatus.ASSIGNED,
        payload={"envelope": {}},
        is_visible=True,
        subject="Read receipt schema test",
        internet_message_id=internet_message_id,
    )
    session.add(interaction)
    await session.flush()
    return interaction


def _receipt(interaction_id, recipient="a@example.com", **kw) -> EmailReadReceipt:
    return EmailReadReceipt(
        receipt_id=uuid.uuid4(),
        interaction_id=interaction_id,
        recipient_email=recipient,
        **kw,
    )


async def test_internet_message_id_is_nullable_and_queryable(db_session):
    plain = await _outbound(db_session)
    real = await _outbound(db_session, internet_message_id="<real-id@example.com>")

    assert plain.internet_message_id is None
    found = (
        await db_session.execute(
            select(Interaction.interaction_id).where(
                Interaction.internet_message_id == "<real-id@example.com>"
            )
        )
    ).scalars().all()
    assert found == [real.interaction_id]


async def test_receipt_defaults_to_requested_and_fields_round_trip(db_session):
    interaction = await _outbound(db_session)
    row = _receipt(interaction.interaction_id)
    db_session.add(row)
    await db_session.flush()
    await db_session.refresh(row)

    assert row.status == RECEIPT_STATUS_REQUESTED
    assert row.read_at is None and row.disposition is None
    assert row.mdn_message_id is None and row.received_at is None
    assert row.created_at is not None

    row.status = RECEIPT_STATUS_CONFIRMED
    row.read_at = datetime(2026, 10, 6, 8, 21, 37, tzinfo=timezone.utc)
    row.disposition = "automatic-action/MDN-sent-automatically; displayed"
    await db_session.flush()
    assert row.status == "CONFIRMED"


async def test_unique_interaction_and_recipient(db_session):
    interaction = await _outbound(db_session)
    db_session.add(_receipt(interaction.interaction_id, "a@example.com"))
    db_session.add(_receipt(interaction.interaction_id, "b@example.com"))
    await db_session.flush()  # different recipients: fine

    db_session.add(_receipt(interaction.interaction_id, "a@example.com"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_same_recipient_allowed_on_different_interactions(db_session):
    first = await _outbound(db_session)
    second = await _outbound(db_session)
    db_session.add(_receipt(first.interaction_id, "a@example.com"))
    db_session.add(_receipt(second.interaction_id, "a@example.com"))
    await db_session.flush()


async def test_mdn_message_id_is_unique_but_many_nulls_are_allowed(db_session):
    interaction = await _outbound(db_session)
    # Several REQUESTED rows with NULL mdn_message_id must coexist.
    for who in ("a", "b", "c"):
        db_session.add(_receipt(interaction.interaction_id, f"{who}@example.com"))
    await db_session.flush()

    other = await _outbound(db_session)
    db_session.add(
        _receipt(interaction.interaction_id, "d@example.com", mdn_message_id="<mdn-1@x>")
    )
    await db_session.flush()
    db_session.add(_receipt(other.interaction_id, "d@example.com", mdn_message_id="<mdn-1@x>"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_foreign_key_is_enforced(db_session):
    db_session.add(_receipt(uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_deleting_the_interaction_cascades_to_its_receipts(db_session):
    interaction = await _outbound(db_session)
    db_session.add(_receipt(interaction.interaction_id, "a@example.com"))
    db_session.add(_receipt(interaction.interaction_id, "b@example.com"))
    await db_session.flush()

    await db_session.execute(
        text("delete from interactions where interaction_id = :i"),
        {"i": interaction.interaction_id},
    )
    remaining = (
        await db_session.execute(
            select(EmailReadReceipt).where(
                EmailReadReceipt.interaction_id == interaction.interaction_id
            )
        )
    ).scalars().all()
    assert remaining == []


async def test_expected_indexes_exist(db_session):
    names = {
        r[0]
        for r in (
            await db_session.execute(
                text(
                    "select indexname from pg_indexes where tablename in "
                    "('email_read_receipts', 'interactions')"
                )
            )
        ).all()
    }
    assert "ix_interactions_internet_message_id" in names
    assert "uq_email_read_receipts_mdn_message_id" in names
    assert "uq_email_read_receipts_interaction_recipient" in names
