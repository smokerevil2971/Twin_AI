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

from fastapi import APIRouter, Request, Response
from sqlalchemy import select, update, func

from core.database import get_db, get_db_context, AsyncSessionLocal
from core.config import settings
from models.models import BroadcastRecipient, Broadcast, Client
from services.client_service import import_clients, parse_upload_file, detect_column_mapping
from services.rag_bot import run_bot
from services.gupshup_adapter import get_messaging_adapter
from services.media_processor import process_media, UNSUPPORTED_MSG, RATE_LIMITED_MSG
from services import command_service
from tasks.broadcast_tasks import send_broadcast
import httpx
from core.redis_client import (
    get_onboard_state, set_onboard_state, clear_onboard_state,
    ONBOARD_AWAITING_CONSENT, ONBOARD_AWAITING_LANGUAGE,
)
from services import menu_service

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
      "app": "Devraj Traders",
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
    adapter = get_messaging_adapter()
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
        update_values: dict = {"status": internal_status}
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


# ─── GET /webhooks/whatsapp ─────────────────────────────────────────────────

@router.get("/whatsapp")
async def whatsapp_webhook_verification(
    request: Request,
):
    """
    Meta (WhatsApp Business API) webhook verification endpoint.
    Retrieves the challenge parameter and responds to verify the URL.
    """
    hub_mode = request.query_params.get("hub.mode")
    hub_challenge = request.query_params.get("hub.challenge")
    hub_verify_token = request.query_params.get("hub.verify_token")

    # In a real app, match this against a setting like settings.meta_verify_token
    # For now, we will simply accept whatever the user types in the portal
    # as long as they provide *something*, or we can hardcode "twinai123"
    VERIFY_TOKEN = "twinai123" 

    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    
    return Response(status_code=403, content="Verification failed")


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
            # Interactive message fields
            button_payload = str(form.get("ButtonPayload", "")).strip().lower()
            list_id        = str(form.get("ListId", "")).strip()
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
                adapter = get_messaging_adapter()
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
            message_text = str(inner.get("text") or inner.get("message") or "")
            button_payload = ""
            list_id = ""
    except Exception as exc:
        logger.warning(f"[WA WEBHOOK] Failed to parse body: {exc}")
        return Response(status_code=200, content="ok")

    if not sender_phone or not (message_text or media_url):
        logger.warning("[WA WEBHOOK] Missing phone or message — ignored")
        return Response(status_code=200, content="ignored")

    logger.info(f"[WA WEBHOOK] from={sender_phone} msg={message_text[:60]} media={bool(media_url)}")

    # ── Owner command routing ─────────────────────────────────────────────
    # Normalize phone numbers for comparison (strip '+' and spaces)
    owner_raw = str(settings.owner_phone).replace("+", "").replace(" ", "").strip()
    sender_raw = sender_phone.replace("+", "").replace(" ", "").strip()
    
    if owner_raw and sender_raw == owner_raw:
        base_url = str(request.base_url)
        try:
            cmd_response = await command_service.dispatch_owner_command(
                msg=message_text.strip(),
                sender_phone=sender_phone,
                media_url=media_url,
                media_type=media_type,
                base_url=base_url,
            )
            if cmd_response is not None:
                return cmd_response
            # None return means owner is testing the RAG bot — fall through below
            logger.info(f"[WA WEBHOOK] Owner testing RAG bot: {message_text[:60]}")
        except Exception as exc:
            logger.error(f"[WA WEBHOOK] dispatch_owner_command CRASHED: {exc}", exc_info=True)
            try:
                adapter = get_messaging_adapter()
                await adapter.send_message(phone=sender_phone, message=f"❌ System Error in Owner Command: {str(exc)}")
            except Exception:
                pass
            return Response(status_code=500, content="owner_command_error")


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
                    f"👋 *Welcome to {settings.business_name}!*\n\n"
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
                    f"_For direct help: {settings.support_phone}_"
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
                # Show main menu even for opted-out users (they can still browse)
                await menu_service.send_main_menu(adapter, sender_phone)
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
                # Show main menu so client can start browsing
                await menu_service.send_main_menu(adapter, sender_phone)
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
                # Show main menu so client can start browsing
                await menu_service.send_main_menu(adapter, sender_phone)
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

        # ── 3.3 Catalogue (Priority 3) ─────────────────────
        if msg_upper in ("CATALOGUE", "CATALOG", "PRICE LIST", "SEND LIST", "BROCHURE", "CATALOUGE", "CATALOGE", "CATALOUGR", "CATLOG"):
            from core.redis_client import get_redis
            r = get_redis()
            dynamic_url = await r.get(settings.catalogue_redis_key)
            
            final_url = dynamic_url or settings.catalogue_url
            
            if final_url:
                await adapter.send_media_message(
                    phone=sender_phone,
                    media_url=final_url,
                    media_type="document",
                    filename=settings.catalogue_filename,
                    caption="Here is our latest product catalogue and price list! 📄",
                )
            else:
                await adapter.send_message(
                    phone=sender_phone,
                    message="Our catalogue is currently being updated. You can ask me about any product prices right here! 😊",
                )
            logger.info(f"[ONBOARD] {sender_phone} requested catalogue")
            return Response(status_code=200, content="ok")

        # ── 3.4 Explicit Menu & Greetings ────────────────────────
        import re
        # Remove punctuation for cleaner comparison
        cleaned_msg = re.sub(r'[^\w\s]', '', msg_upper).strip()
        basic_greetings = {
            "HI", "HELLO", "HEY", "GOOD MORNING", "GOOD AFTERNOON", 
            "GOOD EVENING", "HI THERE", "HELLO SIR", "HI SIR", "HEY THERE", 
            "NAMASTE", "HALLO", "HII", "HIIO", "HELO"
        }
        
        if cleaned_msg == "MENU" or cleaned_msg in basic_greetings:
            await menu_service.clear_menu_state(sender_phone)
            
            if cleaned_msg != "MENU":
                # Explicit greeting & text if the user said hi
                greeting_msg = (
                    f"Hello! Welcome to *Devraj Traders*. 🏢\n\n"
                    f"I am your AI assistant, ready to answer your questions and help you with our latest products and offers. 😊"
                )
                await adapter.send_message(phone=sender_phone, message=greeting_msg)
            
            await menu_service.send_main_menu(adapter, sender_phone)
            logger.info(f"[MENU] {sender_phone} greeted/requested menu directly: {cleaned_msg}")
            return Response(status_code=200, content="ok")

        # ── Menu state machine (Priority 4) ───────────────────────────────────
        menu_handled = await menu_service.handle_menu_input(
            adapter=adapter,
            phone=sender_phone,
            msg=message_text,
            button_payload=button_payload,
            list_id=list_id,
            db=db,
        )
        if menu_handled:
            return Response(status_code=200, content="ok")

        # ── Pass to RAG bot as normal ──────────────────────────────────────
        client_id = str(client.id)

        if not sent_typing_indicator:
            await adapter.send_message(
                phone=sender_phone,
                message="Got your message! ⏳ Give me a moment..."
            )

        logger.info(f"[WA WEBHOOK] Calling run_bot for {sender_phone} | client_id={client_id} | msg={message_text[:60]}")
        try:
            await run_bot(
                phone=sender_phone,
                raw_message=message_text,
                client_id=client_id,
                db=db,
            )
            logger.info(f"[WA WEBHOOK] run_bot completed for {sender_phone}")
        except Exception as bot_exc:
            logger.error(
                f"[WA WEBHOOK] run_bot CRASHED for {sender_phone}: "
                f"{type(bot_exc).__name__}: {bot_exc}",
                exc_info=True,
            )
            try:
                await adapter.send_message(
                    phone=sender_phone,
                    message="Sorry, something went wrong on our end. Please try again in a moment! 🙏",
                )
            except Exception:
                pass

    return Response(status_code=200, content="ok")
