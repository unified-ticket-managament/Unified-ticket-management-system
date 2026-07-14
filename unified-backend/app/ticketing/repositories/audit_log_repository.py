# audit_log_repository.py

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.enums import ActorRole, AuditEntityType, AuditEventType
from app.ticketing.models.audit_log import AuditLog
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import Ticket


class AuditLogVisiblePage:
    """Plain result holder — see list_visible_page's own docstring."""

    __slots__ = ("items", "total")

    def __init__(self, items, total: int):
        self.items = items
        self.total = total

#audit_log_repository.py
class AuditLogRepository:
    """
    Write-mostly access to the ticket_audit_logs table (named that,
    not audit_logs, to avoid colliding with an unrelated table of
    that name already owned by another service in this shared DB).

    Audit rows are immutable once written — there is intentionally
    no update() or delete() here, only create() and reads.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _derive_ticket_id(
        entity_type: AuditEntityType,
        entity_id: UUID,
        new_values: dict[str, Any] | None,
    ) -> UUID | None:
        """
        Single point of derivation for the `ticket_id` column (see
        that column's own docstring in models/audit_log.py) — every
        caller of create() benefits automatically, and the same logic
        is mirrored in migration 4f7a9c2e6b8d's one-time backfill.
        """

        if entity_type == AuditEntityType.TICKET:
            return entity_id

        raw = (new_values or {}).get("ticket_id")
        if raw is None:
            return None

        try:
            return UUID(str(raw))
        except (ValueError, AttributeError, TypeError):
            return None

    async def create(
        self,
        *,
        entity_type: AuditEntityType,
        entity_id: UUID,
        event_type: AuditEventType,
        actor_id: UUID | None,
        actor_name: str,
        actor_role: ActorRole,
        old_values: dict[str, Any] | None,
        new_values: dict[str, Any] | None,
    ) -> AuditLog:
        audit_log = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values=old_values,
            new_values=new_values,
            ticket_id=self._derive_ticket_id(entity_type, entity_id, new_values),
        )

        self.db.add(audit_log)

        # Flush only — never commit. The request's get_db()
        # dependency commits once at the end of the request, so
        # this row lands in the exact same transaction as whatever
        # ticket/interaction/attachment change triggered it: both
        # succeed together or both roll back together.
        await self.db.flush()
        await self.db.refresh(audit_log)

        return audit_log

    async def list_by_ticket(
        self,
        ticket_id: UUID,
    ) -> list[AuditLog]:
        """
        Every audit row related to a ticket: the direct
        entity_type=TICKET rows, plus the INTERACTION / ATTACHMENT
        rows logged against the interaction/attachment id but that
        belong to this ticket — both cases are captured in the
        `ticket_id` column at write time (see AuditLogRepository
        ._derive_ticket_id / the column's own docstring), so this is
        a plain indexed equality lookup rather than a JSONB
        extraction. Newest first.
        """

        result = await self.db.execute(
            select(AuditLog)
            .where(AuditLog.ticket_id == ticket_id)
            .order_by(AuditLog.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_ticket_ids(
        self,
        ticket_ids: list[UUID],
        *,
        limit: int | None = None,
        offset: int = 0,
        entity_type: AuditEntityType | None = None,
        event_type: AuditEventType | None = None,
        actor_name: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[AuditLog], int]:
        """
        Same shape as list_by_ticket, batched over many tickets at
        once — lets a page that needs every visible ticket's audit
        trail (the Audit Log page) run one query instead of one
        request per ticket.

        `limit=None` (the default) preserves this method's original,
        unbounded behavior, with `total` just `len(items)` — no
        separate COUNT needed. Passing `limit` switches to a real
        bounded, filtered query plus a COUNT(*) over the same filters,
        the same convention as InteractionRepository.list_by_ticket_ids.
        This matters more here than almost anywhere else in the app:
        the Audit Log page polls this endpoint every 15 seconds, so an
        unbounded response here means every connected agent's browser
        re-fetches the *entire* audit history, forever, every 15s.
        """

        if not ticket_ids:
            return [], 0

        conditions = [AuditLog.ticket_id.in_(ticket_ids)]

        if entity_type is not None:
            conditions.append(AuditLog.entity_type == entity_type)
        if event_type is not None:
            conditions.append(AuditLog.event_type == event_type)
        if actor_name is not None:
            conditions.append(AuditLog.actor_name == actor_name)
        if date_from is not None:
            conditions.append(AuditLog.created_at >= date_from)
        if date_to is not None:
            conditions.append(AuditLog.created_at <= date_to)

        if limit is None:
            result = await self.db.execute(
                select(AuditLog).where(*conditions).order_by(AuditLog.created_at.desc())
            )
            items = list(result.scalars().all())
            return items, len(items)

        count_result = await self.db.execute(
            select(func.count()).select_from(AuditLog).where(*conditions)
        )
        total = count_result.scalar_one()

        result = await self.db.execute(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        return list(result.scalars().all()), total

    async def list_visible_page(
        self,
        *,
        account_manager_id: UUID | None,
        ticket_types: list[str] | None,
        limit: int,
        offset: int = 0,
        entity_type: AuditEntityType | None = None,
        event_type: AuditEventType | None = None,
        actor_name: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
        assigned_to: UUID | None = None,
    ) -> AuditLogVisiblePage:
        """
        The Audit Log page's query, collapsed the same way
        InteractionRepository.list_visible_page collapsed the
        Interactions page's — see that method's docstring for the
        full round-trip-reduction rationale, which applies identically
        here. The one thing that made this endpoint worse than
        Interactions before this method existed: TicketService
        .list_all_audit_logs used to call `ticket_repository.list_all`
        with **no limit** — an unbounded fetch of every visible ticket
        — on every single call, INCLUDING the Audit Log page's every-
        15-second poll. That's now gone entirely: visibility is
        enforced by JOINing to `tickets` directly (same
        account_manager_id-owned-clients subquery, same ticket_types
        category scoping) instead of ever materializing a visible-
        ticket-id list in Python, and `ticket_title` comes back on the
        same row via the join instead of a separate in-process dict
        built from that now-removed unbounded fetch. `search` (ticket
        title) is now a real `ILIKE` against the joined `tickets.title`
        column in SQL, instead of a Python substring filter applied to
        that same removed in-process title dict.

        `total` is `COUNT(*) OVER()` — see list_visible_page on
        InteractionRepository for why this is correct here (no keyset/
        cursor mode exists for this endpoint, so there's no equivalent
        caveat) and why a genuinely empty page falls back to one plain
        `COUNT(*)` query rather than trying to report a total from a
        window function that has no row to attach it to.
        """

        conditions = [AuditLog.ticket_id.isnot(None)]

        if account_manager_id is not None:
            owned_client_ids = select(Client.client_id).where(
                Client.account_manager_id == account_manager_id
            )
            conditions.append(Ticket.client_company_id.in_(owned_client_ids))

        if ticket_types is not None:
            conditions.append(Ticket.ticket_type.in_(ticket_types))

        if assigned_to is not None:
            conditions.append(Ticket.agent_id == assigned_to)

        if entity_type is not None:
            conditions.append(AuditLog.entity_type == entity_type)
        if event_type is not None:
            conditions.append(AuditLog.event_type == event_type)
        if actor_name is not None:
            conditions.append(AuditLog.actor_name == actor_name)
        if date_from is not None:
            conditions.append(AuditLog.created_at >= date_from)
        if date_to is not None:
            conditions.append(AuditLog.created_at <= date_to)
        if search:
            conditions.append(Ticket.title.ilike(f"%{search}%"))

        def _base_select(*extra_columns):
            return (
                select(AuditLog, Ticket.title.label("ticket_title"), *extra_columns)
                .join(Ticket, Ticket.ticket_id == AuditLog.ticket_id)
                .where(*conditions)
            )

        page_query = (
            _base_select(func.count().over().label("full_count"))
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await self.db.execute(page_query)
        rows = result.all()

        if rows:
            return AuditLogVisiblePage(items=rows, total=rows[0].full_count)

        # Empty page — same fallback shape as
        # InteractionRepository.list_visible_page: only reached when
        # the window function has no row to report a total on.
        count_result = await self.db.execute(
            select(func.count())
            .select_from(AuditLog)
            .join(Ticket, Ticket.ticket_id == AuditLog.ticket_id)
            .where(*conditions)
        )
        total = count_result.scalar_one()

        return AuditLogVisiblePage(items=[], total=total)
