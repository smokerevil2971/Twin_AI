"""
Broadcast routes — Phase 2.2
  POST   /broadcasts            — create + queue send task
  GET    /broadcasts            — paginated list
  GET    /broadcasts/{id}       — detail with per-client stats
  GET    /broadcasts/{id}/export — CSV delivery report
  GET    /broadcasts/{id}/stream — SSE real-time delivery events (Phase 2.3)
"""
import uuid
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import select

from core.database import get_db
from core.security import get_current_user
from core.responses import success_response, error_response
from models.models import BroadcastRecipient, Broadcast
from services import broadcast_service
from tasks.broadcast_tasks import send_broadcast

router = APIRouter(prefix="/broadcasts", tags=["Broadcasts"])


# ─── Request schemas ──────────────────────────────────────────────────────────

class CreateBroadcastRequest(BaseModel):
    name: str
    message_template: str
    channel: str = "whatsapp"
    language: str = "en"
    scheduled_at: Optional[datetime] = None
    target_client_ids: Optional[list[uuid.UUID]] = None
    # ─── Media fields (optional) ──────────────────────────────────────────────
    media_url: Optional[str] = None          # publicly accessible URL (image or PDF)
    media_type: Optional[str] = None         # 'image' | 'document'
    media_filename: Optional[str] = None     # friendly filename shown on document


# ─── POST /broadcasts ─────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_broadcast(
    body: CreateBroadcastRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Create a broadcast and queue the Celery send task.
    - Only opted-in clients are eligible
    - Enforces 24-hour per-client send window
    - Personalises message ({{name}}, {{1}}) per recipient
    - Pass scheduled_at to delay sending; omit for immediate send
    """
    # Validate media_type if provided
    if body.media_url and body.media_type not in (None, "image", "document"):
        from fastapi import HTTPException as _HTTPException
        raise _HTTPException(
            status_code=422,
            detail="media_type must be 'image' or 'document' when media_url is provided."
        )

    result = await broadcast_service.create_broadcast(
        db=db,
        name=body.name,
        message_template=body.message_template,
        channel=body.channel,
        language=body.language,
        scheduled_at=body.scheduled_at,
        target_client_ids=body.target_client_ids,
        media_url=body.media_url,
        media_type=body.media_type,
        media_filename=body.media_filename,
    )

    # TC-015 fix: Validate scheduled_at before queuing.
    # Previously, a past timestamp silently fired immediately with no user warning.
    broadcast_id = result["id"]
    if body.scheduled_at:
        # Normalise to UTC-aware for comparison
        sched = body.scheduled_at
        if sched.tzinfo is None:
            from datetime import timezone as _tz
            sched = sched.replace(tzinfo=_tz.utc)

        now = datetime.now(timezone.utc)
        min_lead_seconds = 5 * 60  # 5-minute minimum lead time

        if sched <= now:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=422,
                detail=(
                    f"scheduled_at must be in the future. "
                    f"Provided: {body.scheduled_at.isoformat()}, "
                    f"Server UTC now: {now.isoformat()}. "
                    f"Please pick a future time."
                ),
            )
        if (sched - now).total_seconds() < min_lead_seconds:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=422,
                detail=(
                    "scheduled_at must be at least 5 minutes in the future "
                    "to allow time for review before sending."
                ),
            )

        send_broadcast.apply_async(args=[broadcast_id], eta=sched)
    else:
        send_broadcast.delay(broadcast_id)

    return success_response(result, status_code=201)



# ─── GET /broadcasts ──────────────────────────────────────────────────────────

@router.get("")
async def list_broadcasts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Paginated list of all broadcasts."""
    result = await broadcast_service.list_broadcasts(db, page, page_size)
    return success_response(result)


# ─── GET /broadcasts/{id} ─────────────────────────────────────────────────────

@router.get("/{broadcast_id}")
async def get_broadcast(
    broadcast_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Full broadcast detail with per-client delivery stats."""
    result = await broadcast_service.get_broadcast_detail(db, broadcast_id)
    return success_response(result)


# ─── GET /broadcasts/{id}/export ─────────────────────────────────────────────

@router.get("/{broadcast_id}/export")
async def export_broadcast(
    broadcast_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Download per-client delivery report as CSV."""
    csv_content = await broadcast_service.export_broadcast_csv(db, broadcast_id)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=broadcast_{broadcast_id}_report.csv"
        }
    )
