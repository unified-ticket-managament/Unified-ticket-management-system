from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.notifications.repository import NotificationRepository
from app.notifications.schemas import (
    MarkReadResponse,
    NotificationListResponse,
    NotificationResponse,
)

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
)


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Every notification for the caller, newest first. The bell badge
    reads `unread_count`, which is always the caller's TOTAL unread
    count (not just unread within this page), so pagination never
    makes the badge undercount.
    """

    repository = NotificationRepository(db)

    items = await repository.list_for_user(
        current_user.user_id, unread_only=unread_only, limit=limit, offset=offset
    )
    total = await repository.count_for_user(current_user.user_id, unread_only=unread_only)
    unread_count = await repository.count_for_user(current_user.user_id, unread_only=True)

    return NotificationListResponse(
        total=total,
        unread_count=unread_count,
        items=[NotificationResponse.model_validate(item) for item in items],
    )


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repository = NotificationRepository(db)

    notification = await repository.get_by_id(notification_id)

    if notification is None or notification.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )

    notification = await repository.mark_read(notification)

    return NotificationResponse.model_validate(notification)


@router.post("/read-all", response_model=MarkReadResponse)
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repository = NotificationRepository(db)
    await repository.mark_all_read(current_user.user_id)

    return MarkReadResponse(message="All notifications marked as read.")
