"""
In-memory, per-process pub/sub that lets NotificationService.notify()
push a freshly-created notification straight to any open SSE
connection(s) for its recipient — same "per-process only, no Redis"
tradeoff already established by app/core/rbac_cache.py (see that
module's own docstring for the rationale): this backend runs as a
single uvicorn process (scripts/start.sh), so an in-memory registry
needs no cross-process broadcast. If this app is ever scaled to
multiple worker processes, this would need to move to a shared pub/sub
(Redis, Postgres LISTEN/NOTIFY) — a real infrastructure change, not
attempted here.

Keyed on user_id as a plain string (just a dict key here, never
queried) -> a set of asyncio.Queue, one per open connection. A user can
have more than one queue at once (multiple browser tabs, multiple
devices) — every queue for that user_id gets its own copy of every
event, so each tab updates independently.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# Bounded so one connection whose consumer has stopped draining (a
# disconnect the server hasn't detected yet) can never grow memory
# unboundedly — further events for that one queue are dropped instead
# of blocking the publisher or every other recipient. A live connection
# drains its queue essentially as fast as events arrive, so actually
# hitting this bound means the connection is already dead in practice.
_QUEUE_MAX_SIZE = 100

# Mail events are only invalidation SIGNALS (the browser refetches the
# real data itself), so they are the first thing shed under pressure:
# once a connection's queue is this full they are skipped, which keeps a
# burst of incoming mail (a poll can ingest dozens at once) from ever
# crowding out a real notification on the same connection.
_MAIL_EVENT_MAX_QUEUE_FILL = _QUEUE_MAX_SIZE // 2


class NotificationStreamManager:
    """Thread-unsafe by design — every caller runs on the single asyncio
    event loop this process serves, same convention as app/core/
    rbac_cache.py's resolution_lock. The lock below only serializes
    concurrent coroutines on that one loop, not separate OS threads."""

    def __init__(self):
        self._queues: dict[str, set[asyncio.Queue]] = defaultdict(set)
        # Connections whose user may see EVERY inbound mail (Site Lead /
        # Super Admin) — they receive mail events without being named in
        # an event's audience, so ingestion never has to look them up.
        self._all_mail_queues: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def subscribe(
        self, user_id: str, *, receives_all_mail: bool = False
    ) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        async with self._lock:
            self._queues[user_id].add(queue)
            if receives_all_mail:
                self._all_mail_queues.add(queue)
            count = len(self._queues[user_id])
        logger.info("SSE_SUBSCRIBE user_id=%s connections=%d", user_id, count)
        return queue

    async def unsubscribe(self, user_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            queues = self._queues.get(user_id)
            if queues is None:
                return
            queues.discard(queue)
            self._all_mail_queues.discard(queue)
            if not queues:
                self._queues.pop(user_id, None)
        logger.info("SSE_UNSUBSCRIBE user_id=%s", user_id)

    def has_subscribers(self, user_id: str) -> bool:
        """
        Cheap pre-check so notify() can skip the extra unread-count
        query entirely for a recipient with no open tab — the common
        case for most notification types.
        """

        return bool(self._queues.get(user_id))

    async def publish(self, user_id: str, payload: dict[str, Any]) -> None:
        queues = self._queues.get(user_id)
        if not queues:
            return
        for queue in list(queues):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning(
                    "SSE_QUEUE_FULL user_id=%s — dropping event for a stalled connection",
                    user_id,
                )


    def publish_mail_event(
        self, audience_user_ids: set[str], payload: dict[str, Any]
    ) -> int:
        """
        Delivers one lightweight mail event (an invalidation signal — ids
        and a timestamp only, never message content) to every open
        connection whose user is in `audience_user_ids`, plus every
        "receives all mail" connection. Synchronous (put_nowait only), so
        it is safe to call from a SQLAlchemy after_commit hook. Returns
        how many connections it was queued for.

        Mail events share a connection's queue with notifications but are
        shed first (see _MAIL_EVENT_MAX_QUEUE_FILL).
        """

        event = {**payload, "_sse_event": "mail"}
        delivered = 0
        for user_id, queues in list(self._queues.items()):
            for queue in list(queues):
                if user_id not in audience_user_ids and queue not in self._all_mail_queues:
                    continue
                if queue.qsize() >= _MAIL_EVENT_MAX_QUEUE_FILL:
                    logger.debug("SSE_MAIL_EVENT_SHED user_id=%s", user_id)
                    continue
                try:
                    queue.put_nowait(event)
                    delivered += 1
                except asyncio.QueueFull:
                    logger.debug("SSE_MAIL_EVENT_SHED user_id=%s", user_id)
        return delivered


_manager: NotificationStreamManager | None = None


def get_notification_stream_manager() -> NotificationStreamManager:
    """Module-level singleton — one registry per process, lazily built."""

    global _manager
    if _manager is None:
        _manager = NotificationStreamManager()
    return _manager
