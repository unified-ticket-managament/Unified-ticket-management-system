# impersonation_session_repository.py

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from shared_models.models import User

from app.rbac.models.impersonation_session import ImpersonationSession

from .base import BaseRepository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ImpersonationSessionRepository(BaseRepository):
    """
    CRUD + the one validity query app/dependencies/auth.py runs on
    every request carrying an `impersonation_session_id` claim.
    """

    async def create(self, session: ImpersonationSession) -> ImpersonationSession:
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def get_by_id(self, session_id: UUID) -> ImpersonationSession | None:
        result = await self.db.execute(
            select(ImpersonationSession).where(ImpersonationSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_valid(
        self,
        session_id: UUID,
        *,
        actor_user_id: UUID | None,
        target_user_id: UUID | None,
    ) -> ImpersonationSession | None:
        """
        Returns the session row only if EVERY one of the following
        holds — otherwise None, which the caller treats as "reject
        this request" (see app/dependencies/auth.py):

        - the row exists and is `status == 'ACTIVE'`
        - `now < expires_at`
        - the token's own `impersonator_id` claim matches
          `session.actor_user_id` (tamper/consistency check)
        - the token's own `user_id` claim matches
          `session.target_user_id` (tamper/consistency check)
        - the actor's live `users.is_active` is true
        - the target's live `users.is_active` is true

        One query, joined to `users` twice (aliased) for the two
        is_active checks, so deactivating either party — or ending the
        session via ImpersonationService.end — takes effect on the
        very next request, not after any cache TTL.
        """

        actor_users = User.__table__.alias("impersonation_actor_users")
        target_users = User.__table__.alias("impersonation_target_users")

        result = await self.db.execute(
            select(ImpersonationSession)
            .join(actor_users, actor_users.c.user_id == ImpersonationSession.actor_user_id)
            .join(target_users, target_users.c.user_id == ImpersonationSession.target_user_id)
            .where(
                ImpersonationSession.id == session_id,
                ImpersonationSession.status == "ACTIVE",
                ImpersonationSession.expires_at > utc_now(),
                ImpersonationSession.actor_user_id == actor_user_id,
                ImpersonationSession.target_user_id == target_user_id,
                actor_users.c.is_active.is_(True),
                target_users.c.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def end(self, session: ImpersonationSession) -> ImpersonationSession:
        session.status = "ENDED"
        session.ended_at = utc_now()
        await self.db.flush()
        await self.db.refresh(session)
        return session
