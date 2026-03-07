"""
Broadcast routes — Phase 2.2
  POST   /broadcasts            — create + queue send task
  GET    /broadcasts            — paginated list
  GET    /broadcasts/{id}       — detail with per-client stats
  GET    /broadcasts/{id}/export — CSV delivery report
  GET    /broadcasts/{id}/stream — SSE real-time delivery events (Phase 2.3)
"""
import uuid
import asyncio
import json
from datetime import datetime, timezone
from typing import Optional, AsyncGenerator

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from core.database import get_db
from core.security import get_tenant_id
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


# ─── POST /broadcasts ─────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_broadcast(
    body: CreateBroadcastRequest,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db=Depends(get_db),
):
    """
    Create a broadcast and queue the Celery send task.
    - Only opted-in clients are eligible
    - Enforces 24-hour per-client send window
    - Personalises message ({{name}}, {{1}}) per recipient
    - Pass scheduled_at to delay sending; omit for immediate send
    """
    result = await broadcast_service.create_broadcast(
        db=db,
        tenant_id=tenant_id,
        name=body.name,
        message_template=body.message_template,
        channel=body.channel,
        language=body.language,
        scheduled_at=body.scheduled_at,
        target_client_ids=body.target_client_ids,
    )

    # Queue Celery task (scheduled or immediate)
    broadcast_id = result["id"]
    if body.scheduled_at and body.scheduled_at > datetime.now(timezone.utc):
        send_broadcast.apply_async(
            args=[broadcast_id],
            eta=body.scheduled_at,
        )
    else:
        send_broadcast.delay(broadcast_id)

    return success_response(result, status_code=201)


# ─── GET /broadcasts ──────────────────────────────────────────────────────────

@router.get("")
async def list_broadcasts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db=Depends(get_db),
):
    """Paginated list of all broadcasts for this tenant."""
    result = await broadcast_service.list_broadcasts(db, tenant_id, page, page_size)
    return success_response(result)


# ─── GET /broadcasts/{id} ─────────────────────────────────────────────────────

@router.get("/{broadcast_id}")
async def get_broadcast(
    broadcast_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db=Depends(get_db),
):
    """Full broadcast detail with per-client delivery stats."""
    result = await broadcast_service.get_broadcast_detail(db, tenant_id, broadcast_id)
    return success_response(result)


# ─── GET /broadcasts/{id}/export ─────────────────────────────────────────────

@router.get("/{broadcast_id}/export")
async def export_broadcast(
    broadcast_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db=Depends(get_db),
):
    """Download per-client delivery report as CSV."""
    csv_content = await broadcast_service.export_broadcast_csv(db, tenant_id, broadcast_id)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=broadcast_{broadcast_id}_report.csv"
        }
    )


# ─── GET /broadcasts/{id}/stream  (SSE — Phase 2.3) ──────────────────────────

@router.get("/{broadcast_id}/stream")
async def stream_broadcast_status(
    broadcast_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db=Depends(get_db),
):
    """
    Server-Sent Events stream — emits delivery status updates in real-time.
    Frontend subscribes on mount; events fire as webhook callbacks update DB.
    Falls back to 10-second polling if SSE connection drops.
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        last_counts = {}
        while True:
            try:
                # Fetch current per-status counts
                rows = (
                    await db.execute(
                        select(
                            BroadcastRecipient.status,
                        )
                        .where(BroadcastRecipient.broadcast_id == broadcast_id)
                    )
                ).scalars().all()

                counts = {"pending": 0, "sent": 0, "delivered": 0, "read": 0, "failed": 0}
                for status in rows:
                    counts[status] = counts.get(status, 0) + 1

                # Only emit if something changed
                if counts != last_counts:
                    last_counts = counts
                    data = json.dumps({
                        "broadcast_id": str(broadcast_id),
                        "stats": counts,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    yield f"data: {data}\n\n"

                # Check if broadcast is complete — close stream
                broadcast = await db.get(Broadcast, broadcast_id)
                if broadcast and broadcast.status in ("sent", "failed"):
                    yield f"data: {json.dumps({'event': 'complete', 'stats': counts})}\n\n"
                    break

            except asyncio.CancelledError:
                break
            except Exception:
                break

            await asyncio.sleep(3)  # Poll DB every 3 seconds

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
