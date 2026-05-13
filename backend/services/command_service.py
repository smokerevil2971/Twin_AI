"""
Owner Command Service — Phase 2 Refactor

Supported commands via registry:
  /help, /status, /clients, /report, /broadcasts, /analytics [7|30], /kb
  /catalogue=<url>
  /products, /offers
  BROADCAST: <msg>           — text broadcast
  BROADCAST (urgent): <msg>  — skip cooldown window
  CANCEL BROADCAST: <name>   — cancel by partial name
  SCHEDULE: YYYY-MM-DD HH:MM <msg>
  ADD: <phone>, <name>
  REMOVE: <phone>
  PRODUCT: <name> | <price> | <description>
  OFFER:   <title> | <description>
  UPDATE PRODUCT: <name> | <new_price>
  DEL PRODUCT: <name>
  DEL OFFER: <title>
  <CSV/XLSX media>       → bulk client import
  <PDF/DOCX/TXT media>   → knowledge base ingestion
  Anything else → falls through to the RAG bot
"""
import logging
import re
from typing import Optional

from fastapi import Response
from core.config import settings

from handlers.owner_commands import COMMAND_REGISTRY, UPLOAD_HANDLERS, CommandPayload
from services.products_offers_service import (
    parse_products_file,
    parse_offers_file,
    bulk_import_products,
    bulk_import_offers,
)

logger = logging.getLogger(__name__)

# ─── Phone normalisation ──────────────────────────────────────────────────────
def _normalise_phone(raw: str) -> str:
    """
    Strip all non-digit characters and normalise to E.164 (+91XXXXXXXXXX).
    Handles inputs like: '84321 26997', '+918432126997', '918432126997'.
    Returns the canonical '+91...' form.
    """
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+91{digits}"
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    # Already has country code or unknown format — prefix + if missing
    return f"+{digits}" if not raw.strip().startswith("+") else raw.strip()

# ─── MIME type sets ───────────────────────────────────────────────────────────
_CLIENT_SHEET_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_INGESTABLE_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
    "text/markdown",
}

_KB_EXT_MAP = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "text/plain": ".txt",
    "text/markdown": ".md",
}

# ─── Entry point (called by webhooks.py) ─────────────────────────────────────
async def dispatch_owner_command(
    msg: str,
    sender_phone: str,
    media_url: str = "",
    media_type: str = "",
    base_url: str = "",
    message_id: str = "",   # 1.2: for emoji reactions
    button_payload: str = "", # 2.3: for analytics toggle button
) -> Optional[Response]:
    """
    Routes an inbound owner WhatsApp message to the correct handler.

    Returns a FastAPI Response if the command was handled, or None to signal
    that the message should fall through to the RAG bot (owner testing mode).
    """
    # 2.3: Reroute analytics button taps as analytics commands
    if button_payload in ("analytics_7days", "analytics_30days"):
        msg = button_payload

    if media_url and settings.messaging_provider == "meta" and not media_url.startswith("http"):
        try:
            from services.media_processor import _resolve_meta_media
            real_url, detected_mime = await _resolve_meta_media(media_url)
            media_url = real_url
            if detected_mime:
                media_type = detected_mime
        except Exception as e:
            logger.error(f"[CMD] Failed to resolve Meta media_id {media_url}: {e}")

    payload = CommandPayload(
        msg=msg,
        sender_phone=sender_phone,
        media_url=media_url,
        media_type=media_type,
        base_url=base_url,
        message_id=message_id,
        button_payload=button_payload,
    )

    # 1. Try Upload handlers first
    if media_url and media_type:
        for handler in UPLOAD_HANDLERS:
            try:
                resp = await handler.execute(payload)
                if resp is not None:
                    return resp
            except Exception as exc:
                logger.error(f"[CMD] Upload Handler {handler.__class__.__name__} failed: {exc}", exc_info=True)
                from services.messaging_adapter import get_messaging_adapter
                adapter = get_messaging_adapter()
                try:
                    await adapter.send_message(phone=sender_phone, message="❌ Upload processing failed. Check server logs for details.")
                except Exception:
                    pass
                return Response(status_code=200, content="ok")

    # 2. Try text command registry
    if msg:
        clean_msg = msg.strip()
        for pattern, handler in COMMAND_REGISTRY:
            match = pattern.match(clean_msg)
            if match:
                payload.match = match
                try:
                    return await handler.execute(payload)
                except Exception as exc:
                    logger.error(f"[CMD] Handler {handler.__class__.__name__} failed: {exc}", exc_info=True)
                    from services.messaging_adapter import get_messaging_adapter
                    adapter = get_messaging_adapter()
                    try:
                        await adapter.send_message(phone=sender_phone, message="❌ Command failed. Check server logs for details.")
                    except Exception:
                        pass
                    return Response(status_code=200, content="ok")

    # ── No command matched — owner is testing the RAG bot ────────────────────
    logger.info(f"[CMD] No command matched — routing to RAG bot: {msg[:60]}")
    return None
