# audit_log_service.py

"""
Compliance/security record of ticket-related changes.

Why this is a separate thing from Interaction:
- Interaction rows are the visible ticket timeline agents read day
  to day (emails, replies, notes, status/priority changes, agent
  transfers, attachment uploads...). They're a business record, and
  they CAN be hidden from that timeline via `is_visible`.
- AuditLog rows are an immutable, append-only compliance/security
  trail of exactly who changed what and what it was before/after.
  They are never surfaced to agents as "activity", and are never
  updated or deleted once written.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ActorRole, AuditEntityType, AuditEventType
from app.models.audit_log import AuditLog
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.user_repository import UserRepository
from app.utils.helpers import serialize_audit_values


class AuditLogService:
    """
    Thin, reusable helper for writing audit_logs rows from any other
    service. Deliberately stateless (a @staticmethod, not tied to a
    particular repository instance) so callers don't need to wire
    up an AuditLogRepository just to log one event — they pass the
    same `db` session they're already using for the ticket change.

    Never commits. The parent request's get_db() dependency commits
    once at the end, so the audit row always lands in the same
    transaction as the change that produced it.
    """

    @staticmethod
    async def log_event(
        db: AsyncSession,
        entity_type: AuditEntityType,
        entity_id: UUID,
        event_type: AuditEventType,
        actor_id: UUID | None,
        actor_name: str,
        actor_role: ActorRole,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
    ) -> AuditLog:
        repository = AuditLogRepository(db)

        return await repository.create(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            # UUIDs / enums / datetimes in old_values / new_values
            # aren't JSON-serializable on their own — normalize them
            # here so every caller gets this for free.
            old_values=serialize_audit_values(old_values),
            new_values=serialize_audit_values(new_values),
        )

    @staticmethod
    async def resolve_agent_actor(
        user_repository: UserRepository,
        agent_name: str | None,
    ) -> tuple[UUID | None, str, ActorRole]:
        """
        Resolves the "acting as" agent_name string — the only
        identity concept in this app, since there is no real
        authentication — into the (actor_id, actor_name, actor_role)
        tuple every audit row needs.

        Falls back to (None, "System", SYSTEM) when no agent_name is
        given, or it doesn't match a real active Staff member (e.g.
        a stale/typo'd name) — this is what makes SYSTEM mean
        "nobody identifiable performed this", matching automatic
        actions like auto-assignment rather than a human mistake.
        """

        if agent_name:
            agent = await user_repository.get_active_staff_by_name(agent_name)
            if agent is not None:
                return agent.user_id, agent.name, ActorRole.AGENT

        return None, "System", ActorRole.SYSTEM
