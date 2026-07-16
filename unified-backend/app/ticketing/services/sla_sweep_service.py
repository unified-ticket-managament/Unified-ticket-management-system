import logging
from datetime import datetime, timezone
from uuid import UUID

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
    RESOLUTION_RULES_CLAIMED,
    RESOLUTION_RULES_UNCLAIMED,
    TEAM_LEAD_ROLE_NAME,
    RecipientContext,
    resolve_recipients,
    thresholds_reached,
)
from app.ticketing.services.sla_service import compute_elapsed_fraction

logger = logging.getLogger(__name__)

CLOCK_TYPE_RESOLUTION = "RESOLUTION"


class SLASweepService:
    """
    Runs one breach-detection pass over every active SLA clock — the
    Render Cron Job's target, called via POST /internal/sla/sweep.

    Shape: (1) two cheap, status-filtered queries fetch every active
    clock; (2) classify each clock's crossed thresholds in Python
    (compute_elapsed_fraction + thresholds_reached, both pure); (3) one
    batched INSERT ... ON CONFLICT DO NOTHING ... RETURNING checks
    every crossed (clock_type, clock_id, threshold) triple's
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
        target_by_priority_res = {p.priority: p.resolution_target_minutes for p in policies}
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

        global_inbox_ids = await self._global_inbox_user_ids()

        # ticket_type -> (team_leads, staff-under-them), populated lazily
        # the first time an unclaimed Resolution clock in that category
        # is seen, reused for every later clock sharing it in this run —
        # caps the extra query fan-out the Case-1 (Team Lead + team
        # members) escalation path would otherwise add per-clock.
        category_cache: dict[str, tuple[list, list]] = {}

        # Every (clock_type, clock_id, threshold) triple that crossed
        # this tick, across both clock types — checked against the
        # idempotency ledger in one batch below, not one round trip
        # each.
        candidates: list[tuple[str, UUID, str]] = []
        fr_clock_by_id: dict[UUID, FirstResponseSLA] = {}
        res_clock_by_id: dict[UUID, ResolutionSLA] = {}

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
            reached = (
                thresholds_reached(
                    fraction,
                    half_elapsed=policy.warning_1_percentage / 100,
                    at_risk=policy.warning_2_percentage / 100,
                )
                if policy is not None
                else thresholds_reached(fraction)
            )
            if "HALF_ELAPSED" in reached:
                counts["first_response_half_elapsed"] += 1
            if "AT_RISK" in reached:
                counts["first_response_at_risk"] += 1
            if "BREACHED" in reached:
                counts["first_response_breached"] += 1

            if reached:
                fr_clock_by_id[clock.first_response_sla_id] = clock
                candidates.extend(
                    (CLOCK_TYPE_FIRST_RESPONSE, clock.first_response_sla_id, threshold)
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

        for clock in resolution_clocks:
            target_minutes = target_by_priority_res.get(clock.priority)
            if target_minutes is None:
                continue

            fraction = compute_elapsed_fraction(
                due_at=clock.due_at, target_minutes=target_minutes, at=now
            )
            policy = policy_by_priority.get(clock.priority)
            reached = (
                thresholds_reached(
                    fraction,
                    half_elapsed=policy.warning_1_percentage / 100,
                    at_risk=policy.warning_2_percentage / 100,
                )
                if policy is not None
                else thresholds_reached(fraction)
            )
            if "HALF_ELAPSED" in reached:
                counts["resolution_half_elapsed"] += 1
            if "AT_RISK" in reached:
                counts["resolution_at_risk"] += 1
            if "BREACHED" in reached:
                counts["resolution_breached"] += 1
            if "ESCALATED" in reached:
                counts["resolution_escalated"] += 1

            if reached:
                res_clock_by_id[clock.resolution_sla_id] = clock
                candidates.extend(
                    (CLOCK_TYPE_RESOLUTION, clock.resolution_sla_id, threshold)
                    for threshold in reached
                )

            # Auto-escalation creation is deliberately evaluated here,
            # independent of the notify-once idempotency ledger below —
            # NOT nested inside the newly-recorded notification loop
            # further down, where it used to live. A clock's BREACHED/
            # ESCALATED crossing only ever notifies once (the ledger's
            # whole point), but a ticket that crossed that threshold
            # before ever getting an escalation created — a past
            # transient failure, or simply because this auto-escalation
            # feature didn't exist yet when the notification first
            # fired — would otherwise never be retried on any later
            # sweep tick, since "newly recorded" would stay false
            # forever for that (clock, threshold) pair. This runs on
            # every tick a clock remains BREACHED/ESCALATED instead,
            # relying entirely on auto_escalate_if_needed's own
            # idempotency (a no-op once an active escalation already
            # exists) to stay safe to call repeatedly. Isolated in its
            # own SAVEPOINT, same as every other per-clock action in
            # this sweep, so one ticket's failure can't affect another.
            if "BREACHED" in reached or "ESCALATED" in reached:
                ticket = tickets_by_id.get(clock.ticket_id)
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

        # ONE round trip checks every crossed triple across both clock
        # types at once — see try_record_many's own docstring for the
        # idempotency guarantee and the trade-off it makes.
        newly_recorded = await self.sla_breach_notification_repository.try_record_many(
            candidates
        )

        for clock_type, clock_id, threshold in newly_recorded:
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
                    else:
                        sent = await self._notify_resolution(
                            res_clock_by_id[clock_id],
                            threshold,
                            global_inbox_ids,
                            category_cache,
                            tickets_by_id,
                            res_clients_by_id,
                            agents_by_id,
                        )
                notifications_sent += int(sent)
            except Exception:
                logger.warning(
                    "SLA sweep: failed processing %s clock %s threshold %s",
                    clock_type,
                    clock_id,
                    threshold,
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
        # resolved within its 25%-of-original-target window. Same
        # "extend this one sweep, no second scheduler" rationale.
        escalation_handling_sla_breaches = 0
        for clock in await self.escalation_handling_sla_service.evaluate_breaches(now=now):
            advanced = await self.escalation_service.advance_for_handling_sla_breach(
                clock.ticket_id
            )
            escalation_handling_sla_breaches += int(advanced)

        duration_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()
        logger.info(
            "SLA sweep completed in %.2fs — notifications_sent=%d "
            "escalations_created=%d escalations_advanced=%d "
            "escalation_handling_sla_breaches=%d errors=%d counts=%s",
            duration_seconds,
            notifications_sent,
            escalations_created,
            escalations_advanced,
            escalation_handling_sla_breaches,
            errors,
            counts,
        )

        return SLASweepResponse(
            **counts,
            notifications_sent=notifications_sent,
            escalations_created=escalations_created,
            escalations_advanced=escalations_advanced,
            escalation_handling_sla_breaches=escalation_handling_sla_breaches,
            errors=errors,
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
    ) -> bool:
        """
        Only ever called for a triple try_record_many just confirmed
        is newly-crossed — no idempotency check here, that already
        happened in the batch. Returns whether a notification was sent.

        Auto-escalation creation is NOT triggered from here (it used to
        be) — see the classification loop in run_sweep, which now calls
        EscalationService.auto_escalate_if_needed independently of this
        newly-crossed gate. Nesting it here meant a ticket only ever
        got one chance, ever, to auto-escalate: the single sweep tick
        where its threshold was first recorded in the notification
        ledger. A ticket that crossed BREACHED/ESCALATED before that
        auto-escalation call existed (or on a tick where it failed)
        would then never retry, since "newly recorded" stays false
        forever for that (clock, threshold) pair — this was a real bug,
        not a hypothetical one.
        """

        ticket = tickets_by_id.get(clock.ticket_id)
        if ticket is None:
            return False

        client = clients_by_id.get(clock.client_id) if clock.client_id is not None else None

        # Claiming (a Team Lead taking a ticket for themselves) and
        # assigning (to a Staff member) both just set this same column —
        # see inbox_ticket_service.py's own "born unclaimed" comment.
        if ticket.agent_id is not None:
            # None here means an orphaned/deactivated agent_id — the
            # resolvers already handle assigned_agent=None gracefully
            # (ASSIGNED_AGENT/TEAM_LEAD both just resolve to nobody).
            assigned_agent = agents_by_id.get(ticket.agent_id)
            ctx = RecipientContext(
                client=client,
                assigned_agent=assigned_agent,
                global_inbox_ids=global_inbox_ids,
            )
            rules = RESOLUTION_RULES_CLAIMED
        else:
            team_leads, team_members = await self._get_category_team(
                ticket.ticket_type, category_cache
            )
            ctx = RecipientContext(
                client=client,
                team_leads=team_leads,
                team_members=team_members,
                global_inbox_ids=global_inbox_ids,
            )
            rules = RESOLUTION_RULES_UNCLAIMED

        recipient_ids = resolve_recipients(rules, threshold, ctx)

        if not recipient_ids:
            return False

        title = f"Resolution SLA {threshold.replace('_', ' ').title()}: {ticket.title}"
        message = f"Ticket \"{ticket.title}\" has crossed its Resolution SLA {threshold.lower()} threshold."

        sent = False
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

        return sent

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
