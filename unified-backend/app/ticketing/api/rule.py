from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.schemas.rule import (
    RuleCreate,
    RuleEnabledUpdate,
    RuleReorderRequest,
    RuleResponse,
    RuleUpdate,
)
from app.ticketing.services.rule_service import RuleService

router = APIRouter(
    prefix="/rules",
    tags=["Rules"],
)


@router.get(
    "",
    response_model=list[RuleResponse],
)
async def list_rules(
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Every Mail Rule and OTP Rule, Mail Rules first — read is open to
    any authenticated agent (only create/update/delete/reorder are
    gated on rule:manage), matching this repo's general "read is
    open, write is gated" bias (see e.g. GET /sla/policies).
    """

    service = RuleService(RuleRepository(db))
    return await service.list_all()


@router.get(
    "/{rule_id}",
    response_model=RuleResponse,
)
async def get_rule(
    rule_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    service = RuleService(RuleRepository(db))
    return await service.get(rule_id)


@router.post(
    "",
    response_model=RuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_rule(
    request: RuleCreate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    service = RuleService(RuleRepository(db))
    return await service.create(request, current_user=current_user)


@router.put(
    "/{rule_id}",
    response_model=RuleResponse,
)
async def update_rule(
    rule_id: UUID,
    request: RuleUpdate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    service = RuleService(RuleRepository(db))
    return await service.update(rule_id, request, current_user=current_user)


@router.patch(
    "/{rule_id}/enabled",
    response_model=RuleResponse,
)
async def set_rule_enabled(
    rule_id: UUID,
    request: RuleEnabledUpdate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Backs the Rules list page's Enabled toggle switch."""

    service = RuleService(RuleRepository(db))
    return await service.set_enabled(rule_id, request.is_enabled, current_user=current_user)


@router.post(
    "/{rule_id}/reorder",
    response_model=list[RuleResponse],
)
async def reorder_rule(
    rule_id: UUID,
    request: RuleReorderRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Moves a rule up/down within its own category's priority order
    (Mail Rules and OTP Rules each have their own 1..N ordering).
    Returns the affected category's rules in their new order.
    """

    service = RuleService(RuleRepository(db))
    return await service.reorder(rule_id, request, current_user=current_user)


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_rule(
    rule_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    service = RuleService(RuleRepository(db))
    await service.delete(rule_id, current_user=current_user)
