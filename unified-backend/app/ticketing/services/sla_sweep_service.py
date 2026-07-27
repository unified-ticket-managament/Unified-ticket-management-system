import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.core.config import get_settings
from app.notifications.service import NotificationService
from app.ticketing.enums import ActorRole, AuditEntityType, AuditEventType
from app.ticketing.models.first_response_sla import FirstResponseSLA
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.first_response_sla_repository import (
    FirstResponseSLARepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.resolution_sla_repository import (
    ResolutionSLARepository,
)
from app.ticketing.repositories.sla_breach_notification_repository import (
    SLABreachNotificationRepository,
)
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_escalation_repository import (
    TicketEscalationRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.sla import SLASweepResponse
from app.ticketing.services.audit_log_service import AuditLogService
from app.ticketing.services.escalation_handling_sla_service import (
    build_escalation_handling_sla_service,
)
from app.ticketing.services.escalation_service import EscalationService
from app.ticketing.services.sla_breach_notifier import (
    CLOCK_TYPE_FIRST_RESPONSE,
    NOTIFICATION_TYPE_BY_THRESHOLD,
    build_absolute_link,
    notify_first_response_threshold,
    resolve_global_inbox_user_ids,
    send_notification_emails,
)
from app.ticketing.services.sla_escalation_rules import (
    RESOLUTION_RULES_CURRENT_OWNER,
    TEAM_LEAD_ROLE_NAME,
    RecipientContext,
    resolve_recipients,
    thresholds_reached,
)
from app.ticketing.services.sla_service import compute_elapsed_fraction

logger = logging.getLogger(__name__)

CLOCK_TYPE_RESOLUTION = "RESOLUTION"

# Fixed regardless of per-priority policy overrides — BREACHED/ESCALATED
# never vary (see thresholds_reached's own docstring); only the two
# warning tiers are configurable.
_FIXED_THRESHOLD_CUTOFFS = {"BREACHED": 1.0, "ESCALATED": 1.5}


def _late_thresholds(
    reached: list[str],
    *,
    due_at: datetime,
    target_minutes: int,
    now: datetime,
    half_elapsed_cutoff: float,
    at_risk_cutoff: float,
    grace_seconds: float,
) -> list[tuple[str, float]]:
    """
    For each threshold this tick found in `reached`, computes how many
    seconds after its true crossing instant `now` actually is — using
    the same due_at-based math as compute_elapsed_fraction (so it's
    correctly pause/resume-robust, never touching started_at) — and
    returns only the ones whose lateness exceeds `grace_seconds`.

    A small amount of lateness (up to roughly one sweep interval) is
    completely normal for a polling sweep and not worth logging.
    Lateness far beyond that — the only thing this returns — means the
    scheduler simply didn't tick for a stretch (a process restart,
    freeze, or a competing/absent scheduler — see root CLAUDE.md's
    Deployment section), not a defect in threshold classification
    itself: `thresholds_reached` still correctly detects every crossed
    threshold the moment it's finally checked, it just checked late.
    This is purely a diagnostic signal for that operational gap.
    """

    target_seconds = target_minutes * 60
    if target_seconds <= 0:
        return []

    cutoffs = {
        "HALF_ELAPSED": half_elapsed_cutoff,
        "AT_RISK": at_risk_cutoff,
        **_FIXED_THRESHOLD_CUTOFFS,
    }

    late: list[tuple[str, float]] = []
    for threshold in reached:
        cutoff = cutoffs.get(threshold)
        if cutoff is None:
            continue
        ideal_at = due_at - timedelta(seconds=target_seconds * (1 - cutoff))
        lateness = (now - ideal_at).total_seconds()
        if lateness > grace_seconds:
            late.append((threshold, lateness))
    return late


class SLASweepService:
    """
    Runs one breach-detection pass over every active SLA clock — the
    Render Cron Job's target, called via POST /internal/sla/sweep.

    Shape: (1) two cheap, status-filtered queries fetch every active
    clock; (2) classify each clock's crossed thresholds in Python
    (compute_elapsed_fraction + thresholds_reached, both pure); (3) one
    batched INSERT ... ON CONFLICT DO NOTHING ... RETURNING checks
    every crossed (clock_type, clock_id, threshold, cycle) quadruple's
    idempotency ledger at once (SLABreachNotificationRepository.
    try_record_many) and reports exactly which are newly-crossed; (4)
    only those get real recipient-resolution + notify + audit-log work,
    each isolated in its own SAVEPOINT (db.begin_nested()) so one
    entry's failure can't affect another's in the same run.

    Every per-clock lookup (ticket, client, assigned agent) is also
    batch-prefetched once up front rather than fetched per crossed
    threshold — both of these batching passes exist because Neon's
    per-round-trip latency (several hundred ms, confirmed via this
    project's own Server-Timing investigation) means round-trip
    *count*, not per-query cost, dominates this sweep's wall-clock
    time; a live smoke test before this batching showed consecutive
    clocks' notifications landing 4-6s apart, almost entirely idle
    network time.

    Recipient resolution is table-driven (see sla_escalation_rules.py)
    rather than hardcoded if/elif — who gets notified at each threshold
    is declared once, there, and this service only interprets it.

    Notifications go out two ways: in-app (NotificationService, always,
    regardless of email config) and real outbound email (EmailSender —
    see app/core/email_sender.py — via sla_breach_notifier.py's
    send_notification_emails, gated only on user_repository being
    available, which it always is here). Email falls back to a
    logging-only no-op until smtp_host is actually configured in
    Settings — this is a separate, narrower seam from
    OutboundDispatcher (the client-facing reply-email transport, still
    a no-op today), not the same thing.
    """

    def __init__(
        self,
        sla_policy_repository: SLAPolicyRepository,
        first_response_sla_repository: FirstResponseSLARepository,
        resolution_sla_repository: ResolutionSLARepository,
        sla_breach_notification_repository: SLABreachNotificationRepository,
        ticket_repository: TicketRepository,
        client_repository: ClientRepository,
        user_repository: UserRepository,
        notification_service: NotificationService | None = None,
        interaction_repository: InteractionRepository | None = None,
    ):
        self.sla_policy_repository = sla_policy_repository
        self.first_response_sla_repository = first_response_sla_repository
        self.resolution_sla_repository = resolution_sla_repository
        self.sla_breach_notification_repository = sla_breach_notification_repository
        self.ticket_repository = ticket_repository
        self.client_repository = client_repository
        self.user_repository = user_repository
        self.notification_service = notification_service
        self.interaction_repository = interaction_repository
        # Extends this same background worker to also evaluate the
        # internal escalation workflow (create on first breach,
        # auto-advance an ignored acknowledgment) rather than standing
        # up a second scheduler — see EscalationService's own docstring.
        # Never touches ResolutionSLA/FirstResponseSLA itself.
        self.escalation_handling_sla_service = build_escalation_handling_sla_service(
            ticket_repository.db
        )
        self.escalation_service = EscalationService(
            ticket_escalation_repository=TicketEscalationRepository(ticket_repository.db),
            ticket_repository=ticket_repository,
            resolution_sla_repository=resolution_sla_repository,
            sla_policy_repository=sla_policy_repository,
            user_repository=user_repository,
            notification_service=notification_service,
            escalation_handling_sla_service=self.escalation_handling_sla_service,
        )

    async def run_sweep(self) -> SLASweepResponse:
        # Every repository here is constructed from the same AsyncSession
        # per request (see api/sla_internal.py's run_sla_sweep) — reusing
        # one of them for `.db` is already this codebase's established
        # pattern (AuditLogService.log_event below does the same thing).
        db = self.ticket_repository.db

        started_at = datetime.now(timezone.utc)
        now = started_at

        policies = await self.sla_policy_repository.list_all()
        target_by_priority_fr = {p.priority: p.first_response_target_minutes for p in policies}
        # Per-priority "Warning 1"/"Warning 2" overrides (see SLAPolicy.
        # warning_1_percentage/warning_2_percentage and the admin-facing
        # SLA Timing Matrix) — BREACHED/ESCALATED stay fixed globally,
        # only these two warning tiers vary per priority.
        policy_by_priority = {p.priority: p for p in policies}

        counts = {
            "first_response_half_elapsed": 0,
            "first_response_at_risk": 0,
            "first_response_breached": 0,
            "resolution_half_elapsed": 0,
            "resolution_at_risk": 0,
            "resolution_breached": 0,
            "resolution_escalated": 0,
        }
        notifications_sent = 0
        escalations_created = 0
        errors = 0
        # A newly-crossed threshold whose ledger row was recorded (so
        # it will never be retried) but whose recipient resolution came
        # back empty — see _notify_resolution's own comment. Previously
        # completely invisible; now surfaced both in logs and here.
        recipients_empty = 0
        # A threshold discovered well after its true crossing instant —
        # see _late_thresholds' own docstring. Purely diagnostic: a
        # nonzero count here means the scheduler had a real continuity
        # gap (process restart/freeze/absence), not that classification
        # or notification logic did anything wrong.
        late_threshold_detections = 0
        # Anything under ~5 sweep intervals (floored at 60s) is ordinary
        # polling jitter, not worth logging — see _late_thresholds.
        late_grace_seconds = max(60.0, get_settings().sla_sweep_interval_seconds * 5)

        global_inbox_ids = await self._global_inbox_user_ids()

        # ticket_type -> (team_leads, staff-under-them), populated lazily
        # the first time an unclaimed Resolution clock in that category
        # is seen, reused for every later clock sharing it in this run —
        # caps the extra query fan-out the Case-1 (Team Lead + team
        # members) escalation path would otherwise add per-clock.
        category_cache: dict[str, tuple[list, list]] = {}

        # Every (clock_type, clock_id, threshold, cycle) quadruple that
        # crossed this tick, across both clock types — checked against
        # the idempotency ledger in one batch below, not one round trip
        # each. `cycle` is always 0 for First Response (never restarts);
        # for Resolution it's the clock's own current escalation_cycle,
        # so a threshold already recorded in an earlier cycle can still
        # fire again after a legitimate escalation-driven restart — see
        # ResolutionSLA.escalation_cycle's own docstring.
        candidates: list[tuple[str, UUID, str, int]] = []
        fr_clock_by_id: dict[UUID, FirstResponseSLA] = {}
        res_clock_by_id: dict[UUID, ResolutionSLA] = {}
        # Clocks whose ticket crossed ESCALATED this tick and don't yet
        # have an active escalation — recorded here during classification
        # but not acted on until after the notify loop below (see that
        # loop's own comment, and the auto-escalation block right after
        # it, for why this must not run any earlier).
        pending_auto_escalations: list[ResolutionSLA] = []

        first_response_clocks = await self.first_response_sla_repository.list_active_for_sweep()
        logger.info("SLA sweep: %d active First Response clock(s)", len(first_response_clocks))

        # Batch-prefetch every First Response clock's client once, up
        # front — same rationale as the Resolution prefetch below.
        fr_client_ids = {c.client_id for c in first_response_clocks if c.client_id is not None}
        fr_clients_by_id = {
            c.client_id: c for c in await self.client_repository.list_by_ids(list(fr_client_ids))
        }

        # Same batching for the underlying email itself (subject/body) —
        # needed so a breach notification can name the specific email
        # instead of a generic "an inbound email" message.
        fr_interaction_ids = [c.interaction_id for c in first_response_clocks]
        fr_interactions_by_id = (
            {
                i.interaction_id: i
                for i in await self.interaction_repository.list_by_ids(fr_interaction_ids)
            }
            if self.interaction_repository is not None
            else {}
        )

        for clock in first_response_clocks:
            target_minutes = target_by_priority_fr.get(clock.priority)
            if target_minutes is None:
                continue

            fraction = compute_elapsed_fraction(
                due_at=clock.due_at, target_minutes=target_minutes, at=now
            )
            policy = policy_by_priority.get(clock.priority)
            half_elapsed_cutoff = policy.warning_1_percentage / 100 if policy is not None else 0.5
            at_risk_cutoff = policy.warning_2_percentage / 100 if policy is not None else 0.8
            reached = thresholds_reached(
                fraction, half_elapsed=half_elapsed_cutoff, at_risk=at_risk_cutoff
            )
            if "HALF_ELAPSED" in reached:
                counts["first_response_half_elapsed"] += 1
            if "AT_RISK" in reached:
                counts["first_response_at_risk"] += 1
            if "BREACHED" in reached:
                counts["first_response_breached"] += 1

            for threshold, lateness in _late_thresholds(
                reached,
                due_at=clock.due_at,
                target_minutes=target_minutes,
                now=now,
                half_elapsed_cutoff=half_elapsed_cutoff,
                at_risk_cutoff=at_risk_cutoff,
                grace_seconds=late_grace_seconds,
            ):
                late_threshold_detections += 1
                logger.warning(
                    "SLA sweep: FIRST_RESPONSE clock %s (interaction %s) threshold %s "
                    "discovered %.0fs after its true crossing instant — scheduler "
                    "likely had a continuity gap, not a classification bug.",
                    clock.first_response_sla_id,
                    clock.interaction_id,
                    threshold,
                    lateness,
                )

            if reached:
                fr_clock_by_id[clock.first_response_sla_id] = clock
                candidates.extend(
                    (CLOCK_TYPE_FIRST_RESPONSE, clock.first_response_sla_id, threshold, 0)
                    for threshold in reached
                )

        resolution_clocks = await self.resolution_sla_repository.list_active_for_sweep()
        logger.info("SLA sweep: %d active Resolution clock(s)", len(resolution_clocks))

        # Batch-prefetch every resolution clock's ticket, client, and
        # (for already-claimed tickets) assigned agent up front, instead
        # of one get_by_id call per clock — see the class docstring for
        # why this matters under Neon's per-round-trip latency.
        ticket_ids = [c.ticket_id for c in resolution_clocks]
        tickets_by_id = {
            t.ticket_id: t for t in await self.ticket_repository.list_by_ids(ticket_ids)
        }

        res_client_ids = {c.client_id for c in resolution_clocks if c.client_id is not None}
        res_clients_by_id = {
            c.client_id: c for c in await self.client_repository.list_by_ids(list(res_client_ids))
        }

        agent_ids = {t.agent_id for t in tickets_by_id.values() if t.agent_id is not None}
        agents_by_id = {
            u.user_id: u for u in await self.user_repository.list_by_ids(list(agent_ids))
        }

        # One escalation per ticket in this batch, if active — used to
        # scope Half-Elapsed/At-Risk/Breached notifications to whoever
        # currently owns the ticket (see RESOLUTION_RULES_CURRENT_OWNER)
        # instead of the old CLAIMED/UNCLAIMED role ladder. Same batch-
        # prefetch rationale as tickets_by_id/res_clients_by_id/
        # agents_by_id above.
        escalations_by_ticket_id = (
            await self.escalation_service.ticket_escalation_repository.list_active_by_ticket_ids(
                ticket_ids
            )
        )

        for clock in resolution_clocks:
            # active_target_minutes is the clock's own stored, resolved
            # target — read directly rather than re-derived from
            # `priority` via a policy lookup. This matters once a
            # handling-stage reshift is in play: the target is then
            # original_resolution_target_minutes x stage_percentage,
            # which no longer matches any single priority's flat policy
            # row (see ResolutionSLA.active_target_minutes's own
            # docstring). warning_1/warning_2 thresholds below still
            # resolve via `clock.priority` — priority stays at the
            # escalation's own original_priority throughout (never
            # forced to CRITICAL), so that lookup remains correct.
            target_minutes = clock.active_target_minutes

            fraction = compute_elapsed_fraction(
                due_at=clock.due_at, target_minutes=target_minutes, at=now
            )
            policy = policy_by_priority.get(clock.priority)
            half_elapsed_cutoff = policy.warning_1_percentage / 100 if policy is not None else 0.5
            at_risk_cutoff = policy.warning_2_percentage / 100 if policy is not None else 0.8
            reached = thresholds_reached(
                fraction, half_elapsed=half_elapsed_cutoff, at_risk=at_risk_cutoff
            )
            if "HALF_ELAPSED" in reached:
                counts["resolution_half_elapsed"] += 1
            if "AT_RISK" in reached:
                counts["resolution_at_risk"] += 1
            if "BREACHED" in reached:
                counts["resolution_breached"] += 1
            if "ESCALATED" in reached:
                counts["resolution_escalated"] += 1

            for threshold, lateness in _late_thresholds(
                reached,
                due_at=clock.due_at,
                target_minutes=target_minutes,
                now=now,
                half_elapsed_cutoff=half_elapsed_cutoff,
                at_risk_cutoff=at_risk_cutoff,
                grace_seconds=late_grace_seconds,
            ):
                late_threshold_detections += 1
                logger.warning(
                    "SLA sweep: RESOLUTION clock %s (ticket %s) threshold %s "
                    "discovered %.0fs after its true crossing instant — scheduler "
                    "likely had a continuity gap, not a classification bug.",
                    clock.resolution_sla_id,
                    clock.ticket_id,
                    threshold,
                    lateness,
                )

            if reached:
                res_clock_by_id[clock.resolution_sla_id] = clock
                candidates.extend(
                    (
                        CLOCK_TYPE_RESOLUTION,
                        clock.resolution_sla_id,
                        threshold,
                        clock.escalation_cycle,
                    )
                    for threshold in reached
                )

            # Auto-escalation is only *recorded* here, never *executed*
            # here — see the dedicated pass after the notify loop below
            # for why, and for the rest of this reasoning (idempotency
            # via auto_escalate_if_needed's own no-op-if-already-
            # escalated guard, the cost-control rationale for the
            # `not in escalations_by_ticket_id` gate, and the fresh-
            # refetch requirement). This split is itself the fix for a
            # real, reported routing defect: executing auto-escalation
            # inline, in this same classification loop, could create the
            # new escalation BEFORE this tick's own notify loop resolves
            # recipients for that same clock's other newly-crossed
            # thresholds (HALF_ELAPSED/AT_RISK/BREACHED) — whenever a
            # clock is discovered already past 150% (a delayed sweep, or
            # a short SLA target relative to the sweep interval),
            # thresholds_reached() returns all of them together in one
            # tick, and the notify loop's own refresh step (which is not
            # threshold-scoped) would then feed the *new* escalation's
            # owner into recipient resolution for thresholds that
            # logically belonged to the pre-escalation owner. Deferring
            # execution until after the notify loop has read
            # `escalations_by_ticket_id` for every one of this tick's
            # thresholds closes that window entirely — see the matching
            # regression tests in tests/test_sla_sweep_service.py.
            #
            # Gated on ESCALATED (150%) only, deliberately NOT BREACHED
            # (100%) — a clock crossing BREACHED still notifies the
            # current owner (assigned agent) via RESOLUTION_RULES_
            # CURRENT_OWNER below, same as HALF_ELAPSED/AT_RISK, with no
            # ownership handoff yet.
            #
            # Skipped entirely for a ticket already present in
            # escalations_by_ticket_id (the batch prefetch above) —
            # auto_escalate_if_needed's own first line is exactly this
            # same "does an active escalation already exist" check via
            # a per-ticket round trip, which on a tick with dozens of
            # already-escalated tickets was the dominant cost of the
            # entire sweep (each round trip ~0.5-1s under Neon's
            # latency) and the direct cause of a NEWLY-breaching
            # ticket's own escalation lagging its actual breach point
            # by 30-200+ seconds — it had to wait behind every other
            # ticket's redundant re-check first. Only tickets with no
            # prefetched active escalation still pay that round trip,
            # and only once they actually need it.
            if "ESCALATED" in reached and clock.ticket_id not in escalations_by_ticket_id:
                pending_auto_escalations.append(clock)

        # ONE round trip checks every crossed triple across both clock
        # types at once — see try_record_many's own docstring for the
        # idempotency guarantee and the trade-off it makes.
        newly_recorded = await self.sla_breach_notification_repository.try_record_many(
            candidates
        )

        # tickets_by_id/agents_by_id/escalations_by_ticket_id were
        # snapshotted once at the top of this tick, but the
        # classification+auto-escalation loop above can run for many
        # seconds (one round trip per ticket). A claim/transfer/
        # escalation that lands on a ticket mid-tick — after its
        # snapshot but before this point — would otherwise be invisible
        # to _notify_resolution's CLAIMED/UNCLAIMED and
        # current-owner-vs-escalation decisions, misrouting Half-
        # Elapsed/At-Risk/Breached to the category's whole Team
        # Lead+staff pool instead of whoever actually holds the ticket
        # right now. Refresh only the tickets about to be notified
        # (newly_recorded is typically small) rather than the whole
        # batch, so this doesn't reintroduce the per-ticket round-trip
        # cost the original snapshot was built to avoid.
        #
        # populate_existing=True is required for this refresh to
        # actually do anything — every ticket here is already loaded in
        # this session's identity map from the batch snapshot above,
        # and AsyncSessionLocal is configured with
        # expire_on_commit=False (app/database/session.py), so without
        # it this re-query would silently hand back the SAME
        # already-loaded, stale objects rather than observing a
        # concurrent commit — this was a real, latent gap in this exact
        # mechanism (confirmed by writing a regression test against it
        # in tests/test_sla_sweep_service.py: it passed even with the
        # ticket-refetch reverted to a plain, non-populate_existing
        # query, until this option was added), not a hypothetical one.
        # See TicketRepository.get_by_id's own docstring for the same
        # explanation.
        resolution_ticket_ids_to_refresh = {
            res_clock_by_id[clock_id].ticket_id
            for clock_type, clock_id, _threshold, _cycle in newly_recorded
            if clock_type == CLOCK_TYPE_RESOLUTION
        }
        if resolution_ticket_ids_to_refresh:
            fresh_tickets = await self.ticket_repository.list_by_ids(
                list(resolution_ticket_ids_to_refresh), populate_existing=True
            )
            for fresh_ticket in fresh_tickets:
                tickets_by_id[fresh_ticket.ticket_id] = fresh_ticket

            fresh_agent_ids = {
                t.agent_id for t in fresh_tickets if t.agent_id is not None
            } - agents_by_id.keys()
            if fresh_agent_ids:
                for fresh_agent in await self.user_repository.list_by_ids(
                    list(fresh_agent_ids)
                ):
                    agents_by_id[fresh_agent.user_id] = fresh_agent

            fresh_escalations = (
                await self.escalation_service.ticket_escalation_repository
                .list_active_by_ticket_ids(
                    list(resolution_ticket_ids_to_refresh), populate_existing=True
                )
            )
            for ticket_id in resolution_ticket_ids_to_refresh:
                if ticket_id in fresh_escalations:
                    escalations_by_ticket_id[ticket_id] = fresh_escalations[ticket_id]
                else:
                    escalations_by_ticket_id.pop(ticket_id, None)

        for clock_type, clock_id, threshold, _cycle in newly_recorded:
            try:
                async with db.begin_nested():
                    if clock_type == CLOCK_TYPE_FIRST_RESPONSE:
                        sent = await self._notify_first_response(
                            fr_clock_by_id[clock_id],
                            threshold,
                            global_inbox_ids,
                            fr_clients_by_id,
                            fr_interactions_by_id,
                        )
                        notifications_sent += int(sent)
                    else:
                        sent, was_empty = await self._notify_resolution(
                            res_clock_by_id[clock_id],
                            threshold,
                            global_inbox_ids,
                            category_cache,
                            tickets_by_id,
                            res_clients_by_id,
                            agents_by_id,
                            escalations_by_ticket_id,
                        )
                        notifications_sent += int(sent)
                        recipients_empty += int(was_empty)
            except Exception:
                logger.warning(
                    "SLA sweep: failed processing %s clock %s threshold %s",
                    clock_type,
                    clock_id,
                    threshold,
                    exc_info=True,
                )
                errors += 1

        # Auto-escalation execution — deliberately run here, strictly
        # after the notify loop above, never earlier (see
        # `pending_auto_escalations`'s own comment in the classification
        # loop for the full reasoning: creating these escalations any
        # earlier could feed this same tick's own notify loop a
        # just-created escalation for a threshold that logically
        # belonged to the pre-escalation owner). By the time this runs,
        # every one of this tick's HALF_ELAPSED/AT_RISK/BREACHED
        # notifications has already read `escalations_by_ticket_id`, so
        # nothing below can affect them.
        for clock in pending_auto_escalations:
            # Re-fetched fresh here rather than reusing the tickets_by_id
            # snapshot taken at the top of this tick — the classification
            # loop and this whole sweep can run for a while, during which
            # a claim/transfer could land on this exact ticket. Using the
            # stale snapshot's agent_id would feed _resolve_starting_level
            # a possibly-already-superseded owner, picking the wrong
            # starting escalation level (e.g. starting at TEAM_LEAD for a
            # ticket a Team Lead has since claimed themselves, instead of
            # correctly skipping to MANAGER). Only paid for tickets
            # actually about to escalate — typically a small set — same
            # "narrow, targeted re-fetch" trade-off as the newly_recorded
            # refresh above.
            #
            # populate_existing=True is not optional here — this exact
            # ticket is already loaded in this session's identity map from
            # the batch snapshot above, and AsyncSessionLocal is
            # configured with expire_on_commit=False (app/database/
            # session.py), so a plain re-query would otherwise silently
            # hand back the SAME stale, already-loaded object rather than
            # observing a concurrent commit — see TicketRepository.
            # get_by_id's own docstring. Note: EscalationService.
            # _set_ticket_priority_to_critical (the first thing
            # _create_escalation does) also happens to refresh this same
            # ticket object as a side effect of its own update()+session.
            # refresh() call — but ONLY the first time a ticket ever
            # escalates; it no-ops without refreshing if the ticket is
            # already CRITICAL from a prior, since-closed escalation. This
            # explicit re-fetch is what keeps a *re*-escalation of an
            # already-CRITICAL ticket correct too, rather than depending
            # on that incidental side effect.
            fresh_ticket = await self.ticket_repository.get_by_id(
                clock.ticket_id, populate_existing=True
            )
            if fresh_ticket is not None:
                tickets_by_id[fresh_ticket.ticket_id] = fresh_ticket
            ticket = fresh_ticket if fresh_ticket is not None else tickets_by_id.get(clock.ticket_id)
            if ticket is not None:
                try:
                    async with db.begin_nested():
                        created = await self.escalation_service.auto_escalate_if_needed(
                            ticket=ticket, resolution_clock=clock
                        )
                    if created:
                        escalations_created += 1
                except Exception:
                    logger.warning(
                        "SLA sweep: failed auto-escalating ticket %s",
                        ticket.ticket_id,
                        exc_info=True,
                    )
                    errors += 1

        # Escalation acknowledgment auto-advance — extends this same
        # sweep run rather than a second scheduler (see
        # EscalationService.evaluate_overdue's own docstring). Runs
        # after the threshold-notification loop above but is otherwise
        # entirely independent of it (a ticket can have an overdue
        # escalation on a run where its Resolution SLA crosses no new
        # threshold at all).
        escalations_advanced = await self.escalation_service.evaluate_overdue(now=now)

        # Escalation-handling SLA breach detection — a distinct clock
        # from the ack-window check just above (see
        # EscalationHandlingSlaService/EscalationService.
        # advance_for_handling_sla_breach's own docstrings): this one
        # fires when an *acknowledged* escalation still isn't actually
        # resolved within its current handling stage's window. Same
        # "extend this one sweep, no second scheduler" rationale.
        #
        # As of the handling-stage redesign, the trigger source is
        # TicketEscalation.handling_stage_due_at (list_handling_stage_
        # overdue), not the old EscalationHandlingSlaService.
        # evaluate_breaches() return value — that method is still
        # called (next block) purely so the old, still-dual-written
        # table's own breached_at/status stay accurate for anyone still
        # reading it, WITHOUT also driving this advance a second time
        # for the same real-world breach (which would double-advance
        # the escalation ladder).
        escalation_handling_sla_breaches = 0
        for escalation in await self.escalation_service.ticket_escalation_repository.list_handling_stage_overdue(
            now=now
        ):
            try:
                async with db.begin_nested():
                    advanced = await self.escalation_service.advance_for_handling_sla_breach(
                        escalation.ticket_id
                    )
                escalation_handling_sla_breaches += int(advanced)
            except Exception:
                logger.warning(
                    "SLA sweep: failed advancing escalation for handling-stage breach on ticket %s",
                    escalation.ticket_id,
                    exc_info=True,
                )
                errors += 1

        # Dual-write only, per this session's "migrate behavior first,
        # verify nothing depends on it, remove in a later cleanup
        # phase" decision — keeps the old escalation_handling_slas
        # rows' own breached_at/status current for anyone still reading
        # them, without influencing escalation advancement (handled
        # entirely by the loop above now).
        try:
            await self.escalation_handling_sla_service.evaluate_breaches(now=now)
        except Exception:
            logger.warning(
                "SLA sweep: failed evaluating legacy escalation-handling-SLA breaches "
                "(dual-write only, does not affect escalation advancement)",
                exc_info=True,
            )
            errors += 1

        duration_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()
        if late_threshold_detections:
            logger.warning(
                "SLA sweep: %d threshold(s) discovered late this tick (>%.0fs past "
                "their true crossing instant) — check whether the scheduler had a "
                "continuity gap (process restart/freeze, or a competing/absent "
                "scheduler; see root CLAUDE.md's Deployment section).",
                late_threshold_detections,
                late_grace_seconds,
            )
        logger.info(
            "SLA sweep completed in %.2fs — notifications_sent=%d "
            "escalations_created=%d escalations_advanced=%d "
            "escalation_handling_sla_breaches=%d errors=%d "
            "late_threshold_detections=%d counts=%s",
            duration_seconds,
            notifications_sent,
            escalations_created,
            escalations_advanced,
            escalation_handling_sla_breaches,
            errors,
            late_threshold_detections,
            counts,
        )

        return SLASweepResponse(
            **counts,
            notifications_sent=notifications_sent,
            escalations_created=escalations_created,
            escalations_advanced=escalations_advanced,
            escalation_handling_sla_breaches=escalation_handling_sla_breaches,
            errors=errors,
            recipients_empty=recipients_empty,
            late_threshold_detections=late_threshold_detections,
        )

    # ---------------------------------------------------------
    # First Response notification
    # ---------------------------------------------------------

    async def _notify_first_response(
        self,
        clock: FirstResponseSLA,
        threshold: str,
        global_inbox_ids: set[UUID],
        clients_by_id: dict,
        interactions_by_id: dict,
    ) -> bool:
        """
        Only ever called for a triple try_record_many just confirmed
        is newly-crossed — no idempotency check here, that already
        happened in the batch. Recipient-resolution + notify itself is
        shared with SLAService.complete_first_response_clock's own
        completion-time breach check (see sla_breach_notifier.py) —
        one definition instead of two that could drift apart.
        """

        client = clients_by_id.get(clock.client_id) if clock.client_id is not None else None
        interaction = interactions_by_id.get(clock.interaction_id)

        return await notify_first_response_threshold(
            clock=clock,
            threshold=threshold,
            client=client,
            interaction=interaction,
            global_inbox_ids=global_inbox_ids,
            notification_service=self.notification_service,
            user_repository=self.user_repository,
        )

    # ---------------------------------------------------------
    # Resolution notification
    # ---------------------------------------------------------

    async def _notify_resolution(
        self,
        clock: ResolutionSLA,
        threshold: str,
        global_inbox_ids: set[UUID],
        category_cache: dict[str, tuple[list, list]],
        tickets_by_id: dict,
        clients_by_id: dict,
        agents_by_id: dict,
        escalations_by_ticket_id: dict,
    ) -> tuple[bool, bool]:
        """
        Only ever called for a triple try_record_many just confirmed
        is newly-crossed — no idempotency check here, that already
        happened in the batch. Returns (sent, recipients_were_empty):
        `sent` is whether a notification was actually sent; `recipients_
        were_empty` is True whenever this crossing's idempotency ledger
        row was already permanently recorded (by the caller's batch
        try_record_many, before this method ever ran) but recipient
        resolution came back with nobody to notify — this specific
        crossing can now never be retried, so the caller surfaces it via
        SLASweepResponse.recipients_empty and a logged warning instead
        of it vanishing silently. Deliberately False for the ESCALATED
        threshold (which intentionally sends nothing — see below), that
        is not an empty-recipient failure, it's by design.

        Auto-escalation creation is NOT triggered from here (it used to
        be) — see the classification loop in run_sweep, which now calls
        EscalationService.auto_escalate_if_needed independently of this
        newly-crossed gate, gated on the ESCALATED (150%) crossing only
        (never BREACHED — see that loop's own comment for why). Nesting
        it here meant a ticket only ever got one chance, ever, to
        auto-escalate: the single sweep tick where its threshold was
        first recorded in the notification ledger. A ticket that
        crossed ESCALATED before that auto-escalation call existed (or
        on a tick where it failed) would then never retry, since
        "newly recorded" stays false forever for that (clock,
        threshold) pair — this was a real bug, not a hypothetical one.

        HALF_ELAPSED/AT_RISK/BREACHED resolve recipients via
        RESOLUTION_RULES_CURRENT_OWNER — whoever is actually working the
        ticket right now, never a wider role ladder — so Team Lead/
        Account Manager/Global Inbox no longer hear about a ticket from
        this sweep alone; they only learn about it through the
        escalation workflow's own hierarchical notifications
        (EscalationService._notify_owners) once the ticket is actually
        escalated. ESCALATED (150% elapsed) sends no notification of
        its own at all — that's the exact same crossing that creates
        the TicketEscalation (see run_sweep's classification loop), so
        the real escalation-created notification has already informed
        the actual owner earlier in this same tick; still audit-logged
        (SLA_ESCALATED) below, just not notified/emailed a second time.
        """

        ticket = tickets_by_id.get(clock.ticket_id)
        if ticket is None:
            logger.warning(
                "SLA notification skipped — RESOLUTION clock %s (ticket %s) "
                "threshold %s: ticket missing from batch prefetch. This "
                "crossing will not be retried.",
                clock.resolution_sla_id,
                clock.ticket_id,
                threshold,
            )
            return False, True

        sent = False
        recipients_were_empty = False

        if threshold != "ESCALATED":
            client = clients_by_id.get(clock.client_id) if clock.client_id is not None else None

            escalation = escalations_by_ticket_id.get(ticket.ticket_id)
            escalation_owner_ids = (
                {UUID(u) for u in escalation.owner_ids} if escalation is not None else set()
            )
            # Mirrors the same "has acceptance actually completed"
            # signal EscalationService itself uses (handling_stage_due_at
            # non-null means a handling stage is currently running,
            # i.e. accept+assign has settled at this level) — read
            # straight off the already-loaded escalation row, no extra
            # query. False whenever there's no active escalation at
            # all, which resolve_current_owner treats as irrelevant.
            escalation_acceptance_completed = (
                escalation is not None and escalation.handling_stage_due_at is not None
            )

            # Claiming (a Team Lead taking a ticket for themselves) and
            # assigning (to a Staff member) both just set this same
            # column — see inbox_ticket_service.py's own "born
            # unclaimed" comment.
            if ticket.agent_id is not None:
                # None here means an orphaned/deactivated agent_id — the
                # resolver already handles assigned_agent=None
                # gracefully (falls through to nobody).
                assigned_agent = agents_by_id.get(ticket.agent_id)
                ctx = RecipientContext(
                    client=client,
                    assigned_agent=assigned_agent,
                    global_inbox_ids=global_inbox_ids,
                    escalation_owner_ids=escalation_owner_ids,
                    escalation_acceptance_completed=escalation_acceptance_completed,
                )
            else:
                team_leads, team_members = await self._get_category_team(
                    ticket.ticket_type, category_cache
                )
                ctx = RecipientContext(
                    client=client,
                    team_leads=team_leads,
                    team_members=team_members,
                    global_inbox_ids=global_inbox_ids,
                    escalation_owner_ids=escalation_owner_ids,
                    escalation_acceptance_completed=escalation_acceptance_completed,
                )

            recipient_ids = resolve_recipients(RESOLUTION_RULES_CURRENT_OWNER, threshold, ctx)

            if recipient_ids:
                title = f"Resolution SLA {threshold.replace('_', ' ').title()}: {ticket.title}"
                message = f"Ticket \"{ticket.title}\" has crossed its Resolution SLA {threshold.lower()} threshold."

                if self.notification_service is not None:
                    await self.notification_service.notify(
                        recipient_ids,
                        NOTIFICATION_TYPE_BY_THRESHOLD[threshold],
                        title=title,
                        message=message,
                        link=f"/tickets/{ticket.ticket_id}",
                        related_entity_type="ticket",
                        related_entity_id=ticket.ticket_id,
                    )
                    sent = True

                await send_notification_emails(
                    recipient_ids=recipient_ids,
                    subject=title,
                    body=f"{message}\n\nView it here: {build_absolute_link(f'/tickets/{ticket.ticket_id}')}",
                    user_repository=self.user_repository,
                )
            else:
                # Previously completely silent: the idempotency ledger
                # row for this (clock, threshold, cycle) was already
                # committed by try_record_many before this method ever
                # ran (see run_sweep), so this specific crossing can
                # now NEVER be retried — yet nothing was logged and
                # SLASweepResponse.errors never counted it, so it looked
                # identical to "nothing crossed" from the outside.
                recipients_were_empty = True
                if ticket.agent_id is None:
                    reason = "ticket unclaimed and no active Team Lead for its category"
                elif agents_by_id.get(ticket.agent_id) is None:
                    reason = f"agent_id={ticket.agent_id} not found (orphaned/deactivated)"
                elif escalation_owner_ids and not escalation_acceptance_completed:
                    reason = "active escalation has empty owner_ids"
                else:
                    reason = "resolve_current_owner returned no recipients"
                logger.warning(
                    "SLA notification skipped — RESOLUTION clock %s (ticket %s) "
                    "threshold %s: %s. This crossing will not be retried.",
                    clock.resolution_sla_id,
                    ticket.ticket_id,
                    threshold,
                    reason,
                )

        if threshold in ("BREACHED", "ESCALATED"):
            await AuditLogService.log_event(
                self.ticket_repository.db,
                entity_type=AuditEntityType.TICKET,
                entity_id=ticket.ticket_id,
                event_type=(
                    AuditEventType.SLA_ESCALATED
                    if threshold == "ESCALATED"
                    else AuditEventType.SLA_BREACH_DETECTED
                ),
                actor_id=None,
                actor_name="SLA Sweep",
                actor_role=ActorRole.SYSTEM,
                new_values={"threshold": threshold, "ticket_id": ticket.ticket_id},
            )

        return sent, recipients_were_empty

    async def _get_category_team(
        self,
        category_name: str,
        category_cache: dict[str, tuple[list, list]],
    ) -> tuple[list, list]:
        """
        Team Lead(s) for a ticket category, plus every active Staff
        member reporting to any of them — memoized per sweep run in
        `category_cache` (populated by the caller, kept across every
        unclaimed clock sharing that category in this run).
        """

        if category_name in category_cache:
            return category_cache[category_name]

        team_leads = await self.user_repository.list_active_by_role_and_category(
            TEAM_LEAD_ROLE_NAME, category_name
        )
        team_members = await self.user_repository.list_active_staff_by_teamlead_ids(
            [u.user_id for u in team_leads]
        )

        category_cache[category_name] = (team_leads, team_members)
        return team_leads, team_members

    async def _global_inbox_user_ids(self) -> set:
        # Shared with SLAService.complete_first_response_clock's own
        # completion-time breach check — see sla_breach_notifier.py.
        return await resolve_global_inbox_user_ids(self.user_repository)
