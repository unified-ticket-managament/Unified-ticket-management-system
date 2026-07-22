# test_sla_clock_math.py
#
# Pure clock-math unit tests — no database needed. These cover the
# single most important correctness property in the whole SLA
# feature: due_at shifts forward by exactly the pause duration on
# resume (see resolution_sla_repository.py's own module docstring and
# the plan doc's §0), and elapsed_fraction/threshold classification is
# derived correctly from due_at alone.

from datetime import datetime, timedelta, timezone

import pytest

from app.ticketing.repositories.resolution_sla_repository import (
    compute_reshifted_due_at,
    compute_restarted_due_at,
    compute_resumed_due_at,
)
from app.ticketing.services.sla_escalation_rules import thresholds_reached
from app.ticketing.services.sla_service import compute_elapsed_fraction


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, tzinfo=timezone.utc)


class TestComputeResumedDueAt:
    def test_single_pause_shifts_due_at_by_exact_duration(self):
        due_at = _dt(12)
        paused_at = _dt(9)
        resumed_at = _dt(10)  # paused for exactly 1 hour

        result = compute_resumed_due_at(due_at, paused_at, resumed_at)

        assert result == due_at + timedelta(hours=1)

    def test_multiple_pause_resume_cycles_accumulate(self):
        due_at = _dt(12)

        # First cycle: paused 1 hour.
        due_at = compute_resumed_due_at(due_at, _dt(8), _dt(9))
        assert due_at == _dt(13)

        # Second cycle: paused 3 hours, applied on top of the shifted due_at.
        due_at = compute_resumed_due_at(due_at, _dt(14), _dt(17))
        assert due_at == _dt(16)

    def test_zero_duration_pause_is_a_no_op_shift(self):
        due_at = _dt(12)
        same_instant = _dt(9)

        result = compute_resumed_due_at(due_at, same_instant, same_instant)

        assert result == due_at


class TestComputeReshiftedDueAt:
    def test_priority_upgrade_shrinks_remaining_time_proportionally(self):
        # Ticket started 2 days ago on a LOW policy (7-day target),
        # never paused. Upgrading to HIGH (3-day target) now should
        # give it exactly 1 day remaining (3 days target - 2 days
        # already consumed), not a fresh 3-day clock.
        started_at = _dt(0) - timedelta(days=2)
        now = _dt(0)

        new_due_at = compute_reshifted_due_at(
            started_at=started_at,
            total_paused_seconds=0,
            new_target_minutes=3 * 24 * 60,
            now=now,
        )

        assert new_due_at == now + timedelta(days=1)

    def test_prior_pause_time_is_excluded_from_consumed_time(self):
        # Same as above, but 1 of those 2 days was spent paused — only
        # 1 day of *running* time has actually been consumed, so 2
        # days should remain against the new 3-day target.
        started_at = _dt(0) - timedelta(days=2)
        now = _dt(0)

        new_due_at = compute_reshifted_due_at(
            started_at=started_at,
            total_paused_seconds=int(timedelta(days=1).total_seconds()),
            new_target_minutes=3 * 24 * 60,
            now=now,
        )

        assert new_due_at == now + timedelta(days=2)

    def test_downgrade_past_new_target_yields_a_due_at_in_the_past(self):
        # Already consumed more running time than the new (smaller)
        # target allows — the clock is immediately overdue, not
        # clamped to "now".
        started_at = _dt(0) - timedelta(days=5)
        now = _dt(0)

        new_due_at = compute_reshifted_due_at(
            started_at=started_at,
            total_paused_seconds=0,
            new_target_minutes=3 * 24 * 60,
            now=now,
        )

        assert new_due_at == now - timedelta(days=2)


class TestComputeRestartedDueAt:
    # Used only by the escalation-acceptance reshift, deliberately NOT
    # the same formula as TestComputeReshiftedDueAt above — see
    # ResolutionSLARepository.restart_due_at_for_escalation's own
    # docstring. No started_at/paused_seconds input at all: the result
    # depends only on `now` and the new target, ignoring however long
    # the ticket had already been running.
    def test_full_target_from_now_regardless_of_prior_elapsed_time(self):
        now = _dt(12)

        new_due_at = compute_restarted_due_at(new_target_minutes=46, now=now)

        assert new_due_at == now + timedelta(minutes=46)

    def test_a_ticket_running_far_longer_than_the_new_target_still_gets_the_full_window(self):
        # This is exactly the scenario compute_reshifted_due_at's own
        # "downgrade past new target" test above lands in the past for
        # — a ticket that ran far longer than CRITICAL's short target
        # before finally being accepted. The restart variant must NOT
        # reproduce that: the new owner gets the genuine full window.
        now = _dt(12)

        new_due_at = compute_restarted_due_at(new_target_minutes=46, now=now)

        assert new_due_at > now


class TestComputeElapsedFraction:
    @pytest.mark.parametrize(
        "hours_before_due,target_hours,expected",
        [
            (0, 4, 1.0),      # exactly at due_at -> 100%
            (4, 4, 0.0),      # a full target-duration before due_at -> 0%
            (2, 4, 0.5),      # halfway -> 50%
            (-2, 4, 1.5),     # 2h past due_at on a 4h target -> 150%
        ],
    )
    def test_fraction_derived_purely_from_due_at_and_target(
        self, hours_before_due, target_hours, expected
    ):
        now = _dt(12)
        due_at = now + timedelta(hours=hours_before_due)

        fraction = compute_elapsed_fraction(
            due_at=due_at, target_minutes=target_hours * 60, at=now
        )

        assert fraction == pytest.approx(expected)

    def test_zero_target_minutes_is_treated_as_already_complete(self):
        now = _dt(12)
        fraction = compute_elapsed_fraction(due_at=now, target_minutes=0, at=now)
        assert fraction == 1.0


class TestThresholdsReached:
    def test_below_half_elapsed_reaches_nothing(self):
        assert thresholds_reached(0.3) == []

    def test_between_half_elapsed_and_at_risk_reaches_only_half_elapsed(self):
        assert thresholds_reached(0.6) == ["HALF_ELAPSED"]

    def test_between_at_risk_and_breached_reaches_half_elapsed_and_at_risk(self):
        assert thresholds_reached(0.85) == ["HALF_ELAPSED", "AT_RISK"]

    def test_between_breached_and_escalated_reaches_first_three(self):
        assert thresholds_reached(1.1) == ["HALF_ELAPSED", "AT_RISK", "BREACHED"]

    def test_past_escalated_reaches_all_four_in_order(self):
        assert thresholds_reached(1.6) == [
            "HALF_ELAPSED",
            "AT_RISK",
            "BREACHED",
            "ESCALATED",
        ]

    def test_exact_boundary_values_are_inclusive(self):
        assert thresholds_reached(0.5) == ["HALF_ELAPSED"]
        assert thresholds_reached(0.8) == ["HALF_ELAPSED", "AT_RISK"]
        assert thresholds_reached(1.0) == ["HALF_ELAPSED", "AT_RISK", "BREACHED"]
        assert thresholds_reached(1.5) == [
            "HALF_ELAPSED",
            "AT_RISK",
            "BREACHED",
            "ESCALATED",
        ]


class TestThresholdBoundaryRequirements:
    """
    Explicit, individually-named coverage mapped 1:1 to the reported
    issue's own numbered threshold test list — TestThresholdsReached
    above already covers this logic more broadly; these exist purely
    for direct traceability against that list, not new behavior.
    """

    def test_1_before_half_elapsed_no_half_elapsed_notification(self):
        assert "HALF_ELAPSED" not in thresholds_reached(0.49)
        assert thresholds_reached(0.49) == []

    def test_2_exactly_half_elapsed_half_elapsed_only(self):
        assert thresholds_reached(0.5) == ["HALF_ELAPSED"]

    def test_3_between_half_elapsed_and_at_risk_no_at_risk_yet(self):
        assert thresholds_reached(0.65) == ["HALF_ELAPSED"]
        assert "AT_RISK" not in thresholds_reached(0.65)

    def test_4_exactly_at_the_at_risk_threshold_at_risk_included(self):
        assert thresholds_reached(0.8) == ["HALF_ELAPSED", "AT_RISK"]

    def test_5_at_100_percent_breached_included(self):
        assert thresholds_reached(1.0) == ["HALF_ELAPSED", "AT_RISK", "BREACHED"]

    # Test 6 (paused time excluded from elapsed time) is covered by
    # TestComputeResumedDueAt/TestComputeReshiftedDueAt above — due_at
    # is what elapsed_fraction is derived from, and pause duration is
    # exactly what gets excluded via the due_at shift, never read from
    # started_at/pause history at classification time.

    def test_7_multiple_thresholds_crossed_between_runs_all_generated_once_in_order(self):
        # A clock discovered already past both Half Elapsed and At Risk
        # (e.g. a long gap between sweep ticks) must report every
        # crossed threshold, in order, in one call — the sweep's ledger
        # then records all of them together in the same tick, none
        # duplicated on a later tick.
        assert thresholds_reached(0.92) == ["HALF_ELAPSED", "AT_RISK"]

    def test_per_priority_warning_overrides_actually_change_where_thresholds_land(self):
        # Proves the per-priority override plumbing (policy.warning_1_
        # percentage/warning_2_percentage / 100) genuinely changes
        # behavior rather than always falling back to the hardcoded
        # 0.5/0.8 defaults: 0.45 is below the *default* half_elapsed
        # cutoff (0.5) but above this tighter override's (0.25/0.4).
        assert thresholds_reached(0.45, half_elapsed=0.25, at_risk=0.4) == [
            "HALF_ELAPSED",
            "AT_RISK",
        ]
        assert thresholds_reached(0.45) == []  # same fraction, default cutoffs -> nothing yet
