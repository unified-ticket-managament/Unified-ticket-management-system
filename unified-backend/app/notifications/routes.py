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
    types: str | None = Query(
        default=None,
        description=(
            "Comma-separated notification_type values to restrict the list to "
            "(e.g. the Mail page's System folder passing every SLA_*/ESCALATION_* "
            "type) — omit for the unfiltered bell/full list, same as before this "
            "param existed."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Every notification for the caller, newest first. The bell badge
    reads `unread_count`, which is always the caller's TOTAL unread
    count (not just unread within this page), so pagination never
    makes the badge undercount — `types`, when passed, scopes both the
    page and both counts to the same subset, so a filtered view's own
    badge/total stay internally consistent too.
    """

    repository = NotificationRepository(db)
    notification_types = (
        [t.strip() for t in types.split(",") if t.strip()] if types else None
    )

    items = await repository.list_for_user(
        current_user.user_id,
        unread_only=unread_only,
        notification_types=notification_types,
        limit=limit,
        offset=offset,
    )
    total = await repository.count_for_user(
        current_user.user_id, unread_only=unread_only, notification_types=notification_types
    )
    unread_count = await repository.count_for_user(
        current_user.user_id, unread_only=True, notification_types=notification_types
    )

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
