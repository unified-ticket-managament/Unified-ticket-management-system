from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.core.impersonation_context import get_impersonator
from app.rbac.models.audit_log import AuditLog
from shared_models.models import Role, User

from .base import BaseRepository


class AuditLogRepository(BaseRepository):
    """
    Repository for Audit Log operations.
    """

    async def create(
        self,
        audit_log: AuditLog,
    ) -> AuditLog:
        # See app/ticketing/repositories/audit_log_repository.py's
        # identical addition for the full rationale — both audit
        # systems need this, since either can write a row during an
        # impersonated session (e.g. this table's own
        # user_impersonation.started/ended rows aside, a Super Admin
        # impersonating a role that holds user:update/permission:update
        # etc. can still trigger a user.*/role.*/permission.* row here).
        impersonator = get_impersonator()
        if impersonator is not None:
            audit_log.impersonator_id = impersonator[0]
            audit_log.impersonator_name = impersonator[1]

        self.db.add(audit_log)

        await self.db.flush()
        await self.db.refresh(audit_log)

        return audit_log

    async def get_by_id(
        self,
        audit_log_id: UUID,
    ) -> AuditLog | None:

        result = await self.db.execute(
            select(AuditLog).where(
                AuditLog.audit_log_id == audit_log_id
            )
        )

        return result.scalar_one_or_none()

    async def get_all(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AuditLog], int]:

        total = (
            await self.db.execute(
                select(func.count()).select_from(AuditLog)
            )
        ).scalar_one()

        result = await self.db.execute(
            select(AuditLog)
            .order_by(AuditLog.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        logs = result.scalars().all()

        return list(logs), total

    async def get_user_logs(
        self,
        user_id: UUID,
    ) -> list[AuditLog]:

        result = await self.db.execute(
            select(AuditLog)
            .where(AuditLog.user_id == user_id)
            .order_by(AuditLog.timestamp.desc())
        )

        return list(result.scalars().all())

    async def list_for_export(
        self,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[AuditLog]:
        """
        The complete, unpaginated matching set for a CSV export —
        reuses get_all's own unscoped query shape (this table is
        org-wide with no per-user/client narrowing, see this module's
        own top-of-file note), just without a page/page_size limit,
        since an export is defined as "every row matching the current
        filters," not one page of them. Eager-loads `user`/`user.role`
        (a plain many-to-one join, no fanout risk — same joinedload
        convention already used elsewhere in this codebase) so the
        export CSV can include the same User/Role columns the frontend
        table already shows, without a second round trip.

        `search`/`date_from`/`date_to` mirror the exact same fields
        the frontend's own client-side filter already searches
        (action, entity_type, and the joined user's name/email/role
        name) — see AuditLogsPage's filteredRows — so an export taken
        while a filter is active downloads only the filtered rows, not
        the whole table.
        """

        query = (
            select(AuditLog)
            .options(joinedload(AuditLog.user).joinedload(User.role))
            .order_by(AuditLog.timestamp.desc())
        )

        if date_from is not None:
            query = query.where(AuditLog.timestamp >= date_from)

        if date_to is not None:
            query = query.where(AuditLog.timestamp <= date_to)

        if search:
            like = f"%{search}%"
            query = query.outerjoin(User, User.user_id == AuditLog.user_id).outerjoin(
                Role, Role.role_id == User.role_id
            )
            query = query.where(
                or_(
                    AuditLog.action.ilike(like),
                    AuditLog.entity_type.ilike(like),
                    User.name.ilike(like),
                    User.email.ilike(like),
                    Role.name.ilike(like),
                )
            )

        result = await self.db.execute(query)

        # unique() is required whenever a collection-safe joinedload is
        # combined with an additional explicit join in the same query
        # (the search branch above) — SQLAlchemy 2.x raises otherwise,
        # since the extra join can multiply row identity even though
        # AuditLog.user itself is a plain many-to-one.
        return list(result.unique().scalars().all())