"""
Webhook routes — Phase 2.5 + 3.3
  POST /webhooks/gupshup/delivery      — inbound Gupshup delivery receipt (2.5)
  POST /webhooks/whatsapp            — inbound WhatsApp message from client (3.3)

Security:
  - HMAC-SHA256 signature verified against X-Gupshup-Signature header
  - In mock mode, signature check always passes
  - Returns 200 immediately — Gupshup retries on non-2xx
"""
import logging
from fastapi import APIRouter, Request, Response
from core.database import get_db_context
from core.config import settings
from services.messaging_adapter import get_messaging_adapter
from services.media_processor import process_media, UNSUPPORTED_MSG, RATE_LIMITED_MSG
from services.guardrails.input_guard import check_input
from sqlalchemy import select

from handlers.event import InboundEvent
from handlers.delivery import DeliveryHandler, GUPSHUP_STATUS_MAP
from handlers.owner import OwnerHandler
from handlers.onboarding import OnboardingHandler
from handlers.client import ClientHandler
from models.models import Client

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
logger = logging.getLogger(__name__)

class WebhookRouter:
    @staticmethod
    async def route(event: InboundEvent) -> Response:
        """Route the inbound event to the appropriate handler."""
        if event.is_delivery_receipt:
            await DeliveryHandler.handle(event)
            return Response(status_code=200, content="ok")

        # ── Layer 1: Input Guardrail ──────────────────────────────────────────────
        if event.message_text and not event.media_url:
            try:
                guard_result = await check_input(event.sender_phone, event.message_text)
                if not guard_result.allowed:
                    logger.info(
                        f"[GUARDRAIL] Input blocked: phone={event.sender_phone} reason={guard_result.reason}"
                    )
                    if guard_result.reply_override:
                        _adapter = get_messaging_adapter()
                        await _adapter.send_message(
                            phone=event.sender_phone, message=guard_result.reply_override
                        )
                    return Response(status_code=200, content="guardrail_blocked")
            except Exception as _guard_exc:
                logger.warning(f"[GUARDRAIL] Input guard failed (non-fatal): {_guard_exc}")

        # Determine if sender is owner
        owner_raw = str(settings.owner_phone).replace("+", "").replace(" ", "").strip()
        sender_raw = event.sender_phone.replace("+", "").replace(" ", "").strip()
        if owner_raw and sender_raw == owner_raw:
            event.is_owner = True

        if event.is_owner:
            return await OwnerHandler.handle(event)

        # ── Regular client — Process media and load DB client ────────────────────────────
        if event.media_url and event.media_type:
            logger.info(f"[MEDIA] Processing {event.media_type} from {event.sender_phone}")
            adapter = get_messaging_adapter()
            if event.media_type.startswith("image/"):
                if event.inbound_msg_id:
                    await adapter.mark_as_read(event.inbound_msg_id)
                await adapter.send_message(phone=event.sender_phone, message="📸 Let me take a look at that image...")
                
            processed = await process_media(
                media_url=event.media_url,
                content_type=event.media_type,
                caption=event.message_text,
            )
            if processed in (UNSUPPORTED_MSG, RATE_LIMITED_MSG):
                adapter = get_messaging_adapter()
                await adapter.send_message(phone=event.sender_phone, message=processed)
                return Response(status_code=200, content="ok")
            event.message_text = processed

        if not event.message_text:
            return Response(status_code=200, content="ok")

        async with get_db_context() as db:
            result = await db.execute(select(Client).where(Client.phone == event.sender_phone))
            event.client = result.scalar_one_or_none()

            # Handle onboarding
            onboard_resp = await OnboardingHandler.handle(event, db)
            if onboard_resp is not None:
                return onboard_resp
                
            # Delegate to client handlers
            return await ClientHandler.handle(event, db)


# ─── POST /webhooks/gupshup/delivery ─────────────────────────────────────────

@router.get("/whatsapp", status_code=200)
async def whatsapp_verify(request: Request):
    """Meta webhook verification handshake."""
    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")

    if mode == "subscribe" and token == settings.meta_webhook_verify_token:
        logger.info("[META] Webhook verification successful")
        return Response(content=challenge, media_type="text/plain")

    logger.warning(f"[META] Webhook verification failed")
    return Response(status_code=403, content="forbidden")


@router.post("/gupshup/delivery", status_code=200)
async def gupshup_delivery_webhook(request: Request):
    """Legacy Gupshup delivery status callback."""
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

    event = InboundEvent(
        provider="gupshup",
        sender_phone=destination,
        is_delivery_receipt=True,
        delivery_status=internal_status,
        delivery_msg_id=provider_message_id,
        delivery_payload=payload
    )
    return await WebhookRouter.route(event)


# ─── POST /webhooks/whatsapp ─────────────────────────────────────────────────

@router.post("/whatsapp", status_code=200)
async def whatsapp_inbound_webhook(request: Request):
    """
    Inbound WhatsApp message.
    Supports Meta (JSON), Twilio (form-encoded) payloads.
    Meta delivery receipts also arrive here and are handled inline.
    Always returns 200 — run_bot() is awaited inline.
    """
    event = InboundEvent(
        provider=settings.messaging_provider,
        sender_phone="",
        base_url=str(request.base_url)
    )

    try:
        if settings.messaging_provider == "twilio":
            form = await request.form()
            event.sender_phone = str(form.get("From", "")).replace("whatsapp:", "")
            event.message_text = str(form.get("Body", "")).strip()
            event.button_payload = str(form.get("ButtonPayload", "")).strip().lower()
            event.list_id = str(form.get("ListId", "")).strip()
            num_media = int(form.get("NumMedia", 0))
            event.media_url = str(form.get("MediaUrl0", "")).strip() if num_media > 0 else ""
            event.media_type = str(form.get("MediaContentType0", "")).strip() if num_media > 0 else ""

        elif settings.messaging_provider == "meta":
            raw_body = await request.body()
            signature = request.headers.get("X-Hub-Signature-256", "")

            if not signature:
                logger.warning("[META WEBHOOK] Missing X-Hub-Signature-256 header — rejected")
                return Response(status_code=200, content="unauthorized")

            adapter = get_messaging_adapter()
            is_valid = await adapter.verify_webhook_signature(raw_body, signature)
            if not is_valid:
                logger.warning("[META WEBHOOK] Invalid X-Hub-Signature-256 — rejected")
                return Response(status_code=200, content="signature_invalid")

            body = await request.json()
            entry = (body.get("entry") or [{}])[0]
            changes = (entry.get("changes") or [{}])[0]
            value = changes.get("value", {})

            # ── Delivery receipt ─────────────────────────
            statuses = value.get("statuses", [])
            if statuses:
                for status_obj in statuses:
                    msg_id = status_obj.get("id", "")
                    raw_status = status_obj.get("status", "")
                    internal_status = GUPSHUP_STATUS_MAP.get(raw_status, raw_status)
                    errors = status_obj.get("errors", [])
                    payload_for_update = {"errors": errors} if errors else {}
                    
                    if msg_id:
                        delivery_event = InboundEvent(
                            provider="meta",
                            sender_phone="",
                            is_delivery_receipt=True,
                            delivery_status=internal_status,
                            delivery_msg_id=msg_id,
                            delivery_payload=payload_for_update
                        )
                        await WebhookRouter.route(delivery_event)
                return Response(status_code=200, content="ok")

            # ── Inbound message ───────────────────────────────────────────
            messages = value.get("messages", [])
            if not messages:
                return Response(status_code=200, content="ignored")

            msg_obj = messages[0]
            event.sender_phone = msg_obj.get("from", "")
            msg_type = msg_obj.get("type", "text")
            event.inbound_msg_id = msg_obj.get("id", "")

            if msg_type == "text":
                event.message_text = msg_obj.get("text", {}).get("body", "")
            elif msg_type == "interactive":
                interactive = msg_obj.get("interactive", {})
                i_type = interactive.get("type", "")
                if i_type == "button_reply":
                    event.button_payload = interactive.get("button_reply", {}).get("id", "").lower()
                    event.message_text = interactive.get("button_reply", {}).get("title", "")
                elif i_type == "list_reply":
                    event.list_id = interactive.get("list_reply", {}).get("id", "")
                    event.message_text = interactive.get("list_reply", {}).get("title", "")
            elif msg_type in ("image", "document", "audio", "video", "sticker"):
                media_obj = msg_obj.get(msg_type, {})
                event.media_url = media_obj.get("id", "")
                event.media_type = media_obj.get("mime_type", msg_type)
                event.message_text = media_obj.get("caption", "")

        else:
            # Gupshup / Mock
            raw_body = await request.body()
            signature = request.headers.get("X-Gupshup-Signature", "")
            if signature:
                adapter = get_messaging_adapter()
                is_valid = await adapter.verify_webhook_signature(raw_body, signature)
                if not is_valid:
                    return Response(status_code=200, content="signature_invalid")

            body = await request.json()
            payload = body.get("payload", {})
            msg_type = body.get("type", "")

            if msg_type != "message":
                return Response(status_code=200, content="ignored")

            event.sender_phone = payload.get("source") or payload.get("sender", {}).get("phone", "")
            inner = payload.get("payload", {})
            event.message_text = str(inner.get("text") or inner.get("message") or "")

    except Exception as exc:
        logger.warning(f"[WA WEBHOOK] Failed to parse body: {exc}")
        return Response(status_code=200, content="ok")

    if not event.sender_phone or not (event.message_text or event.media_url):
        return Response(status_code=200, content="ignored")

    return await WebhookRouter.route(event)
