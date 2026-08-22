from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.rule import Rule


class RuleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[Rule]:
        result = await self.db.execute(
            select(Rule).order_by(Rule.category.asc(), Rule.priority.asc())
        )
        return list(result.scalars().all())

    async def list_owned_or_shared(self, user_id: UUID) -> list[Rule]:
        """
        Every rule `user_id` created, plus every rule they've been
        explicitly added/shared/assigned to — the rule:view_all-less
        path. `shared_user_ids.contains([...])` compiles to Postgres's
        JSONB `@>` containment operator, the same pattern this
        codebase already uses for TicketEscalation.owner_ids.
        """

        result = await self.db.execute(
            select(Rule)
            .where(
                or_(
                    Rule.created_by == user_id,
                    Rule.shared_user_ids.contains([str(user_id)]),
                )
            )
            .order_by(Rule.category.asc(), Rule.priority.asc())
        )
        return list(result.scalars().all())

    async def list_enabled_ordered(self) -> list[Rule]:
        """
        Every enabled rule, Mail Rules (in priority order) before OTP
        Rules (in priority order) — the exact "Mail Rules -> OTP
        Rules" pipeline the engine evaluates in. `category` sorts
        "mail_rule" before "otp_rule" alphabetically, which happens to
        already match; ordering is by the literal category values
        rather than relying on that coincidence.
        """

        result = await self.db.execute(
            select(Rule)
            .where(Rule.is_enabled.is_(True))
            .order_by(Rule.category.asc(), Rule.priority.asc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, rule_id: UUID) -> Rule | None:
        result = await self.db.execute(select(Rule).where(Rule.rule_id == rule_id))
        return result.scalar_one_or_none()

    async def get_next_priority(self, category: str) -> int:
        result = await self.db.execute(
            select(func.max(Rule.priority)).where(Rule.category == category)
        )
        current_max = result.scalar_one_or_none()
        return (current_max or 0) + 1

    async def create(self, rule: Rule) -> Rule:
        self.db.add(rule)
        await self.db.flush()
        await self.db.refresh(rule)
        return rule

    async def save(self, rule: Rule) -> Rule:
        await self.db.flush()
        await self.db.refresh(rule)
        return rule

    async def delete(self, rule: Rule) -> None:
        await self.db.delete(rule)
        await self.db.flush()

    async def list_by_category_ordered(self, category: str) -> list[Rule]:
        result = await self.db.execute(
            select(Rule)
            .where(Rule.category == category)
            .order_by(Rule.priority.asc())
        )
        return list(result.scalars().all())
