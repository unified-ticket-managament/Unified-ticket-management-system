from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.models.rule import Rule
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.schemas.rule import (
    RuleCreate,
    RuleReorderRequest,
    RuleResponse,
    RuleUpdate,
)
from app.ticketing.services.access_control import ensure_has_permission

RULE_MANAGE_PERMISSION = "rule:manage"


class RuleService:
    """
    CRUD + ordering for Mail/OTP Rules. No audit logging (mirrors
    MailFolderService's own reasoning — creating/editing an automation
    rule is an org-config action, not a client-communication event);
    execution-time behavior (what a matching rule actually does) is
    RuleEngineService's job, not this one's.
    """

    def __init__(self, rule_repository: RuleRepository):
        self.rule_repository = rule_repository

    async def list_all(self) -> list[RuleResponse]:
        rules = await self.rule_repository.list_all()
        return [RuleResponse.model_validate(r) for r in rules]

    async def get(self, rule_id: UUID) -> RuleResponse:
        rule = await self._get_or_404(rule_id)
        return RuleResponse.model_validate(rule)

    async def create(self, request: RuleCreate, current_user: User) -> RuleResponse:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)

        priority = await self.rule_repository.get_next_priority(request.category)

        rule = Rule(
            name=request.name,
            category=request.category,
            is_enabled=request.is_enabled,
            # mode="json" — plain dict()/model_dump() leaves
            # employee_user_ids as real UUID objects, which asyncpg's
            # JSONB codec can't serialize (TypeError: Object of type
            # UUID is not JSON serializable). mode="json" round-trips
            # everything through JSON-compatible types (UUID -> str)
            # first.
            conditions=request.conditions.model_dump(mode="json"),
            exceptions=request.exceptions.model_dump(mode="json"),
            actions=[a.model_dump(mode="json") for a in request.actions],
            stop_processing=request.stop_processing,
            priority=priority,
            created_by=current_user.user_id,
        )

        created = await self.rule_repository.create(rule)
        return RuleResponse.model_validate(created)

    async def update(self, rule_id: UUID, request: RuleUpdate, current_user: User) -> RuleResponse:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)

        rule.name = request.name
        rule.is_enabled = request.is_enabled
        rule.conditions = request.conditions.model_dump(mode="json")
        rule.exceptions = request.exceptions.model_dump(mode="json")
        rule.actions = [a.model_dump(mode="json") for a in request.actions]
        rule.stop_processing = request.stop_processing

        saved = await self.rule_repository.save(rule)
        return RuleResponse.model_validate(saved)

    async def set_enabled(self, rule_id: UUID, is_enabled: bool, current_user: User) -> RuleResponse:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)
        rule.is_enabled = is_enabled
        saved = await self.rule_repository.save(rule)
        return RuleResponse.model_validate(saved)

    async def delete(self, rule_id: UUID, current_user: User) -> None:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)
        await self.rule_repository.delete(rule)

    async def reorder(
        self, rule_id: UUID, request: RuleReorderRequest, current_user: User
    ) -> list[RuleResponse]:
        ensure_has_permission(current_user, RULE_MANAGE_PERMISSION)
        rule = await self._get_or_404(rule_id)
        siblings = await self.rule_repository.list_by_category_ordered(rule.category)

        index = next(i for i, r in enumerate(siblings) if r.rule_id == rule.rule_id)
        swap_index = index - 1 if request.direction == "up" else index + 1

        if swap_index < 0 or swap_index >= len(siblings):
            # Already at the top/bottom — a no-op, not an error, so the
            # UI's disabled-at-the-edge Up/Down buttons never need to
            # special-case this themselves.
            return [RuleResponse.model_validate(r) for r in siblings]

        neighbor = siblings[swap_index]
        rule.priority, neighbor.priority = neighbor.priority, rule.priority

        await self.rule_repository.save(rule)
        await self.rule_repository.save(neighbor)

        refreshed = await self.rule_repository.list_by_category_ordered(rule.category)
        return [RuleResponse.model_validate(r) for r in refreshed]

    async def _get_or_404(self, rule_id: UUID) -> Rule:
        rule = await self.rule_repository.get_by_id(rule_id)
        if rule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rule not found.",
            )
        return rule
