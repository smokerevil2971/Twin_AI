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
from services.messaging_adapter import get_messaging_adapter
from services.media_processor import process_media, UNSUPPORTED_MSG, RATE_LIMITED_MSG
from services import command_service
from tasks.broadcast_tasks import send_broadcast
import httpx
from core.redis_client import (
    get_onboard_state, set_onboard_state, clear_onboard_state,
    ONBOARD_AWAITING_CONSENT, ONBOARD_AWAITING_LANGUAGE, ONBOARD_AWAITING_NAME,
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



@router.get("/whatsapp", status_code=200)
async def whatsapp_verify(request: Request):
    """
    Meta webhook verification handshake.
    When you register your webhook URL in the Meta developer dashboard,
    Meta sends a GET with hub.mode, hub.verify_token, hub.challenge.
    We must echo back hub.challenge if the token matches.
    """
    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")

    if mode == "subscribe" and token == settings.meta_webhook_verify_token:
        logger.info("[META] Webhook verification successful")
        return Response(content=challenge, media_type="text/plain")

    logger.warning(f"[META] Webhook verification failed: mode={mode} token_match={token == settings.meta_webhook_verify_token}")
    return Response(status_code=403, content="forbidden")


@router.post("/gupshup/delivery", status_code=200)
async def gupshup_delivery_webhook(
    request: Request,
    db=None,
):
    """
    Legacy Gupshup delivery status callback (kept for reference).
    For Meta, delivery receipts arrive via POST /webhooks/whatsapp.
    """
    raw_body = await request.body()
    try:
        data = await request.json()
    except Exception:
        return Response(status_code=200, content="malformed_json")

    payload = data.get("payload", {})
    provider_message_id = payload.get("id")
    raw_status = payload.get("type", "")
    destination = payload.get("destination", "")

    if not provider_message_id:
        return Response(status_code=200, content="no_message_id")

    internal_status = GUPSHUP_STATUS_MAP.get(raw_status.upper(), None) or \
                      GUPSHUP_STATUS_MAP.get(raw_status, "sent")

    logger.info(
        f"[GUPSHUP DELIVERY] msg_id={provider_message_id} "
        f"status={raw_status} → {internal_status} phone={destination}"
    )

    await _update_recipient_status(provider_message_id, internal_status, payload)
    return Response(status_code=200, content="ok")


async def _update_recipient_status(
    provider_message_id: str,
    internal_status: str,
    payload: dict,
    timestamp: int = 0,
) -> None:
    """Shared helper — update BroadcastRecipient status from any provider's delivery receipt."""
    async for db in get_db():
        result = await db.execute(
            select(BroadcastRecipient).where(
                BroadcastRecipient.provider_message_id == provider_message_id
            )
        )
        recipient = result.scalar_one_or_none()

        if not recipient:
            logger.warning(f"[DELIVERY] No recipient found for msg_id={provider_message_id}")
            return

        update_values: dict = {"status": internal_status}
        now = utcnow()

        if internal_status == "delivered" and not recipient.delivered_at:
            update_values["delivered_at"] = now
        elif internal_status == "read" and not recipient.read_at:
            update_values["read_at"] = now
            if not recipient.delivered_at:
                update_values["delivered_at"] = now
        elif internal_status == "failed":
            error_payload = payload.get("errors", payload.get("payload", {}))
            if isinstance(error_payload, list) and error_payload:
                update_values["failed_reason"] = str(error_payload[0].get("message", internal_status))
            else:
                update_values["failed_reason"] = str(error_payload.get("reason", internal_status))

        await db.execute(
            update(BroadcastRecipient)
            .where(BroadcastRecipient.id == recipient.id)
            .values(**update_values)
        )

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
            await db.execute(
                update(Broadcast)
                .where(Broadcast.id == recipient.broadcast_id)
                .values(status="sent")
            )

        await db.commit()


# ─── POST /webhooks/whatsapp ─────────────────────────────────────────────────

@router.post("/whatsapp", status_code=200)
async def whatsapp_inbound_webhook(
    request: Request,
):
    """
    Inbound WhatsApp message.
    Supports Meta (JSON), Twilio (form-encoded) payloads.
    Meta delivery receipts also arrive here and are handled inline.
    Always returns 200 — run_bot() is awaited inline.
    """
    from core.config import settings as app_settings

    # ── Parse inbound message / delivery receipt ──────────────────────────
    media_url = ""
    media_type = ""
    button_payload = ""
    list_id = ""
    inbound_msg_id = ""
    sender_phone = ""
    message_text = ""
    try:
        if app_settings.messaging_provider == "twilio":
            # Twilio sends form-encoded body
            form = await request.form()
            sender_phone = str(form.get("From", "")).replace("whatsapp:", "")
            message_text = str(form.get("Body", "")).strip()
            button_payload = str(form.get("ButtonPayload", "")).strip().lower()
            list_id        = str(form.get("ListId", "")).strip()
            num_media = int(form.get("NumMedia", 0))
            media_url = str(form.get("MediaUrl0", "")).strip() if num_media > 0 else ""
            media_type = str(form.get("MediaContentType0", "")).strip() if num_media > 0 else ""

        elif app_settings.messaging_provider == "meta":
            # Meta sends JSON via Graph API webhook format
            raw_body = await request.body()
            signature = request.headers.get("X-Hub-Signature-256", "")
            if signature:
                adapter = get_messaging_adapter()
                is_valid = await adapter.verify_webhook_signature(raw_body, signature)
                if not is_valid:
                    logger.warning("[META WEBHOOK] Invalid X-Hub-Signature-256 — rejected")
                    return Response(status_code=200, content="signature_invalid")

            body = await request.json()
            # Meta structure: {object: "whatsapp_business_account", entry: [{changes: [{value: {...}}]}]}
            entry = (body.get("entry") or [{}])[0]
            changes = (entry.get("changes") or [{}])[0]
            value = changes.get("value", {})

            # ── Delivery receipt (statuses array) ─────────────────────────
            statuses = value.get("statuses", [])
            if statuses:
                for status_obj in statuses:
                    msg_id = status_obj.get("id", "")
                    raw_status = status_obj.get("status", "")
                    internal_status = GUPSHUP_STATUS_MAP.get(raw_status, raw_status)
                    errors = status_obj.get("errors", [])
                    payload_for_update = {"errors": errors} if errors else {}
                    logger.info(f"[META DELIVERY] msg_id={msg_id} status={raw_status}")
                    if msg_id:
                        await _update_recipient_status(msg_id, internal_status, payload_for_update)
                return Response(status_code=200, content="ok")

            # ── Inbound message ───────────────────────────────────────────
            messages = value.get("messages", [])
            if not messages:
                logger.info("[META WEBHOOK] No messages in payload — ignored")
                return Response(status_code=200, content="ignored")

            msg_obj = messages[0]
            sender_phone = msg_obj.get("from", "")
            msg_type = msg_obj.get("type", "text")
            # 1.1: Capture inbound message ID for mark_as_read + reactions
            inbound_msg_id = msg_obj.get("id", "")

            if msg_type == "text":
                message_text = msg_obj.get("text", {}).get("body", "")
            elif msg_type == "interactive":
                interactive = msg_obj.get("interactive", {})
                i_type = interactive.get("type", "")
                if i_type == "button_reply":
                    # Quick-reply button tap
                    button_payload = interactive.get("button_reply", {}).get("id", "").lower()
                    message_text = interactive.get("button_reply", {}).get("title", "")
                elif i_type == "list_reply":
                    # List-picker row selection
                    list_id = interactive.get("list_reply", {}).get("id", "")
                    message_text = interactive.get("list_reply", {}).get("title", "")
                else:
                    message_text = ""
            elif msg_type in ("image", "document", "audio", "video", "sticker"):
                # Media: store the media_id as media_url — processor will resolve it
                media_obj = msg_obj.get(msg_type, {})
                media_url = media_obj.get("id", "")   # Meta media_id
                media_type = media_obj.get("mime_type", msg_type)
                message_text = media_obj.get("caption", "")
            else:
                logger.info(f"[META WEBHOOK] Unsupported message type: {msg_type}")
                return Response(status_code=200, content="ignored")

        else:
            # Gupshup / Mock sends JSON body
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

    except Exception as exc:
        logger.warning(f"[WA WEBHOOK] Failed to parse body: {exc}")
        return Response(status_code=200, content="ok")

    if not sender_phone or not (message_text or media_url):
        logger.warning("[WA WEBHOOK] Missing phone or message — ignored")
        return Response(status_code=200, content="ignored")

    logger.info(f"[WA WEBHOOK] from={sender_phone} msg={message_text[:60]} media={bool(media_url)}")

    # inbound_msg_id was initialized to "" at top of function and set inside Meta branch

    # ── Owner command routing ─────────────────────────────────────────────
    # Normalize phone numbers for comparison (strip '+' and spaces)
    owner_raw = str(settings.owner_phone).replace("+", "").replace(" ", "").strip()
    sender_raw = sender_phone.replace("+", "").replace(" ", "").strip()
    
    if owner_raw and sender_raw == owner_raw:
        base_url = str(request.base_url)

        # 3.5: Handle offer expiry button taps BEFORE command dispatch
        if button_payload.startswith("broadcast_expiry_") or button_payload.startswith("skip_expiry_"):
            adapter = get_messaging_adapter()
            try:
                offer_id_str = button_payload.split("_", 2)[-1]
                from models.models import Offer
                from services.broadcast_service import create_broadcast
                async with AsyncSessionLocal() as _db:
                    offer = (await _db.execute(
                        select(Offer).where(Offer.id == offer_id_str)
                    )).scalar_one_or_none()

                if button_payload.startswith("broadcast_expiry_") and offer:
                    # Auto-create a broadcast for this expiring offer
                    offer_desc = offer.description or "Don’t miss out — contact us today!"
                    msg_text = (
                        f"⏰ *Last chance!* Our offer *\"{offer.title}\"* expires soon.\n\n"
                        f"{offer_desc}\n\n"
                        f"_Reply *ORDER* to place your order now!_"
                    )
                    async with AsyncSessionLocal() as _db:
                        bc = await create_broadcast(
                            db=_db,
                            name=f"Expiry reminder: {offer.title[:40]}",
                            message_template=msg_text,
                            override_cooldown=False,
                        )
                        from tasks.broadcast_tasks import send_broadcast
                        send_broadcast.delay(str(bc["id"]))
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"✅ Broadcast queued for offer expiry: *\"{offer.title}\"*",
                    )
                    logger.info(f"[EXPIRY] Owner approved broadcast for: {offer.title}")
                elif button_payload.startswith("skip_expiry_"):
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"✅ Skipped — no broadcast sent for this offer.",
                    )
            except Exception as exc:
                logger.error(f"[EXPIRY] Button handler failed: {exc}", exc_info=True)
            return Response(status_code=200, content="ok")

        try:
            cmd_response = await command_service.dispatch_owner_command(
                msg=message_text.strip(),
                sender_phone=sender_phone,
                media_url=media_url,
                media_type=media_type,
                base_url=base_url,
                message_id=inbound_msg_id,
                button_payload=button_payload,  # 2.3: analytics toggle
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
    if media_url and media_type:
        logger.info(f"[MEDIA] Processing {media_type} from {sender_phone}")
        adapter = get_messaging_adapter()
        if media_type.startswith("image/"):
            # 1.1: mark as read + typing instead of "analysing..." text
            if inbound_msg_id:
                await adapter.mark_as_read(inbound_msg_id)
            await adapter.send_message(phone=sender_phone, message="📸 Let me take a look at that image...")
            
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

            # Send warm welcome + opt-in consent as interactive buttons (1.6)
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
                    f"_For direct help: {settings.support_phone}_"
                ),
            )
            # Interactive YES/NO subscription buttons
            await adapter.send_interactive_message(
                phone=sender_phone,
                body="📢 Would you like to receive product updates & offers from us?",
                buttons=[
                    {"id": "consent_yes", "title": "✅ Yes, Subscribe"},
                    {"id": "consent_no",  "title": "❌ No, Skip"},
                ],
                use_list=False,
            )
            await set_onboard_state(sender_phone, ONBOARD_AWAITING_CONSENT)
            return Response(status_code=200, content="ok")

        # ── 1.2 & 1.3 Onboarding state machine ───────────────────────────
        onboard_state = await get_onboard_state(sender_phone)

        if onboard_state == ONBOARD_AWAITING_CONSENT:
            reply = message_text.strip().upper()
            # 1.6: accept BOTH button tap (button_payload) AND typed text
            is_yes = (
                button_payload in ("consent_yes",)
                or reply in ("YES", "Y", "HAN", "हाँ", "हां", "HA")
            )
            is_no = (
                button_payload in ("consent_no",)
                or reply in ("NO", "N", "NAI", "NAHI", "नहीं", "नही")
            )

            if is_yes:
                client.opted_in = True
                await db.commit()
                logger.info(f"[ONBOARD] {sender_phone} opted IN")
                await set_onboard_state(sender_phone, ONBOARD_AWAITING_LANGUAGE)
                await adapter.send_message(
                    phone=sender_phone,
                    message="✅ *You're subscribed!* We'll keep you updated with the latest offers. 🎉",
                )
                # 1.6: Language selection as interactive buttons
                await adapter.send_interactive_message(
                    phone=sender_phone,
                    body="🌐 What language do you prefer?",
                    buttons=[
                        {"id": "lang_en", "title": "🇬🇧 English"},
                        {"id": "lang_hi", "title": "🇮🇳 हिंदी"},
                    ],
                    use_list=False,
                )
            elif is_no:
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
                # 1.6: Still ask for language preference
                await adapter.send_interactive_message(
                    phone=sender_phone,
                    body="🌐 What language do you prefer?",
                    buttons=[
                        {"id": "lang_en", "title": "🇬🇧 English"},
                        {"id": "lang_hi", "title": "🇮🇳 हिंदी"},
                    ],
                    use_list=False,
                )
                await set_onboard_state(sender_phone, ONBOARD_AWAITING_LANGUAGE)
            else:
                # Unrecognised reply — re-show the buttons
                await adapter.send_interactive_message(
                    phone=sender_phone,
                    body="Please tap a button to choose 👇",
                    buttons=[
                        {"id": "consent_yes", "title": "✅ Yes, Subscribe"},
                        {"id": "consent_no",  "title": "❌ No, Skip"},
                    ],
                    use_list=False,
                )
            return Response(status_code=200, content="ok")

        if onboard_state == ONBOARD_AWAITING_LANGUAGE:
            reply = message_text.strip().upper()
            # 1.6: accept button tap OR typed text for language choice
            is_hindi = (
                button_payload in ("lang_hi",)
                or reply in ("HINDI", "HI", "हिंदी")
            )
            is_english = (
                button_payload in ("lang_en",)
                or reply in ("EN", "ENGLISH", "ENG")
            )

            if is_hindi:
                client.language = "hi"
                await db.commit()
                logger.info(f"[ONBOARD] {sender_phone} language set to Hindi")
                # 2.6: ask for name before finishing onboarding
                await set_onboard_state(sender_phone, ONBOARD_AWAITING_NAME)
                await adapter.send_message(
                    phone=sender_phone,
                    message="बढ़िया! 🎉 आपका नाम क्या है? 😊\n(_हम आपका बेहतर तरीके से साथ देना चाहते हैं_)",
                )
            elif is_english:
                client.language = "en"
                await db.commit()
                logger.info(f"[ONBOARD] {sender_phone} language set to English")
                # 2.6: ask for name before finishing onboarding
                await set_onboard_state(sender_phone, ONBOARD_AWAITING_NAME)
                await adapter.send_message(
                    phone=sender_phone,
                    message="Great! 🎉 One last thing — what's your name? 😊\n_(So we can personalise your experience)_",
                )
            else:
                # Re-show language buttons instead of plain text
                await adapter.send_interactive_message(
                    phone=sender_phone,
                    body="Please tap to choose your language 👇",
                    buttons=[
                        {"id": "lang_en", "title": "🇬🇧 English"},
                        {"id": "lang_hi", "title": "🇮🇳 हिंदी"},
                    ],
                    use_list=False,
                )
            return Response(status_code=200, content="ok")

        # 2.6: Name capture step
        if onboard_state == ONBOARD_AWAITING_NAME:
            captured_name = message_text.strip()
            if len(captured_name) >= 2:
                client.name = captured_name
                await db.commit()
                await clear_onboard_state(sender_phone)
                logger.info(f"[ONBOARD] {sender_phone} name set to: {captured_name}")
                greeting = "Swaagat hai" if client.language == "hi" else "Welcome"
                await adapter.send_message(
                    phone=sender_phone,
                    message=(
                        f"🎉 {greeting}, *{captured_name}*!\n\n"
                        f"You're all set. Feel free to explore our products or ask me anything! 😊"
                    ),
                )
                await menu_service.send_main_menu(adapter, sender_phone)
            else:
                # Too short — nudge
                await adapter.send_message(
                    phone=sender_phone,
                    message="Please share your name so we can personalise your experience 😊",
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

        # ── 3.3: MY ORDERS self-service ────────────────────────────────────────────────────────────────────
        if msg_upper in ("MY ORDERS", "MY ORDER", "ORDERS", "ORDER HISTORY", "MY ENQUIRIES"):
            from models.models import Conversation
            async with AsyncSessionLocal() as _db:
                enquiries = (await _db.execute(
                    select(Conversation)
                    .where(
                        Conversation.client_id == client.id,
                        Conversation.enquiry_intent == True,
                    )
                    .order_by(Conversation.created_at.desc())
                    .limit(5)
                )).scalars().all()

                if not enquiries:
                    await adapter.send_message(
                        phone=sender_phone,
                        message="You haven't placed any enquiries yet.\n\nAsk me about any product and tap *ORDER* to register your interest! 😊",
                    )
                else:
                    from zoneinfo import ZoneInfo
                    IST = ZoneInfo("Asia/Kolkata")
                    lines = [f"📋 *Your Last {len(enquiries)} Enquiries*\n"]
                    for i, conv in enumerate(enquiries, 1):
                        # Convert to IST timezone
                        dt_utc = conv.created_at.replace(tzinfo=timezone.utc) if not conv.created_at.tzinfo else conv.created_at
                        dt_ist = dt_utc.astimezone(IST)
                        date = dt_ist.strftime("%d %b, %I:%M %p")
                        question = (conv.message or "").strip()
                        
                        if question.upper() == "ORDER":
                            # Fetch the previous conversation to provide context on what was ordered
                            # We filter out exactly "ORDER" so we don't get stuck on consecutive button taps
                            prev_conv = (await _db.execute(
                                select(Conversation)
                                .where(
                                    Conversation.client_id == client.id,
                                    Conversation.created_at < conv.created_at,
                                    Conversation.message.not_ilike("ORDER")
                                )
                                .order_by(Conversation.created_at.desc())
                                .limit(1)
                            )).scalar_one_or_none()
                            
                            if prev_conv and prev_conv.message:
                                # Clean up previous message if needed
                                prev_msg = prev_conv.message.strip()
                                question = f"Order regarding: {prev_msg[:50]}..." if len(prev_msg) > 50 else f"Order regarding: {prev_msg}"
                            else:
                                question = "Product Enquiry"
                        else:
                            question = question[:60]
                            
                        lines.append(f"{i}. 📅 {date}\n   _{question}_")
                    
                    lines.append("\n_To enquire again, just ask about any product and tap ORDER._")
                    await adapter.send_message(phone=sender_phone, message="\n\n".join(lines))
            return Response(status_code=200, content="ok")

        # ── 3.4: Language switch mid-session ──────────────────────────────────────────────────────────────
        # Client can type LANGUAGE / SWITCH LANGUAGE or tap a mid-session button
        if msg_upper in ("LANGUAGE", "SWITCH LANGUAGE", "CHANGE LANGUAGE", "LANG") or button_payload == "mid_switch_lang":
            await adapter.send_interactive_message(
                phone=sender_phone,
                body="🌐 Choose your preferred language:",
                buttons=[
                    {"id": "lang_en", "title": "🇬🇧 English"},
                    {"id": "lang_hi", "title": "🇮🇳 हिंदी"},
                ],
                use_list=False,
            )
            # Reuse the AWAITING_LANGUAGE onboarding state to capture the reply
            await set_onboard_state(sender_phone, ONBOARD_AWAITING_LANGUAGE)
            return Response(status_code=200, content="ok")

        # ── Menu state machine (Priority 4) ───────────────────────────────────
        menu_handled = await menu_service.handle_menu_input(
            adapter=adapter,
            phone=sender_phone,
            msg=message_text,
            button_payload=button_payload,
            list_id=list_id,
            db=db,
            client_id=str(client.id),
        )
        if menu_handled:
            return Response(status_code=200, content="ok")

        # ── Pass to RAG bot as normal ──────────────────
        client_id = str(client.id)

        # 1.1: Mark as read (blue ticks) — replaces old "Got your message!" placeholder text
        if inbound_msg_id and app_settings.messaging_provider == "meta":
            try:
                await adapter.mark_as_read(inbound_msg_id)
            except Exception:
                pass

        logger.info(f"[WA WEBHOOK] Calling run_bot for {sender_phone} | client_id={client_id} | msg={message_text[:60]}")
        try:
            await run_bot(
                phone=sender_phone,
                raw_message=message_text,
                client_id=client_id,
                db=db,
            )
            logger.info(f"[WA WEBHOOK] run_bot completed for {sender_phone}")

            # 1.7: Show main menu after RAG bot answers for continued navigation
            try:
                await menu_service.send_main_menu(adapter, sender_phone)
            except Exception as menu_exc:
                logger.warning(f"[WA WEBHOOK] post-RAG menu failed (non-fatal): {menu_exc}")

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
