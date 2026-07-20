from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.enums import TicketPriority
from app.ticketing.models.sla_policy import SLAPolicy

#sla_policy_repository.py
class SLAPolicyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_priority(self, priority: TicketPriority) -> SLAPolicy | None:
        result = await self.db.execute(
            select(SLAPolicy).where(
                SLAPolicy.priority == priority,
                SLAPolicy.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[SLAPolicy]:
        result = await self.db.execute(
            select(SLAPolicy).order_by(SLAPolicy.priority)
        )
        return list(result.scalars().all())

    async def get_by_id(self, policy_id) -> SLAPolicy | None:
        result = await self.db.execute(
            select(SLAPolicy).where(SLAPolicy.policy_id == policy_id)
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        policy: SLAPolicy,
        *,
        first_response_target_minutes: int | None = None,
        resolution_target_minutes: int | None = None,
        escalation_ack_target_minutes: int | None = None,
        handling_sla_percentage: float | None = None,
        handling_stage_percentages: list[float] | None = None,
        warning_1_percentage: float | None = None,
        warning_2_percentage: float | None = None,
        is_active: bool | None = None,
    ) -> SLAPolicy:
        if first_response_target_minutes is not None:
            policy.first_response_target_minutes = first_response_target_minutes
        if resolution_target_minutes is not None:
            policy.resolution_target_minutes = resolution_target_minutes
        if escalation_ack_target_minutes is not None:
            policy.escalation_ack_target_minutes = escalation_ack_target_minutes
        if handling_sla_percentage is not None:
            policy.handling_sla_percentage = handling_sla_percentage
        if handling_stage_percentages is not None:
            policy.handling_stage_percentages = handling_stage_percentages
        if warning_1_percentage is not None:
            policy.warning_1_percentage = warning_1_percentage
        if warning_2_percentage is not None:
            policy.warning_2_percentage = warning_2_percentage
        if is_active is not None:
            policy.is_active = is_active

        await self.db.flush()
        await self.db.refresh(policy)
        return policy
