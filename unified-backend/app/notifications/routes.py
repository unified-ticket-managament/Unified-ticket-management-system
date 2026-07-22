import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_user, get_current_user_sse
from app.notifications.repository import NotificationRepository
from app.notifications.schemas import (
    MarkReadResponse,
    NotificationListResponse,
    NotificationResponse,
)
from app.notifications.sse_manager import get_notification_stream_manager

logger = logging.getLogger(__name__)

# Comfortably inside the "20-30s" window the migration spec asks for —
# also well under any typical reverse-proxy/load-balancer idle-connection
# timeout (most default to 60s+), which is the actual failure mode a
# heartbeat prevents: no bytes flowing for that long and an intermediary
# silently drops the connection without either end seeing a clean close.
HEARTBEAT_INTERVAL_SECONDS = 25

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


@router.get("/stream")
async def stream_notifications(
    request: Request,
    current_user: User = Depends(get_current_user_sse),
):
    """
    Server-Sent Events stream: one persistent connection per open tab,
    pushing this user's own new notifications the instant
    NotificationService.notify() creates them (see
    app/notifications/sse_manager.py) — the real-time replacement for
    the frontend's old 30s GET /notifications poll. Authenticated via
    get_current_user_sse (a query-param token, not a header — see that
    dependency's own docstring for why this one route is different).

    Deliberately takes no `db` dependency of its own beyond what
    get_current_user_sse needs to resolve the caller — once
    subscribed, this generator only reads from an in-memory queue, it
    never touches Postgres again for the life of the connection.

    Each event is `event: notification` with a JSON `data:` payload
    shaped `{"notification": {...same shape as GET /notifications
    items...}, "unread_count": <int>}`. A `: heartbeat` comment line
    (never surfaced to EventSource's onmessage/addEventListener, by the
    SSE spec) is sent whenever HEARTBEAT_INTERVAL_SECONDS elapses with
    nothing new, both to keep intermediary proxies from treating the
    connection as idle and to double as this generator's own
    disconnect-detection tick.
    """

    manager = get_notification_stream_manager()
    user_id_str = str(current_user.user_id)
    queue = await manager.subscribe(user_id_str)

    async def event_generator():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(
                        queue.get(), timeout=HEARTBEAT_INTERVAL_SECONDS
                    )
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": heartbeat\n\n"
                    continue

                yield f"event: notification\ndata: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            # The client disconnected (tab closed, navigated away,
            # network drop) — not an error, just the normal way this
            # generator ends. Re-raised so Starlette's own cancellation
            # handling still completes correctly; cleanup happens in
            # `finally` either way.
            raise
        finally:
            await manager.unsubscribe(user_id_str, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Reverse proxies (nginx, etc.) buffer a response by
            # default, which would batch/delay events instead of
            # flushing each one immediately — the entire point of this
            # endpoint. Ignored by anything that isn't nginx-like; not
            # a native SSE spec header, just its widely-supported
            # opt-out convention.
            "X-Accel-Buffering": "no",
        },
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
