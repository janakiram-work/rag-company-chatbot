"""In-process Pub/Sub Event Bus for Server-Sent Events (SSE).

Architecture Note:
The application operates with a single uvicorn worker process (enforced in production
deployments). This in-memory asynchronous queue bus routes live events across
all active client connections without requiring Redis or an external broker.
"""

import asyncio
import json
import logging
from typing import Dict, Set, Optional, List, Any

logger = logging.getLogger("events")


class EventSubscriber:
    """Represents an active SSE client connection."""

    def __init__(self, user_id: int, role: str):
        self.user_id = user_id
        self.role = role
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=100)


class EventBus:
    """In-memory event hub dispatching events to matching subscribers."""

    def __init__(self):
        self._subscribers: Set[EventSubscriber] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self, user_id: int, role: str) -> EventSubscriber:
        sub = EventSubscriber(user_id, role)
        async with self._lock:
            self._subscribers.add(sub)
        logger.debug(f"[SSE] User {user_id} ({role}) subscribed. Active listeners: {len(self._subscribers)}")
        return sub

    async def unsubscribe(self, sub: EventSubscriber):
        async with self._lock:
            self._subscribers.discard(sub)
        logger.debug(f"[SSE] User {sub.user_id} unsubscribed. Active listeners: {len(self._subscribers)}")

    def publish(
        self,
        event_type: str,
        data: Any = None,
        target_user_ids: Optional[List[int]] = None,
        target_roles: Optional[List[str]] = None,
    ):
        """Enqueue an event to matching subscribers."""
        payload = {
            "type": event_type,
            "data": data or {},
        }
        delivered = 0
        for sub in list(self._subscribers):
            if target_user_ids is not None and sub.user_id not in target_user_ids:
                continue
            if target_roles is not None and sub.role not in target_roles:
                continue

            try:
                sub.queue.put_nowait(payload)
                delivered += 1
            except asyncio.QueueFull:
                try:
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(payload)
                    delivered += 1
                except Exception:
                    pass
        logger.debug(f"[SSE] Published '{event_type}' to {delivered} subscriber(s)")


# Global singleton instance
event_bus = EventBus()


def publish_event(
    event_type: str,
    data: Any = None,
    target_user_ids: Optional[List[int]] = None,
    target_roles: Optional[List[str]] = None,
):
    """Convenience helper to publish an event asynchronously without blocking."""
    event_bus.publish(
        event_type=event_type,
        data=data,
        target_user_ids=target_user_ids,
        target_roles=target_roles,
    )
