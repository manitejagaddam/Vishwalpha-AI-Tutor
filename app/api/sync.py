"""
app/api/sync.py
───────────────
WebSocket and HTTP endpoints for Real-Time Cross-Device Sync (Addon #4).
Allows students to stay synchronized across multiple tabs, phones, and laptops.
"""
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional, Dict, Any

from app.api.deps import get_current_user, decode_token_user_id
from app.data.models.platform import User
from app.services.sync_service import sync_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["RealTime Sync"])


class BroadcastEventRequest(BaseModel):
    event: str
    data: Dict[str, Any]


@router.websocket("/ws")
async def websocket_sync_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="JWT access token for authentication"),
):
    """
    WebSocket endpoint for real-time state synchronization.
    Authenticate via query param ?token=<jwt_access_token>.

    Connection flow:
    1. Connect: ws://<host>/sync/ws?token=<access_token>
    2. Server sends: {"event": "connected", "data": {"user_id": "...", "active_devices": 1}}
    3. Send ping: {"type": "ping"} -> receive {"event": "pong"}
    4. Other event types the client can send: typing, presence, space_switch
    5. The server broadcasts quiz_completed, space_updated events to all other tabs.
    """
    # CRITICAL: WebSocket MUST be accepted before close() can be called.
    # If we close before accept, the browser sees readyState:3 immediately
    # and throws "WebSocket is closed before the connection is established".
    await websocket.accept()

    if not token:
        # Try to receive an auth handshake message as fallback
        try:
            auth_msg = await websocket.receive_text()
            data = json.loads(auth_msg)
            token = data.get("token")
        except Exception:
            await websocket.send_text(json.dumps({"event": "error", "detail": "Authentication token missing"}))
            await websocket.close(code=4001)
            return

    user_id = decode_token_user_id(token)
    if not user_id:
        await websocket.send_text(json.dumps({"event": "error", "detail": "Invalid or expired token"}))
        await websocket.close(code=4003)
        return

    # Store current running loop in manager
    import asyncio
    sync_manager.set_loop(asyncio.get_running_loop())

    # Register this socket (connect() also calls accept() — skip the second accept)
    async with sync_manager._lock:
        if user_id not in sync_manager._connections:
            sync_manager._connections[user_id] = set()
        sync_manager._connections[user_id].add(websocket)
    logger.info(f"[RealTime Sync] Client connected for user={user_id}. Total active: {len(sync_manager._connections[user_id])}")

    # Send initial connection confirmation
    await websocket.send_text(json.dumps({
        "event": "connected",
        "data": {
            "user_id": user_id,
            "active_devices": sync_manager.get_user_connection_count(user_id),
            "message": "Real-time cross-device sync active."
        }
    }))

    try:
        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
                event_type = msg.get("type") or msg.get("event")

                if event_type == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))
                elif event_type in ("typing", "presence", "space_switch"):
                    await sync_manager.broadcast_to_user(
                        user_id=user_id,
                        event=event_type,
                        data=msg.get("data", {}),
                        exclude_socket=websocket,
                    )
            except json.JSONDecodeError:
                if text == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        await sync_manager.disconnect(user_id, websocket)
    except Exception as exc:
        logger.debug(f"[RealTime Sync] Socket exception: {exc}")
        await sync_manager.disconnect(user_id, websocket)


@router.post(
    "/broadcast",
    summary="Broadcast a sync event to other devices",
    description=(
        "Manually triggers a real-time event broadcast to all other connected devices of the authenticated student. "
        "Common event names: `space_switch`, `typing`, `presence`. The `data` dict is forwarded as-is."
    ),
    responses={401: {"description": "Token missing or invalid"}},
)
async def broadcast_event_endpoint(
    body: BroadcastEventRequest,
    student: User = Depends(get_current_user),
):
    """
    Manually triggers a real-time event broadcast to all other devices of the student.
    """
    sent = await sync_manager.broadcast_to_user(
        user_id=str(student.id),
        event=body.event,
        data=body.data,
    )
    return {"status": "broadcasted", "clients_notified": sent}


@router.get(
    "/status",
    summary="Get connected devices count",
    description="Returns how many devices/tabs the authenticated student currently has connected via WebSocket.",
    responses={401: {"description": "Token missing or invalid"}},
)
def sync_status(student: User = Depends(get_current_user)):
    """Returns connected devices count for the authenticated student."""
    return {
        "active_devices_for_user": sync_manager.get_user_connection_count(str(student.id)),
        "total_connected_system_wide": sync_manager.get_total_connections(),
    }
