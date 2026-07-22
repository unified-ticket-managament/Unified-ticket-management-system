# test_sla_breach_notification_repository.py
#
# DB-touching regression coverage for the breach-notification
# idempotency ledger's dedup key (SLABreachNotification /
# SLABreachNotificationRepository). Runs against the real (dev)
# database inside a transaction that is always rolled back at the end —
# same convention as test_escalation_service.py/test_interaction_
# threading.py (no separate test database configured for this
# project). `clock_id` is intentionally an arbitrary UUID throughout —
# SLABreachNotification has no DB-level FK constraint on it (see the
# model's own docstring, "clock_id is polymorphic... no FK constraint"),
# so no Ticket/Client/ResolutionSLA fixtures are needed to exercise
# this repository in isolation.
#
# The central regression here is issue 4 ("regular SLA notifications
# stop after the first escalation"): the ledger used to be unique on
# (clock_type, clock_id, threshold) alone, which meant a Resolution
# clock whose due_at/target gets legitimately restarted in place (same
# resolution_sla_id — see EscalationService._complete_acceptance ->
# SLAService.restart_resolution_clock_for_escalation ->
# ResolutionSLARepository.restart_due_at_for_escalation) could never
# re-fire HALF_ELAPSED/AT_RISK/BREACHED again after they'd already
# fired once pre-escalation. `cycle` (bumped on every such restart —
# see ResolutionSLA.escalation_cycle) is what fixes this.

import uuid

import pytest

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.repositories.sla_breach_notification_repository import (
    SLABreachNotificationRepository,
)

CLOCK_TYPE = "RESOLUTION"


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def test_first_record_for_a_threshold_is_newly_inserted(db_session):
    repo = SLABreachNotificationRepository(db_session)
    clock_id = uuid.uuid4()

    inserted = await repo.try_record(
        clock_type=CLOCK_TYPE, clock_id=clock_id, threshold="HALF_ELAPSED"
    )

    assert inserted is True


async def test_repeated_record_for_the_same_cycle_is_not_reinserted(db_session):
    """
    Core idempotency guarantee (dedup test 23): a scheduler tick that
    re-observes an already-recorded threshold must not record — or
    notify — a second time.
    """

    repo = SLABreachNotificationRepository(db_session)
    clock_id = uuid.uuid4()

    first = await repo.try_record(
        clock_type=CLOCK_TYPE, clock_id=clock_id, threshold="BREACHED", cycle=0
    )
    second = await repo.try_record(
        clock_type=CLOCK_TYPE, clock_id=clock_id, threshold="BREACHED", cycle=0
    )

    assert first is True
    assert second is False


async def test_a_new_cycle_can_re_fire_a_threshold_already_recorded_in_an_earlier_cycle(
    db_session,
):
    """
    THE regression test for issue 4. Once BREACHED fired for cycle 0
    (the pre-escalation lifetime of a Resolution clock), a legitimate
    restart bumps the cycle number, and the same threshold must be able
    to fire again for the new cycle — on the exact same clock_id, which
    never changes across a restart (restart_due_at_for_escalation
    mutates the same ResolutionSLA row in place).
    """

    repo = SLABreachNotificationRepository(db_session)
    clock_id = uuid.uuid4()

    cycle_0_first = await repo.try_record(
        clock_type=CLOCK_TYPE, clock_id=clock_id, threshold="BREACHED", cycle=0
    )
    cycle_0_repeat = await repo.try_record(
        clock_type=CLOCK_TYPE, clock_id=clock_id, threshold="BREACHED", cycle=0
    )
    cycle_1 = await repo.try_record(
        clock_type=CLOCK_TYPE, clock_id=clock_id, threshold="BREACHED", cycle=1
    )

    assert cycle_0_first is True
    assert cycle_0_repeat is False
    assert cycle_1 is True


async def test_different_thresholds_never_block_each_other(db_session):
    repo = SLABreachNotificationRepository(db_session)
    clock_id = uuid.uuid4()

    half_elapsed = await repo.try_record(
        clock_type=CLOCK_TYPE, clock_id=clock_id, threshold="HALF_ELAPSED"
    )
    at_risk = await repo.try_record(
        clock_type=CLOCK_TYPE, clock_id=clock_id, threshold="AT_RISK"
    )

    assert half_elapsed is True
    assert at_risk is True


async def test_response_and_resolution_clock_types_never_block_each_other(db_session):
    repo = SLABreachNotificationRepository(db_session)
    shared_id = uuid.uuid4()  # same UUID reused across both clock types on purpose

    first_response = await repo.try_record(
        clock_type="FIRST_RESPONSE", clock_id=shared_id, threshold="BREACHED"
    )
    resolution = await repo.try_record(
        clock_type=CLOCK_TYPE, clock_id=shared_id, threshold="BREACHED"
    )

    assert first_response is True
    assert resolution is True


async def test_try_record_many_records_every_crossed_threshold_once_in_a_single_batch(
    db_session,
):
    """Test case 7 at the ledger level: a clock discovered already past every threshold gets all of them recorded together, once."""

    repo = SLABreachNotificationRepository(db_session)
    clock_id = uuid.uuid4()

    entries = [
        (CLOCK_TYPE, clock_id, "HALF_ELAPSED", 0),
        (CLOCK_TYPE, clock_id, "AT_RISK", 0),
        (CLOCK_TYPE, clock_id, "BREACHED", 0),
    ]

    newly_recorded = await repo.try_record_many(entries)

    assert newly_recorded == set(entries)


async def test_try_record_many_is_safe_against_a_repeated_scheduler_tick(db_session):
    """
    Dedup test 24's batch-form equivalent: two overlapping/repeated
    sweep ticks observing the same crossed threshold must not both
    record it — the second batch insert records nothing new for an
    already-recorded quadruple, safe with no application-level lock
    (the whole point of the ON CONFLICT DO NOTHING unique index).
    """

    repo = SLABreachNotificationRepository(db_session)
    clock_id = uuid.uuid4()
    entries = [(CLOCK_TYPE, clock_id, "BREACHED", 0)]

    first_tick = await repo.try_record_many(entries)
    second_tick = await repo.try_record_many(entries)

    assert first_tick == set(entries)
    assert second_tick == set()


async def test_try_record_many_treats_distinct_clocks_independently(db_session):
    """
    Dedup test 26 ("different recipients can receive their valid
    notifications"), expressed at this repository's actual granularity:
    the ledger dedupes per-clock (a resolved recipient *set* is
    notified atomically per clock/threshold — see sla_sweep_service.py
    and the design note in this module's own docstring), not globally
    per-threshold — two different tickets' Resolution clocks crossing
    the same threshold in the same tick must never block each other.
    """

    repo = SLABreachNotificationRepository(db_session)
    clock_a, clock_b = uuid.uuid4(), uuid.uuid4()
    entries = [(CLOCK_TYPE, clock_a, "BREACHED", 0), (CLOCK_TYPE, clock_b, "BREACHED", 0)]

    newly_recorded = await repo.try_record_many(entries)

    assert newly_recorded == set(entries)
