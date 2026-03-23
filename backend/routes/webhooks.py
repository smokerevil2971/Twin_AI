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

from core.database import get_db, get_db_context, AsyncSessionLocal
from core.config import settings
from models.models import BroadcastRecipient, Broadcast, Client
from services.client_service import import_clients
from services.gupshup_adapter import get_gupshup_adapter
from services.rag_bot import run_bot
from services.broadcast_service import create_broadcast
from services.gupshup_adapter import get_messaging_adapter
from services.media_processor import process_media, UNSUPPORTED_MSG, RATE_LIMITED_MSG
from tasks.broadcast_tasks import send_broadcast
import httpx
from services import knowledge_service
from core.redis_client import (
    get_onboard_state, set_onboard_state, clear_onboard_state,
    ONBOARD_AWAITING_CONSENT, ONBOARD_AWAITING_LANGUAGE,
)

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


def _detect_columns(df) -> dict:
    """
    TC-018 fix: Auto-detect common CSV column name variants so WhatsApp
    CSV bulk import works even when the owner's file uses 'Name'/'Mobile'
    instead of the expected 'name'/'phone' headers.
    Falls back to positional columns if no recognisable variant is found.
    """
    cols = list(df.columns)
    name_variants  = ["name", "Name", "full_name", "fullname", "customer_name", "customer"]
    phone_variants = ["phone", "Phone", "mobile", "Mobile", "number", "Number", "contact", "Contact"]
    email_variants = ["email", "Email", "e-mail", "E-mail", "mail"]

    detected_name  = next((c for c in name_variants  if c in cols), cols[0] if cols else "name")
    detected_phone = next((c for c in phone_variants if c in cols), cols[1] if len(cols) > 1 else "phone")
    detected_email = next((c for c in email_variants if c in cols), None)

    return {"name": detected_name, "phone": detected_phone, "email": detected_email}

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

    # ── Owner command routing ─────────────────────────────────────────────
    if settings.owner_phone and sender_phone == settings.owner_phone:
        msg = message_text.strip()

        # ── /help ─────────────────────────────────────────────────────────
        if msg.lower() == "/help":
            adapter = get_messaging_adapter()
            await adapter.send_message(
                phone=sender_phone,
                message=(
                    "🤖 *TwinAI Owner Bot — Help Guide*\n\n"

                    "━━━━━━━━━━━━━━━━━━\n"
                    "📢 *BROADCAST* — Send to all clients now\n"
                    "Format: `BROADCAST: <your message>`\n"
                    "Example: _BROADCAST: 🎉 Flash sale today! 20% off all solar panels._\n\n"

                    "━━━━━━━━━━━━━━━━━━\n"
                    "🕐 *SCHEDULE* — Send at a specific date & time (IST)\n"
                    "Format: `SCHEDULE: YYYY-MM-DD HH:MM <your message>`\n"
                    "Example: _SCHEDULE: 2026-03-25 10:00 New inverter stock is live!_\n\n"

                    "━━━━━━━━━━━━━━━━━━\n"
                    "👤 *ADD CLIENT* — Add one client by phone\n"
                    "Format: `ADD: <phone>, <Name>`\n"
                    "Example: _ADD: 9876543210, Ravi Kumar_\n\n"

                    "━━━━━━━━━━━━━━━━━━\n"
                    "🗑️ *REMOVE CLIENT* — Remove client by phone\n"
                    "Format: `REMOVE: <phone>`\n"
                    "Example: _REMOVE: 9876543210_\n\n"

                    "━━━━━━━━━━━━━━━━━━\n"
                    "📋 *BULK IMPORT* — Send a CSV or Excel file\n"
                    "Required columns: `name`, `phone`\n"
                    "Optional column: `email`\n"
                    "All imported clients will be opted-in automatically.\n\n"

                    "━━━━━━━━━━━━━━━━━━\n"
                    "📚 *ADD TO KNOWLEDGE BASE* — Send a PDF or Word doc\n"
                    "Caption = category: `products` / `offers` / `documents`\n"
                    "Supported: PDF, DOCX, DOC, TXT\n\n"

                    "━━━━━━━━━━━━━━━━━━\n"
                    "📊 *COMMANDS*\n"
                    "• `/status` — Platform stats\n"
                    "• `/clients` — Opted-in count\n"
                    "• `/help` — This guide\n\n"

                    "━━━━━━━━━━━━━━━━━━\n"
                    "🧪 *TEST THE BOT*\n"
                    "Send any message without a prefix to test the RAG bot.\n"
                    "Example: _what is the price of solar inverter?_"
                ),
            )
            return Response(status_code=200, content="ok")

        # ── /status ───────────────────────────────────────────────────────
        if msg.lower() == "/status":
            async with get_db_context() as db:
                total_clients = (await db.execute(
                    select(func.count()).where(Client.opted_in == True, Client.is_deleted == False)
                )).scalar_one()
                last_broadcast = (await db.execute(
                    select(Broadcast.created_at).order_by(Broadcast.created_at.desc()).limit(1)
                )).scalar_one_or_none()
                lb_str = last_broadcast.strftime("%d-%b %H:%M UTC") if last_broadcast else "None yet"
            adapter = get_messaging_adapter()
            await adapter.send_message(
                phone=sender_phone,
                message=(
                    f"📊 *TwinAI Status*\n\n"
                    f"👥 Opted-in clients: *{total_clients}*\n"
                    f"📤 Last broadcast: *{lb_str}*\n\n"
                    f"Type `/help` to see all commands & formats."
                ),
            )
            return Response(status_code=200, content="ok")

        # ── /clients ──────────────────────────────────────────────────────
        if msg.lower() == "/clients":
            async with get_db_context() as db:
                count = (await db.execute(
                    select(func.count()).where(Client.opted_in == True, Client.is_deleted == False)
                )).scalar_one()
            adapter = get_messaging_adapter()
            await adapter.send_message(phone=sender_phone, message=f"👥 Opted-in clients: {count}")
            return Response(status_code=200, content="ok")

        # ── SCHEDULE: <date> <time> <message> ─────────────────────────────
        schedule_match = re.match(
            r"(?i)^schedule:\s*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s+(.+)$",
            msg,
            re.DOTALL,
        )
        if schedule_match:
            date_str, time_str, broadcast_msg = schedule_match.groups()
            broadcast_msg = broadcast_msg.strip()
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

            logger.info(f"[BROADCAST] Scheduling for {scheduled_dt_ist}: {broadcast_msg[:40]}")
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
                    send_broadcast.apply_async(args=[broadcast_id], eta=scheduled_dt_utc)
                    display_time = scheduled_dt_ist.strftime("%d-%b-%Y at %I:%M %p")
                    adapter = get_messaging_adapter()
                    preview = broadcast_msg[:60] + ("..." if len(broadcast_msg) > 60 else "")
                    await adapter.send_message(
                        phone=sender_phone,
                        message=(
                            f"🕐 Broadcast scheduled for {display_time} "
                            f"for {eligible_count} client(s).\n\"{preview}\""
                        ),
                    )
                    logger.info(f"[BROADCAST] Scheduled {broadcast_id} for {display_time}")
                except Exception as exc:
                    logger.error(f"[BROADCAST] Failed to schedule: {exc}")
                    try:
                        adapter = get_messaging_adapter()
                        await adapter.send_message(phone=sender_phone, message=f"❌ Scheduling failed: {str(exc)[:100]}")
                    except Exception:
                        pass
            return Response(status_code=200, content="ok")

        # ── BROADCAST with IMAGE/PDF — owner sends media + caption starts with "BROADCAST:" ──
        # Detects: owner sends an image or document with caption "BROADCAST: <message>"
        is_broadcast_media = (
            media_url
            and message_text.upper().startswith("BROADCAST:")
        )
        if is_broadcast_media:
            broadcast_caption = message_text[len("BROADCAST:"):].strip()
            # Determine media_type from Content-Type header
            if "pdf" in media_type.lower():
                bc_media_type = "document"
                bc_filename = "product_catalogue.pdf"
                file_ext = ".pdf"
            else:
                bc_media_type = "image"
                bc_filename = "image.jpg"
                file_ext = ".jpg"

            # ── Download the media from Twilio and re-cache it publicly ────────
            # Twilio stores inbound media behind auth — we must download + re-serve
            # via our public ngrok URL so the outbound MediaUrl is accessible.
            public_media_url = None
            try:
                import httpx, uuid as _uuid
                uploads_dir = "/tmp/twinai_media"
                import os as _os
                _os.makedirs(uploads_dir, exist_ok=True)
                file_name = f"{_uuid.uuid4().hex}{file_ext}"
                save_path = f"{uploads_dir}/{file_name}"

                async with httpx.AsyncClient(timeout=15.0) as hclient:
                    dl = await hclient.get(
                        media_url,
                        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                        follow_redirects=True,
                    )
                    dl.raise_for_status()
                    with open(save_path, "wb") as f:
                        f.write(dl.content)

                # Build public ngrok URL — base URL is detected from the inbound request
                base_url = str(request.base_url).rstrip("/")
                public_media_url = f"{base_url}/media/{file_name}"
                logger.info(f"[BROADCAST] Cached media → {save_path} | public URL: {public_media_url}")
            except Exception as dl_exc:
                logger.error(f"[BROADCAST] Failed to download/cache Twilio media: {dl_exc}")
                # Fallback: try with the raw Twilio URL anyway (may not work in sandbox)
                public_media_url = media_url

            logger.info(
                f"[BROADCAST] Owner triggered media broadcast: "
                f"type={bc_media_type} url={public_media_url[:60]} caption={broadcast_caption[:40]}"
            )
            async with get_db_context() as db:
                try:
                    result = await create_broadcast(
                        db=db,
                        name=f"Media broadcast — {broadcast_caption[:30]}",
                        message_template=broadcast_caption,
                        channel="whatsapp",
                        media_url=public_media_url,
                        media_type=bc_media_type,
                        media_filename=bc_filename,
                    )
                    broadcast_id = result["id"]
                    eligible_count = result["eligible_count"]
                    send_broadcast.delay(broadcast_id)
                    adapter = get_messaging_adapter()
                    await adapter.send_message(
                        phone=sender_phone,
                        message=(
                            f"✅ Media broadcast queued for *{eligible_count}* client(s)!\n"
                            f"📎 Type: {bc_media_type}\n"
                            f"💬 Caption: \"{broadcast_caption[:60]}\""
                        ),
                    )
                    logger.info(f"[BROADCAST] Media broadcast {broadcast_id} queued for {eligible_count} clients")
                except Exception as exc:
                    logger.error(f"[BROADCAST] Media broadcast failed: {exc}")
                    try:
                        adapter = get_messaging_adapter()
                        await adapter.send_message(
                            phone=sender_phone,
                            message=f"❌ Media broadcast failed: {str(exc)[:100]}"
                        )
                    except Exception:
                        pass
            return Response(status_code=200, content="ok")


        # ── BROADCAST: <message> — explicit immediate text broadcast ────────────
        broadcast_match = re.match(r"(?i)^broadcast:\s*(.+)$", msg, re.DOTALL)
        if broadcast_match:
            broadcast_msg = broadcast_match.group(1).strip()
            logger.info(f"[BROADCAST] Owner triggered broadcast: {broadcast_msg[:60]}")
            async with get_db_context() as db:
                try:
                    result = await create_broadcast(
                        db=db,
                        name=f"WhatsApp broadcast {broadcast_msg[:30]}",
                        message_template=broadcast_msg,
                        channel="whatsapp",
                    )
                    broadcast_id = result["id"]
                    eligible_count = result["eligible_count"]
                    send_broadcast.delay(broadcast_id)
                    adapter = get_messaging_adapter()
                    preview = broadcast_msg[:60] + ("..." if len(broadcast_msg) > 60 else "")
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"✅ Broadcast queued for {eligible_count} client(s):\n\"{preview}\"",
                    )
                    logger.info(f"[BROADCAST] Queued {broadcast_id} for {eligible_count} clients")
                except Exception as exc:
                    logger.error(f"[BROADCAST] Failed to create broadcast: {exc}")
                    try:
                        adapter = get_messaging_adapter()
                        await adapter.send_message(phone=sender_phone, message=f"❌ Broadcast failed: {str(exc)[:100]}")
                    except Exception:
                        pass
            return Response(status_code=200, content="ok")


        # ── ADD: +91XXXXXXXXXX, Name ─────────────────────────────────────
        add_match = re.match(r"(?i)^add:\s*(\+?\d[\d\s\-]{7,15})\s*,\s*(.+)$", msg)
        if add_match:
            raw_phone, name = add_match.group(1).strip(), add_match.group(2).strip()
            # Normalise phone: 10-digit Indian → +91
            digits = re.sub(r"\D", "", raw_phone)
            if len(digits) == 10:
                phone = f"+91{digits}"
            elif digits.startswith("91") and len(digits) == 12:
                phone = f"+{digits}"
            else:
                phone = f"+{digits}" if not raw_phone.startswith("+") else raw_phone
            adapter = get_messaging_adapter()
            try:
                async with AsyncSessionLocal() as db:
                    existing = (await db.execute(
                        select(Client).where(Client.phone == phone, Client.is_deleted == False)
                    )).scalar_one_or_none()
                    if existing:
                        await adapter.send_message(
                            phone=sender_phone,
                            message=f"⚠️ Client already exists:\n👤 {existing.name} ({phone})",
                        )
                    else:
                        client = Client(name=name, phone=phone, opted_in=True)
                        db.add(client)
                        await db.commit()
                        await adapter.send_message(
                            phone=sender_phone,
                            message=f"✅ Client added & opted-in:\n👤 *{name}*\n📞 {phone}",
                        )
                        logger.info(f"[OWNER] Added client: {name} ({phone})")
            except Exception as exc:
                logger.error(f"[OWNER] ADD: failed: {exc}")
                await adapter.send_message(phone=sender_phone, message=f"❌ Failed to add client: {str(exc)[:120]}")
            return Response(status_code=200, content="ok")

        # ── REMOVE: +91XXXXXXXXXX ──────────────────────────────────────────
        remove_match = re.match(r"(?i)^remove:\s*(\+?\d[\d\s\-]{7,15})$", msg)
        if remove_match:
            raw_phone = remove_match.group(1).strip()
            digits = re.sub(r"\D", "", raw_phone)
            if len(digits) == 10:
                phone = f"+91{digits}"
            elif digits.startswith("91") and len(digits) == 12:
                phone = f"+{digits}"
            else:
                phone = f"+{digits}" if not raw_phone.startswith("+") else raw_phone
            adapter = get_messaging_adapter()
            try:
                async with AsyncSessionLocal() as db:
                    client = (await db.execute(
                        select(Client).where(Client.phone == phone, Client.is_deleted == False)
                    )).scalar_one_or_none()
                    if not client:
                        await adapter.send_message(
                            phone=sender_phone,
                            message=f"⚠️ No active client found for {phone}",
                        )
                    else:
                        name = client.name
                        client.is_deleted = True
                        client.opted_in = False
                        await db.commit()
                        await adapter.send_message(
                            phone=sender_phone,
                            message=f"🗑️ Client removed:\n👤 *{name}* ({phone})",
                        )
                        logger.info(f"[OWNER] Removed client: {name} ({phone})")
            except Exception as exc:
                logger.error(f"[OWNER] REMOVE: failed: {exc}")
                await adapter.send_message(phone=sender_phone, message=f"❌ Failed to remove client: {str(exc)[:120]}")
            return Response(status_code=200, content="ok")

        # ── Owner sends CSV/XLSX → bulk import clients ─────────────────────
        CLIENT_SHEET_TYPES = {
            "text/csv",
            "application/csv",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        if media_url and media_type and media_type.lower() in CLIENT_SHEET_TYPES:
            logger.info(f"[OWNER] Client spreadsheet received ({media_type})")
            adapter = get_messaging_adapter()
            try:
                async with httpx.AsyncClient(timeout=60, follow_redirects=True) as hclient:
                    if settings.messaging_provider == "twilio" and settings.twilio_account_sid:
                        resp = await hclient.get(
                            media_url,
                            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                        )
                    else:
                        resp = await hclient.get(media_url)
                    resp.raise_for_status()
                    file_bytes = resp.content

                ext = ".xlsx" if "spreadsheetml" in media_type.lower() else ".csv"
                filename = f"clients_import{ext}"

                async with AsyncSessionLocal() as db:
                    summary = await import_clients(
                        db=db,
                        content=file_bytes,
                        filename=filename,
                        column_mapping=_detect_columns(df),
                        set_opted_in=True,
                    )

                imported = summary.get("imported", 0)
                skipped = summary.get("skipped", 0)
                total = summary.get("total_rows", 0)
                await adapter.send_message(
                    phone=sender_phone,
                    message=(
                        f"✅ *Client import complete!*\n"
                        f"📊 Total rows: *{total}*\n"
                        f"✅ Imported: *{imported}*\n"
                        f"⏭️ Skipped (duplicates/invalid): *{skipped}*\n\n"
                        f"_All imported clients are opted-in._\n"
                        f"CSV column names expected: `name`, `phone`, `email` (optional)"
                    ),
                )
                logger.info(f"[OWNER] Client import: {imported} imported, {skipped} skipped")
            except Exception as exc:
                logger.error(f"[OWNER] Client import failed: {exc}")
                try:
                    await adapter.send_message(phone=sender_phone, message=f"❌ Import failed: {str(exc)[:150]}")
                except Exception:
                    pass
            return Response(status_code=200, content="ok")

        # ── Owner sends a document → ingest into Knowledge Base ───────────
        INGESTABLE_TYPES = {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
            "text/plain",
            "text/markdown",
        }
        if media_url and media_type and media_type.lower() in INGESTABLE_TYPES:
            logger.info(f"[OWNER] Document received: {media_type} — ingesting into KB")
            adapter = get_messaging_adapter()
            try:
                # Download file from Twilio (requires Basic Auth)
                async with httpx.AsyncClient(timeout=60, follow_redirects=True) as hclient:
                    if settings.messaging_provider == "twilio" and settings.twilio_account_sid:
                        resp = await hclient.get(
                            media_url,
                            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                        )
                    else:
                        resp = await hclient.get(media_url)
                    resp.raise_for_status()
                    file_bytes = resp.content

                # Infer filename from content-type
                ext_map = {
                    "application/pdf": ".pdf",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                    "application/msword": ".doc",
                    "text/plain": ".txt",
                    "text/markdown": ".md",
                }
                ext = ext_map.get(media_type.lower(), ".bin")
                filename = f"owner_upload_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}{ext}"

                # Determine category from caption (default: "documents")
                valid_categories = {"products", "offers", "documents", "broadcasts"}
                caption_lower = (message_text or "").strip().lower()
                category = caption_lower if caption_lower in valid_categories else "documents"

                # Ingest into ChromaDB + Postgres
                async with AsyncSessionLocal() as db:
                    result = await knowledge_service.ingest_document(
                        db=db,
                        file_bytes=file_bytes,
                        filename=filename,
                        category=category,
                        valid_from=None,
                        valid_until=None,
                    )

                chunks = result.get("chunks_indexed", "?")
                await adapter.send_message(
                    phone=sender_phone,
                    message=(
                        f"✅ *Document ingested!*\n"
                        f"📄 File: {filename}\n"
                        f"📂 Category: *{category}*\n"
                        f"🧩 Chunks indexed: *{chunks}*\n\n"
                        f"_Tip: Send caption as `products`, `offers`, or `documents` to set category._"
                    ),
                )
                logger.info(f"[OWNER] KB ingestion complete: {filename}, {chunks} chunks, category={category}")
            except Exception as exc:
                logger.error(f"[OWNER] KB ingestion failed: {exc}")
                try:
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"❌ Failed to ingest document: {str(exc)[:150]}",
                    )
                except Exception:
                    pass
            return Response(status_code=200, content="ok")

        # ── Everything else → owner tests the RAG bot ─────────────────────
        logger.info(f"[OWNER] Routing to RAG bot for testing: {msg[:60]}")
        # Fall through to the regular RAG bot section below


    # ── Regular client — Onboarding + RAG bot ────────────────────────────
    # If media attached, convert to text first
    sent_typing_indicator = False
    if media_url and media_type:
        logger.info(f"[MEDIA] Processing {media_type} from {sender_phone}")
        adapter = get_messaging_adapter()
        if media_type.startswith("image/"):
            await adapter.send_message(phone=sender_phone, message="📸 Thanks for sending the image! Let me analyse it...")
            sent_typing_indicator = True
            
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

    adapter = get_messaging_adapter()

    async with get_db_context() as db:
        # Get client regardless of deleted status to avoid UniqueConstraint(phone) errors
        result = await db.execute(
            select(Client).where(Client.phone == sender_phone)
        )
        client = result.scalar_one_or_none()

        # ── 1.1 First contact — brand new (or returning deleted) client ───
        if client is None or client.is_deleted:
            if client is None:
                # Completely new client
                client = Client(
                    name=sender_phone,
                    phone=sender_phone,
                    opted_in=False,
                    language="en",
                )
                db.add(client)
            else:
                # Returning deleted client — un-delete them and reset preferences
                client.is_deleted = False
                client.opted_in = False

            await db.commit()
            await db.refresh(client)
            logger.info(f"[ONBOARD] Client onboard started: {sender_phone}")

            # Send warm welcome + opt-in consent question
            await adapter.send_message(
                phone=sender_phone,
                message=(
                    "👋 *Welcome to Devraj Traders!*\n\n"
                    "I'm your AI assistant. I can help you with:\n"
                    "• Product prices & availability 🏠\n"
                    "• Ongoing offers & discounts 🎁\n"
                    "• Order enquiries 📦\n"
                    "• Any product questions!\n\n"
                    "Just ask me anything in *English or हिंदी*. 😊\n\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "📢 Would you like to receive product updates & offers from us?\n\n"
                    "Reply *YES* to subscribe 🔔\n"
                    "Reply *NO* to skip (you can still chat with me anytime)\n\n"
                    "_For direct help: +91-9075805070_"
                ),
            )
            await set_onboard_state(sender_phone, ONBOARD_AWAITING_CONSENT)
            return Response(status_code=200, content="ok")

        # ── 1.2 & 1.3 Onboarding state machine ───────────────────────────
        onboard_state = await get_onboard_state(sender_phone)

        if onboard_state == ONBOARD_AWAITING_CONSENT:
            reply = message_text.strip().upper()
            if reply in ("YES", "Y", "HAN", "हाँ", "हां", "HA"):
                client.opted_in = True
                await db.commit()
                logger.info(f"[ONBOARD] {sender_phone} opted IN")
                await set_onboard_state(sender_phone, ONBOARD_AWAITING_LANGUAGE)
                await adapter.send_message(
                    phone=sender_phone,
                    message=(
                        "✅ *You're subscribed!* We'll keep you updated with the latest offers. 🎉\n\n"
                        "━━━━━━━━━━━━━━━━━━\n"
                        "🌐 *One last thing — what language do you prefer?*\n\n"
                        "Reply *EN* for English 🇬🇧\n"
                        "Reply *HINDI* for हिंदी 🇮🇳"
                    ),
                )
            elif reply in ("NO", "N", "NAI", "NAHI", "नहीं", "नही"):
                client.opted_in = False
                await db.commit()
                logger.info(f"[ONBOARD] {sender_phone} opted OUT")
                await clear_onboard_state(sender_phone)
                await adapter.send_message(
                    phone=sender_phone,
                    message=(
                        "👍 No problem! You won't receive broadcast messages.\n"
                        "You can still ask me anything about our products anytime.\n\n"
                        "_To subscribe later, just say *START*._"
                    ),
                )
            else:
                # Unrecognised reply — nudge them
                await adapter.send_message(
                    phone=sender_phone,
                    message="Please reply *YES* to subscribe to updates or *NO* to skip. 🙏",
                )
            return Response(status_code=200, content="ok")

        if onboard_state == ONBOARD_AWAITING_LANGUAGE:
            reply = message_text.strip().upper()
            if reply in ("HINDI", "HINDI", "HI", "हिंदी", "हिंदी"):
                client.language = "hi"
                await db.commit()
                await clear_onboard_state(sender_phone)
                logger.info(f"[ONBOARD] {sender_phone} language set to Hindi")
                await adapter.send_message(
                    phone=sender_phone,
                    message=(
                        "बढ़िया! 🎉 मैं अब हिंदी में जवाब दूंगा।\n\n"
                        "अब आप मुझसे हमारे किसी भी उत्पाद के बारे में पूछ सकते हैं! 😊"
                    ),
                )
            elif reply in ("EN", "ENGLISH", "ENG"):
                client.language = "en"
                await db.commit()
                await clear_onboard_state(sender_phone)
                logger.info(f"[ONBOARD] {sender_phone} language set to English")
                await adapter.send_message(
                    phone=sender_phone,
                    message=(
                        "Great! 🎉 I'll respond in English.\n\n"
                        "Feel free to ask me anything about our products! 😊"
                    ),
                )
            else:
                await adapter.send_message(
                    phone=sender_phone,
                    message="Please reply *EN* for English or *HINDI* for हिंदी. 🌐",
                )
            return Response(status_code=200, content="ok")

        # ── Handle STOP / START self-service opt commands (1.2 extra) ─────
        msg_upper = message_text.strip().upper()
        if msg_upper in ("STOP", "UNSUBSCRIBE", "OPT OUT", "OPTOUT"):
            client.opted_in = False
            await db.commit()
            await adapter.send_message(
                phone=sender_phone,
                message=(
                    "✅ You've been unsubscribed from broadcast messages.\n"
                    "You can still chat with me anytime! 😊\n\n"
                    "_Reply *START* anytime to re-subscribe._"
                ),
            )
            logger.info(f"[ONBOARD] {sender_phone} self-unsubscribed")
            return Response(status_code=200, content="ok")

        if msg_upper in ("START", "SUBSCRIBE", "OPT IN", "OPTIN"):
            client.opted_in = True
            await db.commit()
            await adapter.send_message(
                phone=sender_phone,
                message="✅ You're re-subscribed! You'll now receive our latest offers & updates. 🔔",
            )
            logger.info(f"[ONBOARD] {sender_phone} self-re-subscribed")
            return Response(status_code=200, content="ok")

        # ── 3.1 & 3.3 Quick Menu & Catalogue (Priority 3) ─────────────────────
        if msg_upper in ("MENU", "/MENU", "PRODUCTS", "CATEGORIES"):
            menu_text = (
                "📦 *Our Product Categories*\n\n"
                "1️⃣ PVC Wall Panels\n"
                "2️⃣ Wall Putty & Paints\n"
                "3️⃣ Waterproofing Solutions\n"
                "4️⃣ Flooring\n\n"
                "Reply with the product you want to know more about, or ask any specific question! 😊"
            )
            await adapter.send_message(phone=sender_phone, message=menu_text)
            logger.info(f"[ONBOARD] {sender_phone} requested menu")
            return Response(status_code=200, content="ok")
            
        if msg_upper in ("CATALOGUE", "CATALOG", "PRICE LIST", "SEND LIST", "BROCHURE"):
            from core.config import settings
            if settings.catalogue_url:
                await adapter.send_media_message(
                    phone=sender_phone,
                    media_url=settings.catalogue_url,
                    media_type="document",
                    filename="Devraj_Traders_Catalogue.pdf",
                    caption="Here is our latest product catalogue and price list! 📄",
                )
            else:
                await adapter.send_message(
                    phone=sender_phone,
                    message="Our catalogue is currently being updated. You can ask me about any product prices right here! 😊",
                )
            logger.info(f"[ONBOARD] {sender_phone} requested catalogue")
            return Response(status_code=200, content="ok")

        # ── Pass to RAG bot as normal ──────────────────────────────────────
        client_id = str(client.id)
        
        if not sent_typing_indicator:
            await adapter.send_message(
                phone=sender_phone,
                message="Got your message! ⏳ Give me a moment..."
            )
            
        await run_bot(
            phone=sender_phone,
            raw_message=message_text,
            client_id=client_id,
            db=db,
        )

    return Response(status_code=200, content="ok")
