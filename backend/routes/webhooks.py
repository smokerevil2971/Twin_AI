"""
Webhook routes — Phase 2.5 + 3.3
  POST /webhooks/gupshup/delivery      — inbound Gupshup delivery receipt (2.5)
  POST /webhooks/whatsapp            — inbound WhatsApp message from client (3.3)

Security:
  - HMAC-SHA256 signature verified against X-Gupshup-Signature header
  - In mock mode, signature check always passes
  - Returns 200 immediately — Gupshup retries on non-2xx
"""
import hashlib
import hmac
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Response
from sqlalchemy import select, update, func

from core.database import get_db, get_db_context
from core.config import settings
from models.models import BroadcastRecipient, Broadcast, Client
from services.gupshup_adapter import get_gupshup_adapter
from services.rag_bot import run_bot
from services.broadcast_service import create_broadcast
from services.gupshup_adapter import get_messaging_adapter
from services.media_processor import process_media, UNSUPPORTED_MSG, RATE_LIMITED_MSG
from tasks.broadcast_tasks import send_broadcast

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


# ─── POST /webhooks/whatsapp ─────────────────────────────────────────────────

@router.post("/whatsapp", status_code=200)
async def whatsapp_inbound_webhook(
    request: Request,
):
    """
    Inbound WhatsApp message.
    Supports both Twilio (form-encoded) and Gupshup (JSON) payloads.
    Always returns 200 — run_bot() is awaited inline.
    """
    from core.config import settings as app_settings

    # ── Parse inbound message (Twilio or Gupshup) ─────────────────────────
    media_url = ""
    media_type = ""
    try:
        if app_settings.messaging_provider == "twilio":
            # Twilio sends form-encoded body
            form = await request.form()
            sender_phone = str(form.get("From", "")).replace("whatsapp:", "")
            message_text = str(form.get("Body", "")).strip()
            # Media attachments (images, PDFs, voice notes)
            num_media = int(form.get("NumMedia", 0))
            media_url = str(form.get("MediaUrl0", "")).strip() if num_media > 0 else ""
            media_type = str(form.get("MediaContentType0", "")).strip() if num_media > 0 else ""
        else:
            # Gupshup sends JSON body
            # Read raw body first (kept for potential future HMAC check)
            raw_body = await request.body()
            signature = request.headers.get("X-Gupshup-Signature", "")
            if signature:
                adapter = get_gupshup_adapter()
                is_valid = await adapter.verify_webhook_signature(raw_body, signature)
                if not is_valid:
                    logger.warning("[WA WEBHOOK] Invalid HMAC — rejected")
                    return Response(status_code=200, content="signature_invalid")
            else:
                logger.warning("[WA WEBHOOK] No X-Gupshup-Signature — proceeding without HMAC check")

            body = await request.json()
            payload = body.get("payload", {})
            msg_type = body.get("type", "")

            if msg_type != "message":
                logger.info(f"[WA WEBHOOK] Ignored non-message event: {msg_type}")
                return Response(status_code=200, content="ignored")

            sender_phone = (
                payload.get("source")
                or payload.get("sender", {}).get("phone", "")
            )
            inner = payload.get("payload", {})
            message_text = inner.get("text") or inner.get("message", "")
    except Exception as exc:
        logger.warning(f"[WA WEBHOOK] Failed to parse body: {exc}")
        return Response(status_code=200, content="ok")

    if not sender_phone or not (message_text or media_url):
        logger.warning("[WA WEBHOOK] Missing phone or message — ignored")
        return Response(status_code=200, content="ignored")

    logger.info(f"[WA WEBHOOK] from={sender_phone} msg={message_text[:60]} media={bool(media_url)}")

    # ── Owner broadcast trigger ───────────────────────────────────────────
    if settings.owner_phone and sender_phone == settings.owner_phone:
        # Detect SCHEDULE: prefix — e.g. "SCHEDULE: 2026-03-14 18:00 Your message here"
        schedule_match = re.match(
            r"(?i)^schedule:\s*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s+(.+)$",
            message_text.strip(),
            re.DOTALL,
        )
        if schedule_match:
            date_str, time_str, broadcast_msg = schedule_match.groups()
            broadcast_msg = broadcast_msg.strip()
            # Parse as IST and convert to UTC for Celery
            IST = ZoneInfo("Asia/Kolkata")
            try:
                scheduled_dt_ist = datetime.strptime(
                    f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=IST)
                scheduled_dt_utc = scheduled_dt_ist.astimezone(timezone.utc)
            except ValueError:
                adapter = get_messaging_adapter()
                await adapter.send_message(
                    phone=sender_phone,
                    message="❌ Invalid format. Use:\nSCHEDULE: YYYY-MM-DD HH:MM Your message here",
                )
                return Response(status_code=200, content="ok")

            logger.info(f"[BROADCAST] Scheduling broadcast for {scheduled_dt_ist}: {broadcast_msg[:40]}")
            async with get_db_context() as db:
                try:
                    result = await create_broadcast(
                        db=db,
                        name=f"Scheduled {date_str} {time_str} — {broadcast_msg[:25]}",
                        message_template=broadcast_msg,
                        channel="whatsapp",
                        scheduled_at=scheduled_dt_utc,
                    )
                    broadcast_id = result["id"]
                    eligible_count = result["eligible_count"]
                    # Dispatch Celery task at the scheduled UTC time
                    send_broadcast.apply_async(args=[broadcast_id], eta=scheduled_dt_utc)
                    # Format confirmation in IST
                    display_time = scheduled_dt_ist.strftime("%d-%b-%Y at %-I:%M %p")
                    adapter = get_messaging_adapter()
                    preview = broadcast_msg[:60] + ("..." if len(broadcast_msg) > 60 else "")
                    await adapter.send_message(
                        phone=sender_phone,
                        message=(
                            f"🕐 Broadcast scheduled for {display_time} "
                            f"for {eligible_count} client(s).\n\"{preview}\""
                        ),
                    )
                    logger.info(f"[BROADCAST] Scheduled broadcast {broadcast_id} for {display_time}")
                except Exception as exc:
                    logger.error(f"[BROADCAST] Failed to schedule: {exc}")
                    try:
                        adapter = get_messaging_adapter()
                        await adapter.send_message(
                            phone=sender_phone,
                            message=f"❌ Scheduling failed: {str(exc)[:100]}",
                        )
                    except Exception:
                        pass
            return Response(status_code=200, content="ok")

        # ── Immediate broadcast (no SCHEDULE: prefix) ─────────────────────
        logger.info(f"[BROADCAST] Owner message — creating broadcast: {message_text[:60]}")
        async with get_db_context() as db:
            try:
                result = await create_broadcast(
                    db=db,
                    name=f"WhatsApp broadcast {message_text[:30]}",
                    message_template=message_text,
                    channel="whatsapp",
                )
                broadcast_id = result["id"]
                eligible_count = result["eligible_count"]
                send_broadcast.delay(broadcast_id)
                adapter = get_messaging_adapter()
                preview = message_text[:60] + ("..." if len(message_text) > 60 else "")
                await adapter.send_message(
                    phone=sender_phone,
                    message=f"✅ Broadcast queued for {eligible_count} client(s):\n\"{preview}\"",
                )
                logger.info(f"[BROADCAST] Queued broadcast {broadcast_id} for {eligible_count} clients")
            except Exception as exc:
                logger.error(f"[BROADCAST] Failed to create broadcast: {exc}")
                try:
                    adapter = get_messaging_adapter()
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"❌ Broadcast failed: {str(exc)[:100]}",
                    )
                except Exception:
                    pass
        return Response(status_code=200, content="ok")

    # ── Regular client — RAG bot ──────────────────────────────────────────
    # If media attached, convert to text first
    if media_url and media_type:
        logger.info(f"[MEDIA] Processing {media_type} from {sender_phone}")
        processed = await process_media(
            media_url=media_url,
            content_type=media_type,
            caption=message_text,
        )
        if processed in (UNSUPPORTED_MSG, RATE_LIMITED_MSG):
            adapter = get_messaging_adapter()
            await adapter.send_message(phone=sender_phone, message=processed)
            return Response(status_code=200, content="ok")
        message_text = processed

    if not message_text:
        return Response(status_code=200, content="ok")

    async with get_db_context() as db:
        result = await db.execute(
            select(Client).where(
                Client.phone == sender_phone,
                Client.is_deleted == False,
            )
        )
        client = result.scalar_one_or_none()
        client_id = str(client.id) if client else None

        await run_bot(
            phone=sender_phone,
            raw_message=message_text,
            client_id=client_id,
            db=db,
        )

    return Response(status_code=200, content="ok")
