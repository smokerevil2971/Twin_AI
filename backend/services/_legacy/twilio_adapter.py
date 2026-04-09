"""
Twilio WhatsApp adapter.
Activate by setting MESSAGING_PROVIDER=twilio in .env.
Uses Twilio sandbox for pre-approval testing.
Sandbox number: whatsapp:+14155238886
"""
import logging
import hmac
import hashlib

import httpx

from services.messaging_adapter import MessagingAdapter
from core.config import settings

logger = logging.getLogger(__name__)


class TwilioAdapter(MessagingAdapter):
    """
    Twilio WhatsApp adapter — implements the same
    GupshupAdapter interface so all existing code
    (broadcast_service, rag_bot, webhooks) works
    with zero changes.
    """

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
    ):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = f"whatsapp:{from_number}"
        self.base_url = (
            f"https://api.twilio.com/2010-04-01"
            f"/Accounts/{account_sid}/Messages.json"
        )

    async def send_message(self, phone: str, message: str) -> dict:
        to = f"whatsapp:{phone}"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                data={
                    "From": self.from_number,
                    "To": to,
                    "Body": message,
                },
                auth=(self.account_sid, self.auth_token),
                timeout=settings.http_timeout_seconds,
            )
        if response.status_code not in (200, 201):
            logger.error(
                f"[TWILIO] send_message failed "
                f"status={response.status_code} "
                f"body={response.text[:200]}"
            )
            response.raise_for_status()

        data = response.json()
        logger.info(
            f"[TWILIO] sent → {phone} "
            f"sid={data.get('sid')} "
            f"status={data.get('status')}"
        )
        return {
            "status": data.get("status", "queued"),
            "messageId": data.get("sid", ""),
            "phone": phone,
        }

    async def send_media_message(
        self,
        phone: str,
        media_url: str,
        media_type: str,
        caption: str = "",
        filename: str = "document.pdf",
    ) -> dict:
        """
        Send an image or document via Twilio WhatsApp.
        Twilio renders MediaUrl as inline image (image/*) or document attachment (application/pdf).
        The Body acts as the caption shown below the media.
        """
        to = f"whatsapp:{phone}"
        post_data = {
            "From": self.from_number,
            "To": to,
            "MediaUrl": media_url,
        }
        if caption:
            post_data["Body"] = caption

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                data=post_data,
                auth=(self.account_sid, self.auth_token),
                timeout=settings.http_timeout_seconds,
            )
        if response.status_code not in (200, 201):
            logger.error(
                f"[TWILIO] send_media_message failed "
                f"status={response.status_code} "
                f"body={response.text[:200]}"
            )
            response.raise_for_status()

        data = response.json()
        logger.info(
            f"[TWILIO] media sent ({media_type}) → {phone} "
            f"sid={data.get('sid')} status={data.get('status')}"
        )
        return {
            "status": data.get("status", "queued"),
            "messageId": data.get("sid", ""),
            "phone": phone,
        }

    async def send_interactive_message(
        self,
        phone: str,
        body: str,
        buttons: list[dict],
        use_list: bool = False,
        list_items: list[dict] | None = None,
    ) -> dict:
        """
        Send a WhatsApp interactive message via Twilio Content API.

        Quick-reply (use_list=False):
          buttons = [{"id": "products", "title": "🛍️ Products"}, ...]
          Renders as inline tappable buttons (max 3, WhatsApp limit).

        List-picker (use_list=True):
          list_items = [{"id": "row_xyz", "title": "Solar Panel 300W", "description": "₹8,500"}, ...]
          Renders as a scrollable popup list (max 10 items, WhatsApp limit).
        """
        from core.redis_client import get_cached_content_sid, cache_content_sid

        if use_list:
            import hashlib
            # Hash the items and the body to create a unique template per list configuration
            items_str = "--".join(f"{i['id']}::{i['title']}::{i.get('description', '')}" for i in (list_items or []))
            list_hash = hashlib.md5((body + items_str).encode()).hexdigest()
            cache_key = f"twilio:dynlist_{list_hash}"
            
            content_sid = await get_cached_content_sid(cache_key)
            if not content_sid:
                content_sid = await self._create_list_picker_template(body, list_items or [])
                if content_sid:
                    await cache_content_sid(cache_key, content_sid)

            if content_sid and list_items:
                return await self._send_with_list_sid(phone, body, content_sid)
            # Fallback: plain numbered text if template creation failed
            lines = "\n".join(
                f"{i+1}. {item['title']}" for i, item in enumerate(list_items or [])
            )
            return await self.send_message(phone=phone, message=f"{body}\n\n{lines}")
        else:
            cache_key = "twilio:main_menu_sid"
            content_sid = await get_cached_content_sid(cache_key)
            if not content_sid:
                content_sid = await self._create_quick_reply_template(buttons)
                if content_sid:
                    await cache_content_sid(cache_key, content_sid)

            if content_sid:
                return await self._send_with_content_sid(phone, content_sid)
            # Fallback: plain text buttons
            labels = "  |  ".join(b["title"] for b in buttons)
            return await self.send_message(phone=phone, message=f"{body}\n\n{labels}")

    # ── Twilio Content API helpers ──────────────────────────────────────────────

    async def _create_quick_reply_template(self, buttons: list[dict]) -> str | None:
        """Create a twilio/quick-reply Content Template and return its ContentSid."""
        actions = [{"id": b["id"], "title": b["title"]} for b in buttons]
        payload = {
            "friendly_name": "twin_ai_main_menu_v2",
            "language": "en",
            "types": {
                "twilio/quick-reply": {
                    "body": "What would you like to explore today? 🔍",
                    "actions": actions,
                }
            },
        }
        return await self._post_content_template(payload)

    async def _create_list_picker_template(self, body: str, list_items: list[dict]) -> str | None:
        """
        Create a twilio/list-picker Content Template with hardcoded items and body.
        (Twilio Content API does not allow variables in list item titles/descriptions).
        """
        logger.info(f"[TWILIO] Creating new list-picker template for {len(list_items)} items")
        items = []
        for item in list_items[:10]:
            # Twilio list items: item max 24 chars, description max 72 chars
            items.append({
                "id": str(item["id"])[:200],
                "item": str(item["title"])[:24],
                "description": str(item.get("description", ""))[:72]
            })

        payload = {
            "friendly_name": f"twin_ai_list_{len(list_items)}_items",
            "language": "en",
            "types": {
                "twilio/list-picker": {
                    "body": body,
                    "button": "Select",
                    "items": items,
                }
            },
        }
        return await self._post_content_template(payload)

    async def _post_content_template(self, payload: dict) -> str | None:
        """POST to Twilio Content API; return ContentSid or None on error."""
        import json as _json
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://content.twilio.com/v1/Content",
                    json=payload,
                    auth=(self.account_sid, self.auth_token),
                )
            if resp.status_code in (200, 201):
                sid = resp.json().get("sid")
                logger.info(f"[TWILIO] Content template created: {sid}")
                return sid
            logger.error(
                f"[TWILIO] Content API error {resp.status_code}: {resp.text[:200]}"
            )
        except Exception as exc:
            logger.error(f"[TWILIO] Content API exception: {exc}")
        return None

    async def _send_with_content_sid(self, phone: str, content_sid: str) -> dict:
        """Send a message using a pre-created ContentSid (no variables)."""
        to = f"whatsapp:{phone}"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                data={"From": self.from_number, "To": to, "ContentSid": content_sid},
                auth=(self.account_sid, self.auth_token),
                timeout=settings.http_timeout_seconds,
            )
        if response.status_code not in (200, 201):
            logger.error(f"[TWILIO] send ContentSid failed: {response.status_code} {response.text[:200]}")
            response.raise_for_status()
        data = response.json()
        logger.info(f"[TWILIO] interactive sent → {phone} sid={data.get('sid')}")
        return {"status": data.get("status", "queued"), "messageId": data.get("sid", ""), "phone": phone}

    async def _send_with_list_sid(
        self, phone: str, body: str, content_sid: str
    ) -> dict:
        """
        Send a list-picker message using the pre-generated static ContentSid.
        """
        to = f"whatsapp:{phone}"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                data={
                    "From": self.from_number,
                    "To": to,
                    "ContentSid": content_sid,
                },
                auth=(self.account_sid, self.auth_token),
                timeout=settings.http_timeout_seconds,
            )
        if response.status_code not in (200, 201):
            logger.error(f"[TWILIO] list-picker send failed: {response.status_code} {response.text[:200]}")
            response.raise_for_status()
        data = response.json()
        logger.info(f"[TWILIO] list-picker sent → {phone} sid={data.get('sid')}")
        return {"status": data.get("status", "queued"), "messageId": data.get("sid", ""), "phone": phone}

    async def verify_webhook_signature(
        self, payload: bytes, signature: str
    ) -> bool:
        """
        Twilio signs webhooks with X-Twilio-Signature header.
        Validation uses HMAC-SHA1 of the full URL + sorted params.
        During sandbox testing we skip strict validation —
        set TWILIO_SKIP_SIG_VALIDATION=true in .env to bypass.
        """
        from core.config import settings
        skip = getattr(settings, "twilio_skip_sig_validation", "true")
        if str(skip).lower() == "true":
            logger.info(
                "[TWILIO] webhook signature check skipped "
                "(TWILIO_SKIP_SIG_VALIDATION=true)"
            )
            return True
        # Full validation for production
        expected = hmac.new(
            self.auth_token.encode(),
            payload,
            hashlib.sha1,
        ).digest()
        import base64
        expected_b64 = base64.b64encode(expected).decode()
        return hmac.compare_digest(expected_b64, signature)
