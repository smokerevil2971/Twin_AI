"""
Meta WhatsApp Business API adapter.
Activate by setting MESSAGING_PROVIDER=meta in .env.

Uses the Graph API v19.0 (or whichever META_API_VERSION is set).
All outbound calls go to:
  https://graph.facebook.com/{version}/{phone_number_id}/messages
  Authorization: Bearer {access_token}

Inbound webhook:
  POST /webhooks/whatsapp  (handled in routes/webhooks.py)
  GET  /webhooks/whatsapp  (hub.challenge verification — also in webhooks.py)

Media strategy: upload-first
  Outbound media (images, documents) are uploaded to Meta's servers to get
  a reusable `media_id`. The media_id is cached in Redis (md5 of source URL,
  25-day TTL — Meta expires media after 30 days) to avoid redundant uploads.
"""
import asyncio
import hashlib
import hmac
import mimetypes

import httpx

from services.messaging_adapter import MessagingAdapter
from core.config import settings

from core.logging import logger

# Meta Graph API base
_GRAPH_BASE = "https://graph.facebook.com"

# Map our media_type strings to Meta message types
_MEDIA_TYPE_MAP = {
    "image": "image",
    "document": "document",
    "audio": "audio",
    "video": "video",
}


class MetaWABAAdapter(MessagingAdapter):
    """
    Meta WhatsApp Business API adapter.
    Implements the MessagingAdapter interface so all existing code
    (broadcast_service, rag_bot, webhooks, menu_service) works unchanged.
    """

    def __init__(
        self,
        phone_number_id: str,
        access_token: str,
        app_secret: str,
        api_version: str = "v19.0",
    ):
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.app_secret = app_secret
        self.api_version = api_version
        self.messages_url = (
            f"{_GRAPH_BASE}/{api_version}/{phone_number_id}/messages"
        )
        self.media_url = (
            f"{_GRAPH_BASE}/{api_version}/{phone_number_id}/media"
        )
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    # ── Public interface ──────────────────────────────────────────────────────

    async def send_message(self, phone: str, message: str) -> dict:
        """Send a plain text WhatsApp message."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        }
        return await self._post_message(payload, phone)

    async def send_media_message(
        self,
        phone: str,
        media_url: str,
        media_type: str,       # 'image' | 'document'
        caption: str = "",
        filename: str = "document.pdf",
    ) -> dict:
        """
        Send an image or document via Meta WABA using the upload-first strategy.

        Flow:
          1. Check Redis cache for an existing media_id (keyed by md5 of media_url)
          2. If not cached: download the file bytes, upload to Meta, cache the media_id
          3. Send the message referencing the media_id
        """
        meta_type = _MEDIA_TYPE_MAP.get(media_type, "document")
        media_id = await self._get_or_upload_media(media_url, meta_type, filename)

        if meta_type == "image":
            media_block = {"id": media_id}
            if caption:
                media_block["caption"] = caption
        else:
            media_block = {"id": media_id, "filename": filename}
            if caption:
                media_block["caption"] = caption

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": meta_type,
            meta_type: media_block,
        }
        return await self._post_message(payload, phone)

    async def send_interactive_message(
        self,
        phone: str,
        body: str,
        buttons: list[dict],
        use_list: bool = False,
        list_items: list[dict] | None = None,
    ) -> dict:
        """
        Send a native WhatsApp interactive message.
        No Content API, no pre-created templates, no ContentSid caching needed.

        Quick-reply (use_list=False):
          buttons = [{"id": "products", "title": "🛍️ Products"}, ...]
          → type: button  (max 3 buttons, WhatsApp limit)

        List-picker (use_list=True):
          list_items = [{"id": "row_xyz", "title": "Item", "description": "Details"}, ...]
          → type: list  (max 10 rows, max 1 section, WhatsApp limit)
        """
        if use_list:
            return await self._send_list_message(phone, body, buttons, list_items or [])
        return await self._send_button_message(phone, body, buttons)



    async def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """
        Validate the X-Hub-Signature-256 header sent by Meta.
        Format: sha256=<hex_digest>
        Uses HMAC-SHA256 of raw payload body with APP_SECRET as the key.
        """
        if not self.app_secret:
            logger.warning("[META] APP_SECRET not set — skipping signature validation")
            return True

        expected = hmac.new(
            self.app_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        # Strip "sha256=" prefix if present
        received = signature.removeprefix("sha256=")
        return hmac.compare_digest(expected, received)

    async def mark_as_read(self, message_id: str) -> None:
        """
        Mark an inbound message as read — shows blue double ticks to sender.
        Non-fatal: failure is logged as a warning only.
        """
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        try:
            async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
                await client.post(self.messages_url, json=payload, headers=self._headers)
            logger.info(f"[META] Marked as read: {message_id}")
        except Exception as e:
            logger.warning(f"[META] mark_as_read failed (non-fatal): {e}")

    async def send_reaction(self, phone: str, message_id: str, emoji: str = "👍") -> None:
        """
        Send an emoji reaction to a specific message.
        Used to acknowledge owner commands (e.g., react 👍 after BROADCAST).
        Non-fatal: failure is logged as a warning only.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "reaction",
            "reaction": {
                "message_id": message_id,
                "emoji": emoji,
            },
        }
        try:
            await self._post_message(payload, phone)
            logger.info(f"[META] Reaction {emoji} sent for msg_id={message_id}")
        except Exception as e:
            logger.warning(f"[META] send_reaction failed (non-fatal): {e}")

    # ── Interactive message helpers ───────────────────────────────────────────

    async def _send_button_message(
        self, phone: str, body: str, buttons: list[dict]
    ) -> dict:
        """Send a quick-reply button message (max 3 buttons)."""
        # Meta button reply_buttons: each needs type, reply.id, reply.title
        action_buttons = [
            {
                "type": "reply",
                "reply": {
                    "id": btn["id"],
                    "title": btn["title"][:20],  # Meta limit: 20 chars
                },
            }
            for btn in buttons[:3]  # Max 3 buttons
        ]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {"buttons": action_buttons},
            },
        }
        return await self._post_message(payload, phone)

    async def _send_list_message(
        self,
        phone: str,
        body: str,
        buttons: list[dict],
        list_items: list[dict],
    ) -> dict:
        """Send a list-picker message (max 10 rows, max 1 section)."""
        section_title = buttons[0]["title"] if buttons else "Options"
        rows = [
            {
                "id": item["id"][:200],
                "title": item["title"][:24],       # Meta limit: 24 chars
                "description": item.get("description", "")[:72],  # Meta limit: 72 chars
            }
            for item in list_items[:10]  # Max 10 rows
        ]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body},
                "action": {
                    "button": "Select",
                    "sections": [
                        {
                            "title": section_title[:24],
                            "rows": rows,
                        }
                    ],
                },
            },
        }
        return await self._post_message(payload, phone)

    # ── Media upload helpers ──────────────────────────────────────────────────

    async def _get_or_upload_media(
        self, source_url: str, media_type: str, filename: str
    ) -> str:
        """
        Return a cached media_id for source_url, or upload it to Meta and cache.
        Redis key: meta:media:{md5(source_url)}, TTL: 25 days (Meta expires at 30).
        """
        from core.redis_client import get_redis

        url_hash = hashlib.md5(source_url.encode()).hexdigest()
        cache_key = f"meta:media:{url_hash}"
        r = get_redis()

        # Check cache first
        cached_id = await r.get(cache_key)
        if cached_id:
            logger.info(f"[META] media_id cache hit for {source_url[:60]}")
            return cached_id if isinstance(cached_id, str) else cached_id.decode()

        # Download the source file
        logger.info(f"[META] Downloading media from {source_url[:60]}")
        async with httpx.AsyncClient(
            timeout=settings.media_download_timeout_seconds,
            follow_redirects=True,
        ) as client:
            resp = await client.get(source_url)
            resp.raise_for_status()
            file_bytes = resp.content
            content_type = resp.headers.get("content-type", "application/octet-stream")

        # Fallback to guessing from filename if content_type is generic
        generic_types = ("application/octet-stream", "application/binary")
        if content_type.split(";")[0].strip().lower() in generic_types:
            guessed_type, _ = mimetypes.guess_type(filename)
            if guessed_type:
                content_type = guessed_type

        # Force valid image mime type if Meta expects an image
        if media_type == "image" and not content_type.startswith("image/"):
            content_type = "image/jpeg"

        # Upload to Meta
        media_id = await self._upload_media(file_bytes, content_type, filename)

        # Cache for 25 days (2_160_000 seconds)
        await r.set(cache_key, media_id, ex=2_160_000)
        logger.info(f"[META] media_id cached: {media_id} for {source_url[:60]}")
        return media_id

    async def _upload_media(
        self, file_bytes: bytes, mime_type: str, filename: str
    ) -> str:
        """
        Upload raw file bytes to Meta's media endpoint.
        Returns the media_id string.
        POST {graph_base}/{version}/{phone_number_id}/media
          multipart/form-data: messaging_product, file (bytes), type
        """
        upload_url = self.media_url
        auth_headers = {"Authorization": f"Bearer {self.access_token}"}

        logger.info(
            f"[META] Uploading media: {len(file_bytes)} bytes, "
            f"type={mime_type}, filename={filename}"
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                upload_url,
                headers=auth_headers,
                data={"messaging_product": "whatsapp", "type": mime_type},
                files={"file": (filename, file_bytes, mime_type)},
            )

        if response.status_code not in (200, 201):
            logger.error(
                f"[META] Media upload failed: "
                f"status={response.status_code} body={response.text[:200]}"
            )
            response.raise_for_status()

        data = response.json()
        media_id = data.get("id", "")
        logger.info(f"[META] Media uploaded successfully: media_id={media_id}")
        return media_id

    # ── Core HTTP helper ───────────────────────────────────────────────────────────

    async def _post_message(self, payload: dict, phone: str) -> dict:
        """
        POST a message payload to the Meta messages endpoint.

        Uses a granular timeout:  connect=10 s, read=30 s  (Meta can be slow).
        Retries up to 3 times on transient ReadTimeout / ConnectTimeout with
        1-second exponential back-off to survive occasional Meta API hiccups
        without crashing the webhook handler.
        """
        timeout = httpx.Timeout(
            connect=10.0,
            read=settings.http_timeout_seconds,  # 30 s default
            write=10.0,
            pool=10.0,
        )
        max_attempts = 3
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        self.messages_url,
                        json=payload,
                        headers=self._headers,
                    )
                break  # success — exit retry loop
            except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                last_exc = exc
                if attempt < max_attempts:
                    wait = 2 ** (attempt - 1)  # 1 s, 2 s
                    logger.warning(
                        f"[META] Timeout on attempt {attempt}/{max_attempts} "
                        f"sending to {phone} — retrying in {wait}s: {exc}"
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        f"[META] All {max_attempts} attempts timed out "
                        f"sending to {phone}: {exc}"
                    )
                    raise

        if response.status_code not in (200, 201):
            logger.error(
                f"[META] send failed → {phone} "
                f"status={response.status_code} "
                f"body={response.text[:300]}"
            )
            response.raise_for_status()

        data = response.json()
        msg_id = ""
        messages = data.get("messages", [])
        if messages:
            msg_id = messages[0].get("id", "")

        logger.info(f"[META] sent → {phone} msg_id={msg_id}")
        return {
            "status": "sent",
            "messageId": msg_id,
            "phone": phone,
        }
