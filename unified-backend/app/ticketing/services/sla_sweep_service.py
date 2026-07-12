import logging
from datetime import datetime, timezone

from app.notifications.service import NotificationService, NotificationType
from app.ticketing.enums import ActorRole, AuditEntityType, AuditEventType
from app.ticketing.models.first_response_sla import FirstResponseSLA
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.first_response_sla_repository import (
    FirstResponseSLARepository,
)
from app.ticketing.repositories.resolution_sla_repository import (
    ResolutionSLARepository,
)
from app.ticketing.repositories.sla_breach_notification_repository import (
    SLABreachNotificationRepository,
)
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.sla import SLASweepResponse
from app.ticketing.services.access_control import GLOBAL_INBOX_ROLE_NAMES
from app.ticketing.services.audit_log_service import AuditLogService
from app.ticketing.services.sla_service import compute_elapsed_fraction

logger = logging.getLogger(__name__)

CLOCK_TYPE_FIRST_RESPONSE = "FIRST_RESPONSE"
CLOCK_TYPE_RESOLUTION = "RESOLUTION"

# Ordered so a single elapsed_fraction reading yields every threshold
# it has crossed, oldest first — a clock discovered at 160% fires
# AT_RISK, BREACHED, and ESCALATED all in the same tick (each is its
# own idempotent row, so this is safe even if a prior tick already
# recorded the earlier ones).
THRESHOLDS = (
    ("AT_RISK", 0.8),
    ("BREACHED", 1.0),
    ("ESCALATED", 1.5),
)

TEAM_LEAD_ROLE_NAME = "Team Lead"


def thresholds_reached(elapsed_fraction: float) -> list[str]:
    """Pure classification — every named threshold `elapsed_fraction` has met or passed."""

    return [name for name, cutoff in THRESHOLDS if elapsed_fraction >= cutoff]


class SLASweepService:
    """
    Runs one breach-detection pass over every active SLA clock — the
    Render Cron Job's target, called via POST /internal/sla/sweep.
    Two cheap, status-filtered queries (no scheduler infra existed in
    this codebase before this feature; see the plan doc's §3), then
    per-row threshold classification in Python and an idempotent
    notify via SLABreachNotificationRepository's unique-index guard.

    v1 is in-app notifications only — OutboundDispatcher (real email
    transport) is a logging no-op in this codebase today; there is no
    email escalation channel to build against yet.
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
    ):
        self.sla_policy_repository = sla_policy_repository
        self.first_response_sla_repository = first_response_sla_repository
        self.resolution_sla_repository = resolution_sla_repository
        self.sla_breach_notification_repository = sla_breach_notification_repository
        self.ticket_repository = ticket_repository
        self.client_repository = client_repository
        self.user_repository = user_repository
        self.notification_service = notification_service

    async def run_sweep(self) -> SLASweepResponse:
        now = datetime.now(timezone.utc)

        policies = await self.sla_policy_repository.list_all()
        target_by_priority_fr = {p.priority: p.first_response_target_minutes for p in policies}
        target_by_priority_res = {p.priority: p.resolution_target_minutes for p in policies}

        counts = {
            "first_response_at_risk": 0,
            "first_response_breached": 0,
            "resolution_at_risk": 0,
            "resolution_breached": 0,
            "resolution_escalated": 0,
        }
        notifications_sent = 0

        for clock in await self.first_response_sla_repository.list_active_for_sweep():
            target_minutes = target_by_priority_fr.get(clock.priority)
            if target_minutes is None:
                continue

            fraction = compute_elapsed_fraction(
                due_at=clock.due_at, target_minutes=target_minutes, at=now
            )
            reached = thresholds_reached(fraction)
            if "AT_RISK" in reached:
                counts["first_response_at_risk"] += 1
            if "BREACHED" in reached:
                counts["first_response_breached"] += 1

            for threshold in reached:
                sent = await self._notify_first_response(clock, threshold)
                notifications_sent += int(sent)

        for clock in await self.resolution_sla_repository.list_active_for_sweep():
            target_minutes = target_by_priority_res.get(clock.priority)
            if target_minutes is None:
                continue

            fraction = compute_elapsed_fraction(
                due_at=clock.due_at, target_minutes=target_minutes, at=now
            )
            reached = thresholds_reached(fraction)
            if "AT_RISK" in reached:
                counts["resolution_at_risk"] += 1
            if "BREACHED" in reached:
                counts["resolution_breached"] += 1
            if "ESCALATED" in reached:
                counts["resolution_escalated"] += 1

            for threshold in reached:
                sent = await self._notify_resolution(clock, threshold)
                notifications_sent += int(sent)

        return SLASweepResponse(**counts, notifications_sent=notifications_sent)

    # ---------------------------------------------------------
    # First Response notification
    # ---------------------------------------------------------

    async def _notify_first_response(
        self, clock: FirstResponseSLA, threshold: str
    ) -> bool:
        inserted = await self.sla_breach_notification_repository.try_record(
            clock_type=CLOCK_TYPE_FIRST_RESPONSE,
            clock_id=clock.first_response_sla_id,
            threshold=threshold,
        )
        if not inserted:
            return False

        recipient_ids = await self._resolve_first_response_recipients(clock, threshold)
        if not recipient_ids or self.notification_service is None:
            return False

        notification_type = {
            "AT_RISK": NotificationType.SLA_AT_RISK,
            "BREACHED": NotificationType.SLA_BREACHED,
            "ESCALATED": NotificationType.SLA_ESCALATED,
        }[threshold]

        await self.notification_service.notify(
            recipient_ids,
            notification_type,
            title=f"First Response SLA {threshold.replace('_', ' ').title()}",
            message="An inbound email is still awaiting triage.",
            link="/inbox",
            related_entity_type="interaction",
            related_entity_id=clock.interaction_id,
        )
        return True

    async def _resolve_first_response_recipients(
        self, clock: FirstResponseSLA, threshold: str
    ) -> set:
        recipients: set = set()

        client = (
            await self.client_repository.get_by_id(clock.client_id)
            if clock.client_id is not None
            else None
        )

        if threshold == "AT_RISK":
            if client is not None:
                recipients.add(client.account_manager_id)
        elif threshold == "BREACHED":
            if client is not None:
                recipients.add(client.account_manager_id)
            recipients.update(await self._global_inbox_user_ids())
        elif threshold == "ESCALATED":
            recipients.update(await self._global_inbox_user_ids())

        return recipients

    # ---------------------------------------------------------
    # Resolution notification
    # ---------------------------------------------------------

    async def _notify_resolution(self, clock: ResolutionSLA, threshold: str) -> bool:
        inserted = await self.sla_breach_notification_repository.try_record(
            clock_type=CLOCK_TYPE_RESOLUTION,
            clock_id=clock.resolution_sla_id,
            threshold=threshold,
        )
        if not inserted:
            return False

        ticket = await self.ticket_repository.get_by_id(clock.ticket_id)
        if ticket is None:
            return False

        recipient_ids = await self._resolve_resolution_recipients(
            clock, ticket, threshold
        )
        if not recipient_ids or self.notification_service is None:
            return False

        notification_type = {
            "AT_RISK": NotificationType.SLA_AT_RISK,
            "BREACHED": NotificationType.SLA_BREACHED,
            "ESCALATED": NotificationType.SLA_ESCALATED,
        }[threshold]

        await self.notification_service.notify(
            recipient_ids,
            notification_type,
            title=f"Resolution SLA {threshold.replace('_', ' ').title()}: {ticket.title}",
            message=f"Ticket \"{ticket.title}\" has crossed its Resolution SLA {threshold.lower()} threshold.",
            link=f"/tickets/{ticket.ticket_id}",
            related_entity_type="ticket",
            related_entity_id=ticket.ticket_id,
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

        return True

    async def _resolve_resolution_recipients(
        self, clock: ResolutionSLA, ticket, threshold: str
    ) -> set:
        recipients: set = set()

        client = (
            await self.client_repository.get_by_id(clock.client_id)
            if clock.client_id is not None
            else None
        )
        team_leads = await self.user_repository.list_active_by_role_and_category(
            TEAM_LEAD_ROLE_NAME, ticket.ticket_type
        )

        if threshold == "AT_RISK":
            if ticket.agent_id is not None:
                recipients.add(ticket.agent_id)
        elif threshold == "BREACHED":
            if ticket.agent_id is not None:
                recipients.add(ticket.agent_id)
            recipients.update(u.user_id for u in team_leads)
            if client is not None:
                recipients.add(client.account_manager_id)
        elif threshold == "ESCALATED":
            recipients.update(u.user_id for u in team_leads)
            if client is not None:
                recipients.add(client.account_manager_id)
            recipients.update(await self._global_inbox_user_ids())

        return recipients

    async def _global_inbox_user_ids(self) -> set:
        recipients: set = set()
        for role_name in GLOBAL_INBOX_ROLE_NAMES:
            users = await self.user_repository.list_active_by_role_name(role_name)
            recipients.update(u.user_id for u in users)
        return recipients
