"""
app/services/sync_service.py
─────────────────────────────
Real-time cross-device sync manager (Addon #4).
Maintains active WebSocket connections per student and broadcasts sync events:
- session_created / session_updated
- message_received
- quiz_completed
- space_changed
- streak_updated
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Set, Any, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class SyncConnectionManager:
    """
    Manages active WebSocket connections mapped by user_id.
    Thread-safe event broadcast across multiple browser tabs / mobile devices.
    """

    def __init__(self):
        # user_id -> set of active WebSockets
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        """Accepts and registers a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = set()
            self._connections[user_id].add(websocket)
        logger.info(f"[RealTime Sync] Client connected for user={user_id}. Total active: {len(self._connections[user_id])}")

    async def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        """Removes a disconnected WebSocket connection."""
        async with self._lock:
            if user_id in self._connections:
                self._connections[user_id].discard(websocket)
                if not self._connections[user_id]:
                    del self._connections[user_id]
        logger.info(f"[RealTime Sync] Client disconnected for user={user_id}")

    async def broadcast_to_user(
        self,
        user_id: str,
        event: str,
        data: Dict[str, Any],
        exclude_socket: Optional[WebSocket] = None,
    ) -> int:
        """
        Asynchronously sends an event payload to all active WebSockets of a student.
        Returns the number of connected clients that received the event.
        """
        async with self._lock:
            sockets = list(self._connections.get(user_id, []))

        if not sockets:
            return 0

        payload = {
            "event": event,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        msg_str = json.dumps(payload)

        sent_count = 0
        stale_sockets = []

        for ws in sockets:
            if ws == exclude_socket:
                continue
            try:
                await ws.send_text(msg_str)
                sent_count += 1
            except Exception as exc:
                logger.debug(f"[RealTime Sync] Error sending to socket: {exc}")
                stale_sockets.append(ws)

        # Cleanup any broken sockets
        if stale_sockets:
            async with self._lock:
                for s in stale_sockets:
                    if user_id in self._connections:
                        self._connections[user_id].discard(s)

        return sent_count

    def sync_broadcast(self, user_id: str, event: str, data: Dict[str, Any]) -> None:
        """
        Thread-safe method callable from synchronous routes or background threads.
        Schedules broadcast_to_user on the running event loop without blocking.
        """
        try:
            loop = self._loop or asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.broadcast_to_user(user_id, event, data), loop
                )
            else:
                loop.run_until_complete(self.broadcast_to_user(user_id, event, data))
        except RuntimeError:
            # If no loop in current thread, spawn a quick runner
            try:
                new_loop = asyncio.new_event_loop()
                new_loop.run_until_complete(self.broadcast_to_user(user_id, event, data))
                new_loop.close()
            except Exception as e:
                logger.warning(f"[RealTime Sync] Background broadcast failed: {e}")
        except Exception as exc:
            logger.warning(f"[RealTime Sync] sync_broadcast error: {exc}")

    def get_user_connection_count(self, user_id: str) -> int:
        return len(self._connections.get(user_id, set()))

    def get_total_connections(self) -> int:
        return sum(len(s) for s in self._connections.values())


# Singleton instance
sync_manager = SyncConnectionManager()
