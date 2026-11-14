"""Server-Sent Events (SSE) router for real-time application updates."""

import json
import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import jwt

from backend.database import get_db, User
from backend.auth import JWT_SECRET, JWT_ALGORITHM, oauth2_scheme
from backend.events import event_bus

logger = logging.getLogger("events")
router = APIRouter(prefix="/api", tags=["Events"])


def get_current_user_events(
    request: Request,
    bearer_token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Authenticate event stream using Cookie, Authorization header, or query parameter."""
    token = bearer_token
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for events stream",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject",
            )
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User inactive or not found",
        )
    return user


@router.get("/events")
async def events_stream(
    request: Request,
    current_user: User = Depends(get_current_user_events),
):
    """
    Server-Sent Events endpoint streaming real-time notifications, branding updates,
    status changes, and session invalidation signals.
    Emits a heartbeat comment every 20 seconds.
    Does not count against chat concurrency limit.
    """
    sub = await event_bus.subscribe(current_user.id, current_user.role)

    async def event_generator():
        try:
            # Send initial connected handshake event
            init_payload = {"type": "connected", "user_id": current_user.id, "role": current_user.role}
            yield f"data: {json.dumps(init_payload)}\n\n"

            while True:
                # Disconnect if client disconnected
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=20.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Periodic 20s heartbeat keeping NAT / proxy connections alive
                    yield ": heartbeat\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            await event_bus.unsubscribe(sub)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
