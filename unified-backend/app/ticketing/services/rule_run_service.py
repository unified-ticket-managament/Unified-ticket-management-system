"""
"Run rule now" — queueing and read side. A run is a one-time,
background, retroactive pass of one rule over existing inbound mail;
rule_run_worker does the processing. See app.ticketing.models.rule_run
for the data model and rule_run_authorization for the mail-scope rules.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.ticketing.enums.rule_enums import RuleActionType
from app.ticketing.models.rule import Rule
from app.ticketing.models.rule_run import RuleRun, RuleRunPhase, RuleRunStatus
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.schemas.rule import RuleRunRef, RuleRunSummary
from app.ticketing.services.rule_run_authorization import (
    FORWARD_PERMISSION,
    MOVE_PERMISSION,
)
from app.ticketing.services.access_control import has_permission

logger = logging.getLogger(__name__)

# Server-side safety limit on real emails a single historical run may
# forward. Reaching it stops the run with status=capped — it never
# silently continues past it.
HISTORICAL_FORWARD_CAP = 500


def build_rule_snapshot(rule: Rule) -> dict:
    """The rule definition a run executes — frozen at trigger time."""

    return {
        "rule_id": str(rule.rule_id),
        "name": rule.name,
        "category": rule.category,
        "conditions": rule.conditions,
        "exceptions": rule.exceptions,
        "actions": rule.actions,
        "stop_processing": rule.stop_processing,
        "priority": rule.priority,
        "created_by": str(rule.created_by) if rule.created_by else None,
    }


def build_precedence_snapshot(target: Rule, enabled_ordered: list[Rule]) -> list[dict]:
    """
    Every enabled rule evaluated before `target` in the live pipeline
    (all Mail Rules by priority, then all OTP Rules by priority — the
    order RuleRepository.list_enabled_ordered returns) that has "Stop
    processing more rules" set. If one of these matches an email, the
    live engine never reaches `target` for it, so the run skips that
    email too. Only conditions are kept — their actions never run here.
    """

    preceding: list[dict] = []
    for rule in enabled_ordered:
        if rule.rule_id == target.rule_id:
            break
        if rule.stop_processing:
            preceding.append(
                {
                    "rule_id": str(rule.rule_id),
                    "name": rule.name,
                    "conditions": rule.conditions,
                    "exceptions": rule.exceptions,
                }
            )
    return preceding


def required_run_permissions(actions: list) -> set[str]:
    perms: set[str] = set()
    for action in actions or []:
        action_type = action.get("type") if isinstance(action, dict) else getattr(action, "type", None)
        if action_type == RuleActionType.MOVE_TO_FOLDER:
            perms.add(MOVE_PERMISSION)
        elif action_type == RuleActionType.FORWARD_TO:
            perms.add(FORWARD_PERMISSION)
    return perms


def to_ref(run: RuleRun | None) -> RuleRunRef | None:
    if run is None:
        return None
    return RuleRunRef(run_id=run.run_id, status=run.status)


class RuleRunService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active(self, rule_id: UUID) -> RuleRun | None:
        result = await self.db.execute(
            select(RuleRun)
            .where(RuleRun.rule_id == rule_id, RuleRun.status.in_(RuleRunStatus.ACTIVE))
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_latest(self, rule_id: UUID) -> RuleRun | None:
        result = await self.db.execute(
            select(RuleRun)
            .where(RuleRun.rule_id == rule_id)
            .order_by(RuleRun.created_at.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def list_active_by_rule_ids(self, rule_ids: list[UUID]) -> dict[UUID, RuleRun]:
        if not rule_ids:
            return {}
        result = await self.db.execute(
            select(RuleRun).where(
                RuleRun.rule_id.in_(rule_ids), RuleRun.status.in_(RuleRunStatus.ACTIVE)
            )
        )
        return {run.rule_id: run for run in result.scalars().all()}

    async def queue_run(self, rule: Rule, current_user: User) -> tuple[RuleRun, bool]:
        """
        Queues one run of `rule` (already saved/flushed in this same
        session, so the caller's single commit covers both — the save
        and the queued run land together or not at all). Returns
        (run, created): an already-active run for this rule is returned
        as-is rather than starting a second one; the partial unique
        index uq_rule_runs_one_active_per_rule is the real guard against
        a concurrent double-submit racing past the check below.

        The caller has already authorized `current_user` to manage
        `rule`. This only adds run-specific preconditions; the actual
        mail scope is enforced per email by the worker.
        """

        if not rule.is_enabled:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Enable the rule to run it against existing messages.",
            )

        missing = sorted(
            perm for perm in required_run_permissions(rule.actions)
            if not has_permission(current_user, perm)
        )
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "You need " + ", ".join(missing)
                    + " to run this rule against existing messages."
                ),
            )

        existing = await self.get_active(rule.rule_id)
        if existing is not None:
            return existing, False

        enabled_ordered = await RuleRepository(self.db).list_enabled_ordered()

        run = RuleRun(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            rule_owner_id=rule.created_by,
            triggered_by=current_user.user_id,
            impersonator_id=getattr(current_user, "impersonator_id", None),
            impersonator_name=getattr(current_user, "impersonator_name", None),
            status=RuleRunStatus.QUEUED,
            phase=RuleRunPhase.SCAN,
            rule_snapshot=build_rule_snapshot(rule),
            precedence_snapshot=build_precedence_snapshot(rule, enabled_ordered),
            scope={
                "model": "rule_owner_intersect_triggering_user",
                "rule_owner_id": str(rule.created_by) if rule.created_by else None,
                "triggered_by": str(current_user.user_id),
                "triggered_by_role": current_user.role.name if current_user.role else None,
            },
            cutoff_at=datetime.now(timezone.utc),
            skipped_by_reason={},
            error_samples=[],
        )

        try:
            async with self.db.begin_nested():
                self.db.add(run)
                await self.db.flush()
        except IntegrityError:
            # Lost a race with a concurrent trigger for the same rule.
            existing = await self.get_active(rule.rule_id)
            if existing is None:
                raise
            return existing, False

        logger.info(
            "RULE_RUN_QUEUED run_id=%s rule_id=%s triggered_by=%s rule_owner_id=%s impersonator_id=%s",
            run.run_id,
            rule.rule_id,
            current_user.user_id,
            rule.created_by,
            run.impersonator_id,
        )
        return run, True

    @staticmethod
    def to_summary(run: RuleRun) -> RuleRunSummary:
        return RuleRunSummary.model_validate(run)
