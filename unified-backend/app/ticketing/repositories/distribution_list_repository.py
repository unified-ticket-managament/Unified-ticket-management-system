# distribution_list_repository.py

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.ticketing.models.distribution_list import DistributionList, DistributionListMember


class DistributionListRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, distribution_list_id: UUID) -> DistributionList | None:
        result = await self.db.execute(
            select(DistributionList).where(
                DistributionList.distribution_list_id == distribution_list_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name_case_insensitive(
        self, name: str, exclude_id: UUID | None = None
    ) -> DistributionList | None:
        query = select(DistributionList).where(
            func.lower(DistributionList.name) == name.strip().lower()
        )
        if exclude_id is not None:
            query = query.where(DistributionList.distribution_list_id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_all(self) -> list[DistributionList]:
        result = await self.db.execute(
            select(DistributionList).order_by(DistributionList.name.asc())
        )
        return list(result.scalars().all())

    async def list_active_with_member_counts(self) -> list[tuple[DistributionList, int]]:
        """
        Every active Distribution List, paired with a count of its
        *active-user* members — backs both the admin summary list and
        the shared recipient-selection endpoint. One LEFT JOIN +
        GROUP BY, never N+1.
        """

        result = await self.db.execute(
            select(DistributionList, func.count(User.user_id))
            .outerjoin(
                DistributionListMember,
                DistributionListMember.distribution_list_id
                == DistributionList.distribution_list_id,
            )
            .outerjoin(
                User,
                (User.user_id == DistributionListMember.user_id)
                & (User.is_active.is_(True)),
            )
            .where(DistributionList.is_active.is_(True))
            .group_by(DistributionList.distribution_list_id)
            .order_by(DistributionList.name.asc())
        )
        return [(row[0], row[1]) for row in result.all()]

    async def list_with_member_counts(self) -> list[tuple[DistributionList, int]]:
        """Same as list_active_with_member_counts but for every list, active or not (admin view)."""

        result = await self.db.execute(
            select(DistributionList, func.count(User.user_id))
            .outerjoin(
                DistributionListMember,
                DistributionListMember.distribution_list_id
                == DistributionList.distribution_list_id,
            )
            .outerjoin(
                User,
                (User.user_id == DistributionListMember.user_id)
                & (User.is_active.is_(True)),
            )
            .group_by(DistributionList.distribution_list_id)
            .order_by(DistributionList.name.asc())
        )
        return [(row[0], row[1]) for row in result.all()]

    async def list_members(self, distribution_list_id: UUID) -> list[User]:
        result = await self.db.execute(
            select(User)
            .join(
                DistributionListMember,
                DistributionListMember.user_id == User.user_id,
            )
            .where(DistributionListMember.distribution_list_id == distribution_list_id)
            .order_by(User.name.asc())
        )
        return list(result.scalars().all())

    async def create(self, distribution_list: DistributionList) -> DistributionList:
        self.db.add(distribution_list)
        await self.db.flush()
        await self.db.refresh(distribution_list)
        return distribution_list

    async def save(self, distribution_list: DistributionList) -> DistributionList:
        await self.db.flush()
        await self.db.refresh(distribution_list)
        return distribution_list

    async def delete(self, distribution_list: DistributionList) -> None:
        await self.db.delete(distribution_list)
        await self.db.flush()

    async def add_member(
        self, distribution_list_id: UUID, user_id: UUID
    ) -> DistributionListMember | None:
        """Returns None (no-op) if the membership already exists — idempotent."""

        existing = await self.db.execute(
            select(DistributionListMember).where(
                DistributionListMember.distribution_list_id == distribution_list_id,
                DistributionListMember.user_id == user_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return None

        member = DistributionListMember(
            distribution_list_id=distribution_list_id, user_id=user_id
        )
        self.db.add(member)
        await self.db.flush()
        return member

    async def remove_member(self, distribution_list_id: UUID, user_id: UUID) -> bool:
        """Returns whether a row was actually deleted."""

        result = await self.db.execute(
            select(DistributionListMember).where(
                DistributionListMember.distribution_list_id == distribution_list_id,
                DistributionListMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        if member is None:
            return False

        await self.db.delete(member)
        await self.db.flush()
        return True

    async def get_active_member_emails_by_list_ids(
        self, distribution_list_ids: list[UUID]
    ) -> dict[UUID, dict[UUID, str]]:
        """
        {distribution_list_id: {user_id: email}} — resolved server-side
        at send time, never trusted from a client. Only lists that are
        themselves `is_active=True`, and only members whose own User
        row is `is_active=True`, contribute. A deactivated/stale list
        id (or one with zero currently-active members) is present with
        an empty dict, not omitted, so callers can tell "resolved to
        nothing" apart from "wasn't a real id at all" if they need to.
        One JOIN query, never N+1.
        """

        if not distribution_list_ids:
            return {}

        result = await self.db.execute(
            select(
                DistributionListMember.distribution_list_id,
                DistributionListMember.user_id,
                User.email,
            )
            .join(
                DistributionList,
                DistributionList.distribution_list_id
                == DistributionListMember.distribution_list_id,
            )
            .join(User, User.user_id == DistributionListMember.user_id)
            .where(
                DistributionListMember.distribution_list_id.in_(distribution_list_ids),
                DistributionList.is_active.is_(True),
                User.is_active.is_(True),
            )
        )

        resolved: dict[UUID, dict[UUID, str]] = {
            list_id: {} for list_id in distribution_list_ids
        }
        for list_id, user_id, email in result.all():
            resolved[list_id][user_id] = email
        return resolved
