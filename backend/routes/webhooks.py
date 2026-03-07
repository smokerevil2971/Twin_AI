"""
Webhook routes — Phase 2.5
  POST /webhooks/gupshup/delivery — inbound Gupshup delivery receipt

Gupshup sends a callback for every status change:
  submitted → sent → delivered → read  (or failed)

Security:
  - HMAC-SHA256 signature verified against X-Gupshup-Signature header
  - In mock mode, signature check always passes (MockGupshupAdapter.verify_webhook_signature)
  - Returns 200 immediately — Gupshup retries on non-2xx

DB update:
  - Matches BroadcastRecipient by gupshup_message_id
  - Updates status, delivered_at, read_at, failed_reason
  - Updates parent Broadcast.status to "sent" once all recipients are done
"""
import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response, HTTPException
from sqlalchemy import select, update, func

from core.database import get_db
from core.config import settings
from models.models import BroadcastRecipient, Broadcast
from services.gupshup_adapter import get_gupshup_adapter

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


# ─── Status map — Gupshup event type → our internal status ───────────────────

GUPSHUP_STATUS_MAP = {
    "SENT": "sent",
    "DELIVERED": "delivered",
    "READ": "read",
    "FAILED": "failed",
    "ENQUEUED": "sent",
    "submitted": "sent",
    "delivered": "delivered",
    "read": "read",
    "failed": "failed",
}


# ─── POST /webhooks/gupshup/delivery ─────────────────────────────────────────

@router.post("/gupshup/delivery", status_code=200)
async def gupshup_delivery_webhook(
    request: Request,
    db=None,
):
    """
    Inbound Gupshup delivery status callback.

    Gupshup payload format:
    {
      "app": "TwinAI",
      "timestamp": 1234567890,
      "version": 2,
      "type": "message-event",
      "payload": {
        "id": "<gupshup_message_id>",
        "type": "enqueued|failed|sent|delivered|read",
        "destination": "+91...",
        "payload": { "type": "text" }
      }
    }

    Always returns 200 — Gupshup retries on any non-2xx response.
    """
    # ── 1. Read raw body for HMAC verification ────────────────────────────────
    raw_body = await request.body()
    signature = request.headers.get("X-Gupshup-Signature", "")

    # ── 2. Verify HMAC signature ──────────────────────────────────────────────
    adapter = get_gupshup_adapter()
    is_valid = await adapter.verify_webhook_signature(raw_body, signature)
    if not is_valid:
        logger.warning("Gupshup webhook: invalid HMAC signature — rejected")
        # Return 200 to stop retries, but log the rejection
        return Response(status_code=200, content="signature_invalid")

    # ── 3. Parse payload ──────────────────────────────────────────────────────
    try:
        data = await request.json()
    except Exception:
        logger.warning("Gupshup webhook: malformed JSON body")
        return Response(status_code=200, content="malformed_json")

    payload = data.get("payload", {})
    gupshup_message_id = payload.get("id")
    raw_status = payload.get("type", "")
    destination = payload.get("destination", "")

    if not gupshup_message_id:
        logger.info("Gupshup webhook: no message id in payload — ignoring")
        return Response(status_code=200, content="no_message_id")

    internal_status = GUPSHUP_STATUS_MAP.get(raw_status.upper(), None) or \
                      GUPSHUP_STATUS_MAP.get(raw_status, "sent")

    logger.info(
        f"Gupshup webhook: msg_id={gupshup_message_id} "
        f"status={raw_status} → {internal_status} phone={destination}"
    )

    # ── 4. Find matching recipient and update DB ──────────────────────────────
    async for db in get_db():
        result = await db.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.gupshup_message_id == gupshup_message_id
            )
        )
        recipient = result.scalar_one_or_none()

        if not recipient:
            logger.warning(f"Gupshup webhook: no recipient found for msg_id={gupshup_message_id}")
            return Response(status_code=200, content="not_found")

        # Build update values
        update_values = {"status": internal_status}
        now = utcnow()

        if internal_status == "delivered" and not recipient.delivered_at:
            update_values["delivered_at"] = now
        elif internal_status == "read" and not recipient.read_at:
            update_values["read_at"] = now
            if not recipient.delivered_at:
                update_values["delivered_at"] = now  # backfill if missed
        elif internal_status == "failed":
            error_payload = payload.get("payload", {})
            update_values["failed_reason"] = str(error_payload.get("reason", raw_status))

        await db.execute(
            update(BroadcastRecipient)
            .where(BroadcastRecipient.id == recipient.id)
            .values(**update_values)
        )

        # ── 5. Check if broadcast is fully complete ───────────────────────────
        pending_count = (
            await db.execute(
                select(func.count())
                .where(
                    BroadcastRecipient.broadcast_id == recipient.broadcast_id,
                    BroadcastRecipient.status.in_(["pending", "sent"])
                )
            )
        ).scalar_one()

        if pending_count == 0:
            # All recipients reached a terminal state (delivered/read/failed)
            await db.execute(
                update(Broadcast)
                .where(Broadcast.id == recipient.broadcast_id)
                .values(status="sent")
            )

        await db.commit()

    return Response(status_code=200, content="ok")
