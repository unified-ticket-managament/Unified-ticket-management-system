# test_read_receipt_service_db.py
#
# Real-DB (rolled-back) coverage of read-receipt matching, per-recipient
# state, idempotency, the receipt-before-commit race, failure isolation,
# and the send-time recording path. Same prerequisites as
# test_email_read_receipts_db.py: a database migrated to head, DATABASE_URL
# pointed at a THROWAWAY database (never the shared RDS). Skipped when the
# read-receipt table is absent.

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.email_read_receipt import (
    RECEIPT_STATUS_CONFIRMED,
    RECEIPT_STATUS_REQUESTED,
    EmailReadReceipt,
)
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.email_read_receipt_repository import (
    EmailReadReceiptRepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.schemas.email import EmailRequest
from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.mail_provider import MailProviderSendResult
from app.ticketing.services.outbound_dispatcher import OutboundDispatchError
from app.ticketing.services.read_receipt_service import (
    ReadReceiptService,
    ReceiptOutcome,
    load_receipt_statuses,
    tracked_receipt_recipients,
)
from tests.test_mdn_detection import ORIGINAL_ID, _receipt

REAL_ID = "<REAL1@PN0SPRMB0019.INDPRD01.PROD.OUTLOOK.COM>"
OTHER_ID = "<REAL2@PN0SPRMB0019.INDPRD01.PROD.OUTLOOK.COM>"


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


def _envelope(to="a@example.com", cc=(), bcc=(), **kw) -> OutboundEnvelope:
    return OutboundEnvelope(
        from_email="ticketing@example.com",
        to_email=to,
        cc=list(cc),
        bcc=list(bcc),
        subject="Hello",
        message_id=f"<local-{uuid.uuid4().hex}@example.com>",
        body="Hi",
        **kw,
    )


async def _outbound(
    session,
    *,
    internet_message_id=REAL_ID,
    envelope=None,
    track=True,
    direction=InteractionDirection.OUTBOUND,
    conversation_id=None,
) -> Interaction:
    envelope = envelope or _envelope()
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="REPLY",
        direction=direction,
        status=InteractionStatus.ASSIGNED,
        payload={"envelope": envelope.model_dump()},
        is_visible=True,
        subject="Hello",
        internet_message_id=internet_message_id,
        conversation_id=conversation_id,
    )
    session.add(interaction)
    await session.flush()
    if track:
        await EmailReadReceiptRepository(session).create_requested(
            interaction.interaction_id, tracked_receipt_recipients(envelope)
        )
    return interaction


def _mime(*, original=REAL_ID, recipient="a@example.com", disposition=None,
          own_id=None, date="Tue, 6 Oct 2026 08:21:37 +0000"):
    disposition = disposition or "automatic-action/MDN-sent-automatically; displayed"
    fields = (
        f"Final-recipient: RFC822; {recipient}\n"
        f"Disposition: {disposition}\n"
        f"Original-Message-ID: {original}\n"
    )
    raw = _receipt(dsn_fields=fields, date=date)
    if own_id:
        raw = raw.replace(
            b"<RECEIPT-OWN-ID@example.com>", own_id.encode()
        )
    return raw


def _email(**kw) -> EmailRequest:
    base = dict(
        to_email="ticketing@probeps.com",
        from_email="recipient@example.com",
        subject="Read: Hello",
        body="read",
        message_id=f"<{uuid.uuid4().hex}@example.com>",
        is_read_receipt=True,
        provider_message_id="graph-id",
        received_at=datetime(2026, 10, 6, 8, 21, 39, tzinfo=timezone.utc),
    )
    base.update(kw)
    return EmailRequest(**base)


def _service(session, mime, **kw):
    async def _fetch(email):
        return mime

    return ReadReceiptService(
        session, mime_fetcher=_fetch, retry_delays=kw.pop("retry_delays", ()), **kw
    )


async def _rows(session, interaction):
    result = await session.execute(
        select(EmailReadReceipt)
        .where(EmailReadReceipt.interaction_id == interaction.interaction_id)
        .order_by(EmailReadReceipt.recipient_email)
    )
    return {r.recipient_email: r for r in result.scalars().all()}


async def _interaction_count(session):
    return (await session.execute(select(func.count()).select_from(Interaction))).scalar_one()


# ---------------------------------------------------------------
# Tracked recipients
# ---------------------------------------------------------------


def test_tracked_recipients_are_to_and_cc_only_lowercased_and_deduped():
    envelope = _envelope(
        to="Alice@Example.com",
        cc=["bob@example.com", "ALICE@example.com", "carol@example.com"],
        bcc=["hidden@example.com"],
    )
    assert tracked_receipt_recipients(envelope) == [
        "alice@example.com",
        "bob@example.com",
        "carol@example.com",
    ]


def test_tracked_recipients_use_the_full_to_list_when_present():
    envelope = _envelope(to="a@example.com", cc=["c@example.com"])
    envelope = envelope.model_copy(update={"to_emails": ["a@example.com", "b@example.com"]})
    assert tracked_receipt_recipients(envelope) == [
        "a@example.com", "b@example.com", "c@example.com"
    ]


# ---------------------------------------------------------------
# Read-side gating: only messages that asked for a receipt are looked up
# ---------------------------------------------------------------


def test_receipt_was_requested_reads_the_persisted_envelope():
    from app.ticketing.services.read_receipt_service import receipt_was_requested

    asked = SimpleNamespace(payload={"envelope": {"read_receipt_requested": True}})
    not_asked = SimpleNamespace(payload={"envelope": {"read_receipt_requested": False}})
    old_row = SimpleNamespace(payload={"envelope": {"subject": "pre-feature row"}})
    inbound = SimpleNamespace(payload={"subject": "hi"})
    malformed = SimpleNamespace(payload=None)

    assert receipt_was_requested(asked) is True
    assert receipt_was_requested(not_asked) is False
    assert receipt_was_requested(old_row) is False
    assert receipt_was_requested(inbound) is False
    assert receipt_was_requested(malformed) is False
    assert receipt_was_requested(SimpleNamespace(payload={"envelope": "oops"})) is False


async def test_status_lookup_issues_no_query_when_nothing_requested():
    class _ExplodingDb:
        def begin_nested(self):
            raise AssertionError("no query/savepoint may run for an empty id list")

    assert await load_receipt_statuses(_ExplodingDb(), []) == {}


# ---------------------------------------------------------------
# Matching
# ---------------------------------------------------------------


async def test_exact_match_confirms_the_right_recipient(db_session):
    outbound = await _outbound(db_session)

    outcome = await _service(db_session, _mime()).process_receipt(_email())

    assert outcome is ReceiptOutcome.CONFIRMED
    row = (await _rows(db_session, outbound))["a@example.com"]
    assert row.status == RECEIPT_STATUS_CONFIRMED
    assert row.disposition == "automatic-action/MDN-sent-automatically; displayed"
    assert row.mdn_message_id == "<RECEIPT-OWN-ID@example.com>"
    assert row.read_at == datetime(2026, 10, 6, 8, 21, 37, tzinfo=timezone.utc)
    assert row.received_at == datetime(2026, 10, 6, 8, 21, 39, tzinfo=timezone.utc)


async def test_receipt_creates_no_interaction(db_session):
    await _outbound(db_session)
    before = await _interaction_count(db_session)

    await _service(db_session, _mime()).process_receipt(_email())

    assert await _interaction_count(db_session) == before


async def test_match_works_with_no_in_reply_to_or_references(db_session):
    # The verified receipt has neither header; the match must not need them.
    mime = _mime()
    assert b"In-Reply-To" not in mime and b"References" not in mime
    outbound = await _outbound(db_session)

    assert await _service(db_session, mime).process_receipt(_email()) is ReceiptOutcome.CONFIRMED
    assert (await _rows(db_session, outbound))["a@example.com"].status == "CONFIRMED"


async def test_two_messages_in_one_conversation_update_only_the_right_one(db_session):
    first = await _outbound(db_session, internet_message_id=REAL_ID, conversation_id="conv-1")
    second = await _outbound(db_session, internet_message_id=OTHER_ID, conversation_id="conv-1")

    outcome = await _service(db_session, _mime(original=OTHER_ID)).process_receipt(_email())

    assert outcome is ReceiptOutcome.CONFIRMED
    assert (await _rows(db_session, second))["a@example.com"].status == "CONFIRMED"
    assert (await _rows(db_session, first))["a@example.com"].status == "REQUESTED"


async def test_local_placeholder_message_id_is_never_a_match_key(db_session):
    envelope = _envelope()
    outbound = await _outbound(db_session, internet_message_id=None, envelope=envelope)
    outbound.message_id = "<placeholder-only@example.com>"
    await db_session.flush()

    outcome = await _service(
        db_session, _mime(original="<placeholder-only@example.com>")
    ).process_receipt(_email())

    assert outcome is ReceiptOutcome.UNMATCHED_UNKNOWN_MESSAGE
    assert (await _rows(db_session, outbound))["a@example.com"].status == "REQUESTED"


async def test_unknown_message_id_is_consumed_unmatched(db_session):
    await _outbound(db_session)
    before = await _interaction_count(db_session)

    outcome = await _service(
        db_session, _mime(original="<nobody-sent-this@example.com>")
    ).process_receipt(_email())

    assert outcome is ReceiptOutcome.UNMATCHED_UNKNOWN_MESSAGE
    assert await _interaction_count(db_session) == before


async def test_inbound_row_with_the_same_id_never_matches(db_session):
    outbound = await _outbound(
        db_session, direction=InteractionDirection.INBOUND, track=True
    )
    outcome = await _service(db_session, _mime()).process_receipt(_email())
    assert outcome is ReceiptOutcome.UNMATCHED_UNKNOWN_MESSAGE
    assert (await _rows(db_session, outbound))["a@example.com"].status == "REQUESTED"


async def test_case_insensitive_retry_only_when_unique(db_session):
    outbound = await _outbound(db_session, internet_message_id="<MiXeD@Example.com>")

    outcome = await _service(
        db_session, _mime(original="<mixed@example.com>")
    ).process_receipt(_email())
    assert outcome is ReceiptOutcome.CONFIRMED
    assert (await _rows(db_session, outbound))["a@example.com"].status == "CONFIRMED"


async def test_case_insensitive_collision_is_ambiguous_and_unmatched(db_session):
    await _outbound(db_session, internet_message_id="<Dup@Example.com>")
    await _outbound(db_session, internet_message_id="<DUP@example.com>")

    outcome = await _service(
        db_session, _mime(original="<dup@example.com>")
    ).process_receipt(_email())
    assert outcome is ReceiptOutcome.UNMATCHED_UNKNOWN_MESSAGE


# ---------------------------------------------------------------
# Recipient validation
# ---------------------------------------------------------------


async def test_wrong_recipient_is_unmatched_and_attributed_to_nobody(db_session):
    outbound = await _outbound(db_session)

    outcome = await _service(
        db_session, _mime(recipient="stranger@example.com")
    ).process_receipt(_email())

    assert outcome is ReceiptOutcome.UNMATCHED_RECIPIENT
    rows = await _rows(db_session, outbound)
    assert set(rows) == {"a@example.com"} and rows["a@example.com"].status == "REQUESTED"


async def test_bcc_recipient_is_not_tracked_and_cannot_confirm(db_session):
    envelope = _envelope(to="a@example.com", bcc=["hidden@example.com"])
    outbound = await _outbound(db_session, envelope=envelope)

    assert set(await _rows(db_session, outbound)) == {"a@example.com"}
    outcome = await _service(
        db_session, _mime(recipient="hidden@example.com")
    ).process_receipt(_email())
    assert outcome is ReceiptOutcome.UNMATCHED_RECIPIENT


async def test_to_and_cc_each_confirm_independently(db_session):
    envelope = _envelope(to="a@example.com", cc=["b@example.com", "c@example.com"])
    outbound = await _outbound(db_session, envelope=envelope)

    initial = await _rows(db_session, outbound)
    assert set(initial) == {"a@example.com", "b@example.com", "c@example.com"}
    assert {row.status for row in initial.values()} == {"REQUESTED"}

    # A reads at 10:00, B reads at 10:15, C never answers.
    a = await _service(
        db_session, _mime(recipient="a@example.com", own_id="<mdn-a@example.com>",
                          date="Tue, 6 Oct 2026 10:00:00 +0000")
    ).process_receipt(_email())
    b = await _service(
        db_session, _mime(recipient="b@example.com", own_id="<mdn-b@example.com>",
                          date="Tue, 6 Oct 2026 10:15:00 +0000")
    ).process_receipt(_email())

    assert a is ReceiptOutcome.CONFIRMED and b is ReceiptOutcome.CONFIRMED
    rows = await _rows(db_session, outbound)
    assert rows["a@example.com"].status == "CONFIRMED"
    assert rows["a@example.com"].read_at.hour == 10 and rows["a@example.com"].read_at.minute == 0
    assert rows["b@example.com"].status == "CONFIRMED"
    assert rows["b@example.com"].read_at.minute == 15
    # No receipt from C: still just "requested" — never "unread".
    assert rows["c@example.com"].status == "REQUESTED"
    assert rows["c@example.com"].read_at is None


# ---------------------------------------------------------------
# Disposition
# ---------------------------------------------------------------


@pytest.mark.parametrize(
    "disposition",
    [
        "manual-action/MDN-sent-manually; denied",
        "automatic-action/MDN-sent-automatically; deleted",
        "gibberish",
    ],
)
async def test_non_displayed_disposition_is_never_confirmed_but_is_preserved(
    db_session, disposition
):
    outbound = await _outbound(db_session)

    outcome = await _service(
        db_session, _mime(disposition=disposition, own_id="<mdn-nd@example.com>")
    ).process_receipt(_email())

    assert outcome is ReceiptOutcome.NOT_DISPLAYED
    row = (await _rows(db_session, outbound))["a@example.com"]
    assert row.status == RECEIPT_STATUS_REQUESTED  # no invented DECLINED state
    assert row.disposition == disposition
    assert row.read_at is None


async def test_a_later_displayed_receipt_still_confirms_after_a_non_displayed_one(db_session):
    outbound = await _outbound(db_session)
    await _service(
        db_session, _mime(disposition="manual-action/MDN-sent-manually; denied",
                          own_id="<mdn-1@example.com>")
    ).process_receipt(_email())

    outcome = await _service(
        db_session, _mime(own_id="<mdn-2@example.com>")
    ).process_receipt(_email())

    assert outcome is ReceiptOutcome.CONFIRMED
    assert (await _rows(db_session, outbound))["a@example.com"].status == "CONFIRMED"


# ---------------------------------------------------------------
# Malformed receipts
# ---------------------------------------------------------------


@pytest.mark.parametrize(
    "mime, expected",
    [
        (None, ReceiptOutcome.MALFORMED),
        (b"", ReceiptOutcome.MALFORMED),
        (b"\x00\xff garbage", ReceiptOutcome.UNMATCHED_NO_ORIGINAL_ID),
    ],
)
async def test_malformed_receipts_are_consumed_without_side_effects(db_session, mime, expected):
    outbound = await _outbound(db_session)
    before = await _interaction_count(db_session)

    outcome = await _service(db_session, mime).process_receipt(_email())

    assert outcome is expected
    assert await _interaction_count(db_session) == before
    assert (await _rows(db_session, outbound))["a@example.com"].status == "REQUESTED"


async def test_missing_original_message_id_and_missing_recipient(db_session):
    outbound = await _outbound(db_session)
    no_id = _receipt(dsn_fields=(
        "Final-recipient: RFC822; a@example.com\n"
        "Disposition: automatic-action/MDN-sent-automatically; displayed\n"
    ))
    no_rcpt = _receipt(dsn_fields=(
        "Disposition: automatic-action/MDN-sent-automatically; displayed\n"
        f"Original-Message-ID: {REAL_ID}\n"
    ))

    assert await _service(db_session, no_id).process_receipt(_email()) is (
        ReceiptOutcome.UNMATCHED_NO_ORIGINAL_ID
    )
    assert await _service(db_session, no_rcpt).process_receipt(_email()) is (
        ReceiptOutcome.UNMATCHED_RECIPIENT
    )
    assert (await _rows(db_session, outbound))["a@example.com"].status == "REQUESTED"


# ---------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------


async def test_same_receipt_twice_is_one_row_and_one_update(db_session):
    outbound = await _outbound(db_session)
    mime = _mime(own_id="<mdn-dup@example.com>")

    first = await _service(db_session, mime).process_receipt(_email())
    second = await _service(db_session, mime).process_receipt(_email())

    assert first is ReceiptOutcome.CONFIRMED and second is ReceiptOutcome.DUPLICATE
    assert len(await _rows(db_session, outbound)) == 1


async def test_a_new_receipt_never_regresses_or_duplicates_a_confirmed_row(db_session):
    outbound = await _outbound(db_session)
    await _service(
        db_session, _mime(own_id="<mdn-1@example.com>", date="Tue, 6 Oct 2026 09:00:00 +0000")
    ).process_receipt(_email())

    # A second, DIFFERENT receipt: later -> read_at unchanged ...
    later = await _service(
        db_session, _mime(own_id="<mdn-2@example.com>", date="Tue, 6 Oct 2026 11:00:00 +0000")
    ).process_receipt(_email())
    row = (await _rows(db_session, outbound))["a@example.com"]
    assert later is ReceiptOutcome.DUPLICATE and row.read_at.hour == 9

    # ... earlier -> only the TIME moves earlier; status stays CONFIRMED.
    earlier = await _service(
        db_session, _mime(own_id="<mdn-3@example.com>", date="Tue, 6 Oct 2026 07:00:00 +0000")
    ).process_receipt(_email())
    await db_session.refresh(row)
    assert earlier is ReceiptOutcome.DUPLICATE
    assert row.status == "CONFIRMED" and row.read_at.hour == 7
    assert row.mdn_message_id == "<mdn-1@example.com>"


async def test_the_receipts_own_message_id_is_a_second_idempotency_guard(db_session):
    first = await _outbound(db_session, internet_message_id=REAL_ID)
    second = await _outbound(db_session, internet_message_id=OTHER_ID)
    mime_for_first = _mime(original=REAL_ID, own_id="<same-mdn@example.com>")
    mime_for_second = _mime(original=OTHER_ID, own_id="<same-mdn@example.com>")

    assert await _service(db_session, mime_for_first).process_receipt(_email()) is (
        ReceiptOutcome.CONFIRMED
    )
    # Same receipt message id replayed against another original: refused.
    assert await _service(db_session, mime_for_second).process_receipt(_email()) is (
        ReceiptOutcome.DUPLICATE
    )
    assert (await _rows(db_session, second))["a@example.com"].status == "REQUESTED"
    assert (await _rows(db_session, first))["a@example.com"].status == "CONFIRMED"


async def test_concurrent_duplicate_receipts_settle_to_one_confirmation():
    # Two real sessions racing on the same receipt. Committed data, so
    # this test cleans up after itself.
    async with AsyncSessionLocal() as setup:
        probe = await setup.execute(
            text("select count(*) from information_schema.tables where table_name='email_read_receipts'")
        )
        if probe.scalar_one() == 0:
            pytest.skip("database is not migrated to the read-receipt revision")
        unique_id = f"<RACE-{uuid.uuid4().hex}@example.com>"
        outbound = await _outbound(setup, internet_message_id=unique_id)
        interaction_id = outbound.interaction_id
        await setup.commit()

    async def _process(own_id):
        async with AsyncSessionLocal() as session:
            outcome = await _service(
                session, _mime(original=unique_id, own_id=own_id)
            ).process_receipt(_email())
            await session.commit()
            return outcome

    try:
        outcomes = await asyncio.gather(
            _process("<race-mdn-1@example.com>"), _process("<race-mdn-2@example.com>")
        )
        assert sorted(o.value for o in outcomes) == ["confirmed", "duplicate"]

        async with AsyncSessionLocal() as check:
            rows = (
                await check.execute(
                    select(EmailReadReceipt).where(
                        EmailReadReceipt.interaction_id == interaction_id
                    )
                )
            ).scalars().all()
            assert len(rows) == 1 and rows[0].status == "CONFIRMED"
    finally:
        async with AsyncSessionLocal() as cleanup:
            await cleanup.execute(
                text("delete from interactions where interaction_id = :i"),
                {"i": interaction_id},
            )
            await cleanup.commit()
        await engine.dispose()


# ---------------------------------------------------------------
# Race: receipt arrives before the send's own transaction commits
# ---------------------------------------------------------------


async def test_receipt_before_the_send_commits_is_matched_by_a_bounded_retry(db_session):
    sleeps: list[float] = []
    created: dict = {}

    async def _fake_sleep(delay):
        sleeps.append(delay)
        # The send "commits" between the first lookup and the retry.
        if "interaction" not in created:
            created["interaction"] = await _outbound(db_session)

    service = ReadReceiptService(
        db_session,
        mime_fetcher=lambda email: asyncio.sleep(0, result=_mime()),
        retry_delays=(1.0, 2.0),
        sleep=_fake_sleep,
    )

    outcome = await service.process_receipt(_email())

    assert outcome is ReceiptOutcome.CONFIRMED
    assert sleeps == [1.0]  # found on the first retry — no further waiting
    assert (await _rows(db_session, created["interaction"]))["a@example.com"].status == "CONFIRMED"


async def test_unmatched_receipt_retries_are_strictly_bounded(db_session):
    sleeps: list[float] = []

    async def _fake_sleep(delay):
        sleeps.append(delay)

    service = ReadReceiptService(
        db_session,
        mime_fetcher=lambda email: asyncio.sleep(0, result=_mime(original="<ghost@example.com>")),
        retry_delays=(1.0, 2.0),
        sleep=_fake_sleep,
    )

    assert await service.process_receipt(_email()) is ReceiptOutcome.UNMATCHED_UNKNOWN_MESSAGE
    assert sleeps == [1.0, 2.0]  # exactly the configured bound, never more


# ---------------------------------------------------------------
# Failure isolation (real session)
# ---------------------------------------------------------------


async def test_fetch_failure_is_absorbed_and_the_session_stays_usable(db_session):
    outbound = await _outbound(db_session)

    async def _boom(email):
        raise RuntimeError("graph exploded")

    outcome = await ReadReceiptService(db_session, mime_fetcher=_boom, retry_delays=()).process_receipt(
        _email()
    )

    assert outcome is ReceiptOutcome.ERROR
    # Prior work survives and the session still works.
    assert (await _rows(db_session, outbound))["a@example.com"].status == "REQUESTED"


async def test_db_failure_inside_the_savepoint_rolls_back_only_the_receipt(db_session, monkeypatch):
    outbound = await _outbound(db_session)

    async def _explode(self, row, **kw):
        row.status = RECEIPT_STATUS_CONFIRMED  # a partial write...
        await self.db.flush()
        raise RuntimeError("write failed")

    monkeypatch.setattr(EmailReadReceiptRepository, "confirm", _explode)

    outcome = await _service(db_session, _mime()).process_receipt(_email())

    assert outcome is ReceiptOutcome.ERROR
    # ...is rolled back with the savepoint; the outbound row is intact
    # and the session is still usable.
    await db_session.refresh(
        (await _rows(db_session, outbound))["a@example.com"]
    )
    assert (await _rows(db_session, outbound))["a@example.com"].status == "REQUESTED"
    assert await _interaction_count(db_session) >= 1


# ---------------------------------------------------------------
# Status annotation (read side)
# ---------------------------------------------------------------


async def test_load_receipt_statuses_groups_by_interaction(db_session):
    envelope = _envelope(to="a@example.com", cc=["b@example.com"])
    outbound = await _outbound(db_session, envelope=envelope)
    plain = await _outbound(db_session, internet_message_id="<plain@example.com>", track=False)

    statuses = await load_receipt_statuses(
        db_session, [outbound.interaction_id, plain.interaction_id]
    )

    assert plain.interaction_id not in statuses
    assert {s.recipient_email: s.status for s in statuses[outbound.interaction_id]} == {
        "a@example.com": "REQUESTED",
        "b@example.com": "REQUESTED",
    }
    assert await load_receipt_statuses(db_session, []) == {}


async def test_load_receipt_statuses_failure_degrades_without_poisoning_the_session(
    db_session, monkeypatch
):
    outbound = await _outbound(db_session)

    async def _boom(self, ids):
        raise RuntimeError("table missing")

    monkeypatch.setattr(EmailReadReceiptRepository, "list_for_interactions", _boom)

    assert await load_receipt_statuses(db_session, [outbound.interaction_id]) == {}
    # Session still usable afterwards.
    assert await _interaction_count(db_session) >= 1


# ---------------------------------------------------------------
# Send-time recording (InteractionService._dispatch_and_record)
# ---------------------------------------------------------------


class _ScriptedDispatcher:
    def __init__(self, *results):
        self._results = list(results)
        self.calls = 0

    async def dispatch(self, interaction_id, envelope):
        self.calls += 1
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _recorder(session, monkeypatch, dispatcher):
    # The real recorder commits; keep everything inside the test's
    # rolled-back transaction.
    monkeypatch.setattr(session, "commit", session.flush)
    service = object.__new__(InteractionService)
    service.interaction_repository = InteractionRepository(session)
    service.outbound_dispatcher = dispatcher
    return service


async def _pending(session, envelope):
    interaction = await _outbound(session, internet_message_id=None, track=False, envelope=envelope)
    interaction.payload = {**interaction.payload, "dispatch_status": "PENDING_SEND"}
    await session.flush()
    return interaction


async def test_successful_requested_send_stores_real_id_and_one_row_per_to_cc(
    db_session, monkeypatch
):
    envelope = _envelope(
        to="a@example.com", cc=["b@example.com"], bcc=["hidden@example.com"],
        read_receipt_requested=True,
    )
    interaction = await _pending(db_session, envelope)
    service = _recorder(
        db_session,
        monkeypatch,
        _ScriptedDispatcher(
            MailProviderSendResult(provider_message_id="p1", status="SENT", internet_message_id=REAL_ID)
        ),
    )

    await service._dispatch_and_record(interaction, envelope)

    await db_session.refresh(interaction)
    assert interaction.internet_message_id == REAL_ID
    assert interaction.dispatch_status == "SENT"
    assert set(await _rows(db_session, interaction)) == {"a@example.com", "b@example.com"}
    # And the matching key actually finds it.
    found = await EmailReadReceiptRepository(db_session).find_outbound_by_internet_message_id(REAL_ID)
    assert found.interaction_id == interaction.interaction_id


async def test_unrequested_send_creates_no_receipt_rows(db_session, monkeypatch):
    envelope = _envelope()
    interaction = await _pending(db_session, envelope)
    service = _recorder(
        db_session,
        monkeypatch,
        _ScriptedDispatcher(MailProviderSendResult(provider_message_id="p", status="SENT")),
    )

    await service._dispatch_and_record(interaction, envelope)

    await db_session.refresh(interaction)
    assert interaction.dispatch_status == "SENT"
    assert interaction.internet_message_id is None  # direct path: nothing inferred
    assert await _rows(db_session, interaction) == {}


async def test_failed_send_creates_no_rows_and_stores_no_id(db_session, monkeypatch):
    envelope = _envelope(read_receipt_requested=True)
    interaction = await _pending(db_session, envelope)
    service = _recorder(
        db_session,
        monkeypatch,
        _ScriptedDispatcher(OutboundDispatchError("boom", operation="sendDraft", status_code=500)),
    )

    with pytest.raises(Exception):
        await service._dispatch_and_record(interaction, envelope)

    await db_session.refresh(interaction)
    assert interaction.dispatch_status == "FAILED"
    assert interaction.internet_message_id is None
    assert await _rows(db_session, interaction) == {}


async def test_retry_after_failure_stores_the_successful_attempts_id(db_session, monkeypatch):
    envelope = _envelope(read_receipt_requested=True)
    interaction = await _pending(db_session, envelope)
    dispatcher = _ScriptedDispatcher(
        OutboundDispatchError("boom", operation="sendDraft", status_code=500),
        MailProviderSendResult(provider_message_id="p2", status="SENT", internet_message_id=OTHER_ID),
    )
    service = _recorder(db_session, monkeypatch, dispatcher)

    with pytest.raises(Exception):
        await service._dispatch_and_record(interaction, envelope)
    assert await _rows(db_session, interaction) == {}

    await service._dispatch_and_record(interaction, envelope)  # the retry

    await db_session.refresh(interaction)
    assert interaction.internet_message_id == OTHER_ID
    assert set(await _rows(db_session, interaction)) == {"a@example.com"}


async def test_row_creation_failure_never_fails_the_send_record(db_session, monkeypatch):
    envelope = _envelope(read_receipt_requested=True)
    interaction = await _pending(db_session, envelope)

    async def _boom(self, interaction_id, recipients):
        raise RuntimeError("receipts table unavailable")

    monkeypatch.setattr(EmailReadReceiptRepository, "create_requested", _boom)
    service = _recorder(
        db_session,
        monkeypatch,
        _ScriptedDispatcher(
            MailProviderSendResult(provider_message_id="p", status="SENT", internet_message_id=REAL_ID)
        ),
    )

    await service._dispatch_and_record(interaction, envelope)  # must not raise

    await db_session.refresh(interaction)
    assert interaction.dispatch_status == "SENT" and interaction.internet_message_id == REAL_ID


async def test_create_requested_is_idempotent(db_session):
    outbound = await _outbound(db_session, track=False)
    repository = EmailReadReceiptRepository(db_session)

    await repository.create_requested(outbound.interaction_id, ["a@example.com", "b@example.com"])
    await repository.create_requested(outbound.interaction_id, ["a@example.com"])
    await repository.create_requested(outbound.interaction_id, [])

    assert set(await _rows(db_session, outbound)) == {"a@example.com", "b@example.com"}
