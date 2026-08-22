# distribution_list.py
#
# Two independently-gated route groups in one router:
# - Admin CRUD (list/get/create/update/active-toggle/members/delete)
#   — gated on rule:manage inside DistributionListService.
# - GET /active — the shared, unscoped "recipient selection" listing
#   every picker in the app fetches from (Forward, Compose, Reply,
#   Ticket Reply, Internal Note, Rules' forward_to). Gated only by
#   Depends(get_current_agent), deliberately NOT rule:manage/
#   rule:view_all — mirrors GET /tickets/internal-notes/recipients.
#
# /active is registered before /{distribution_list_id} so FastAPI's
# static-path-before-path-param matching doesn't treat "active" as a
# UUID.

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent
from app.ticketing.repositories.distribution_list_repository import (
    DistributionListRepository,
)
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.distribution_list import (
    DistributionListActiveUpdate,
    DistributionListCreate,
    DistributionListMemberAdd,
    DistributionListRecipientsResponse,
    DistributionListResponse,
    DistributionListSummaryResponse,
    DistributionListUpdate,
)
from app.ticketing.services.distribution_list_service import DistributionListService

router = APIRouter(prefix="/distribution-lists", tags=["Distribution Lists"])


def _service(db: AsyncSession) -> DistributionListService:
    return DistributionListService(DistributionListRepository(db), UserRepository(db))


@router.get("/active", response_model=DistributionListRecipientsResponse)
async def list_active_distribution_lists(
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Every active Distribution List, for use in a recipient picker —
    authenticated-agent-only, no rule:manage/rule:view_all check. See
    this module's own top-of-file docstring.
    """

    candidates = await _service(db).list_active_for_recipient_picker()
    return DistributionListRecipientsResponse(distribution_lists=candidates)


@router.get("", response_model=list[DistributionListSummaryResponse])
async def list_distribution_lists(
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    return await _service(db).list_all(current_user=current_user)


@router.get("/{distribution_list_id}", response_model=DistributionListResponse)
async def get_distribution_list(
    distribution_list_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    return await _service(db).get(distribution_list_id, current_user=current_user)


@router.post("", response_model=DistributionListResponse, status_code=status.HTTP_201_CREATED)
async def create_distribution_list(
    request: DistributionListCreate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    return await _service(db).create(request, current_user=current_user)


@router.put("/{distribution_list_id}", response_model=DistributionListResponse)
async def update_distribution_list(
    distribution_list_id: UUID,
    request: DistributionListUpdate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    return await _service(db).update(distribution_list_id, request, current_user=current_user)


@router.patch("/{distribution_list_id}/active", response_model=DistributionListResponse)
async def set_distribution_list_active(
    distribution_list_id: UUID,
    request: DistributionListActiveUpdate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    return await _service(db).set_active(
        distribution_list_id, request.is_active, current_user=current_user
    )


@router.post("/{distribution_list_id}/members", response_model=DistributionListResponse)
async def add_distribution_list_member(
    distribution_list_id: UUID,
    request: DistributionListMemberAdd,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    return await _service(db).add_member(
        distribution_list_id, request.user_id, current_user=current_user
    )


@router.delete("/{distribution_list_id}/members/{user_id}", response_model=DistributionListResponse)
async def remove_distribution_list_member(
    distribution_list_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    return await _service(db).remove_member(
        distribution_list_id, user_id, current_user=current_user
    )


@router.delete("/{distribution_list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_distribution_list(
    distribution_list_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    await _service(db).delete(distribution_list_id, current_user=current_user)
