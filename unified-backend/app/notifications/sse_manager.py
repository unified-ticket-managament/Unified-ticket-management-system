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


class NotificationStreamManager:
    """Thread-unsafe by design — every caller runs on the single asyncio
    event loop this process serves, same convention as app/core/
    rbac_cache.py's resolution_lock. The lock below only serializes
    concurrent coroutines on that one loop, not separate OS threads."""

    def __init__(self):
        self._queues: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, user_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        async with self._lock:
            self._queues[user_id].add(queue)
            count = len(self._queues[user_id])
        logger.info("SSE_SUBSCRIBE user_id=%s connections=%d", user_id, count)
        return queue

    async def unsubscribe(self, user_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            queues = self._queues.get(user_id)
            if queues is None:
                return
            queues.discard(queue)
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


_manager: NotificationStreamManager | None = None


def get_notification_stream_manager() -> NotificationStreamManager:
    """Module-level singleton — one registry per process, lazily built."""

    global _manager
    if _manager is None:
        _manager = NotificationStreamManager()
    return _manager
