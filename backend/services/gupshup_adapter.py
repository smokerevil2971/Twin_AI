"""
Messaging adapters — Gupshup (Mock + Real) + interface definition.

Swap between providers via MESSAGING_PROVIDER and GUPSHUP_MODE env vars.
Both send_message() and send_media_message() are supported.
"""
import logging
from abc import ABC, abstractmethod
import uuid
from typing import Optional

from core.config import settings

logger = logging.getLogger(__name__)


class GupshupAdapter(ABC):
    """Base interface for all messaging adapters."""

    @abstractmethod
    async def send_message(self, phone: str, message: str) -> dict:
        """Send a plain text WhatsApp message."""
        ...

    @abstractmethod
    async def send_media_message(
        self,
        phone: str,
        media_url: str,
        media_type: str,          # 'image' | 'document'
        caption: str = "",
        filename: str = "document.pdf",
    ) -> dict:
        """Send a media (image or document) WhatsApp message with optional caption."""
        ...

    @abstractmethod
    async def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        ...


class MockGupshupAdapter(GupshupAdapter):
    """Safe no-op adapter. Logs all calls. Returns fake success responses."""

    async def send_message(self, phone: str, message: str) -> dict:
        mock_id = str(uuid.uuid4())
        logger.info(f"[MOCK GUPSHUP] send_message → {phone} | msg_id={mock_id}")
        logger.info(f"[MOCK GUPSHUP] message preview: {message[:80]}...")
        return {"status": "submitted", "messageId": mock_id, "phone": phone}

    async def send_media_message(
        self,
        phone: str,
        media_url: str,
        media_type: str,
        caption: str = "",
        filename: str = "document.pdf",
    ) -> dict:
        mock_id = str(uuid.uuid4())
        logger.info(
            f"[MOCK GUPSHUP] send_media_message → {phone} | "
            f"type={media_type} url={media_url[:60]} | msg_id={mock_id}"
        )
        return {"status": "submitted", "messageId": mock_id, "phone": phone}

    async def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        logger.info("[MOCK GUPSHUP] verify_webhook_signature → always True in mock mode")
        return True


class RealGupshupAdapter(GupshupAdapter):
    """Real Gupshup API — activate by setting GUPSHUP_MODE=real in .env"""

    def __init__(self, api_key: str, app_name: str, sender: str, webhook_secret: str):
        import httpx
        self.api_key = api_key
        self.app_name = app_name
        self.sender = sender
        self.webhook_secret = webhook_secret
        self.client = httpx.AsyncClient(base_url="https://api.gupshup.io", timeout=settings.http_timeout_seconds)

    async def send_message(self, phone: str, message: str) -> dict:
        import httpx
        response = await self.client.post(
            "/sm/api/v1/msg",
            data={
                "channel": "whatsapp",
                "source": self.sender,
                "destination": phone,
                "message": message,
                "src.name": self.app_name,
            },
            headers={"apikey": self.api_key},
        )
        response.raise_for_status()
        return response.json()

    async def send_media_message(
        self,
        phone: str,
        media_url: str,
        media_type: str,
        caption: str = "",
        filename: str = "document.pdf",
    ) -> dict:
        """
        Send image or document via Gupshup.
        Gupshup media message format:
          message = JSON string with type, originalUrl, caption/filename
        """
        import json
        import httpx

        if media_type == "image":
            msg_payload = json.dumps({
                "type": "image",
                "originalUrl": media_url,
                "caption": caption,
            })
        else:  # document
            msg_payload = json.dumps({
                "type": "file",
                "url": media_url,
                "filename": filename,
                "caption": caption,
            })

        response = await self.client.post(
            "/sm/api/v1/msg",
            data={
                "channel": "whatsapp",
                "source": self.sender,
                "destination": phone,
                "message": msg_payload,
                "src.name": self.app_name,
            },
            headers={"apikey": self.api_key},
        )
        response.raise_for_status()
        return response.json()

    async def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        import hmac
        import hashlib
        expected = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


def get_messaging_adapter() -> GupshupAdapter:
    """
    FastAPI dependency — returns the correct messaging
    adapter based on MESSAGING_PROVIDER env var.

    MESSAGING_PROVIDER=twilio  → TwilioAdapter
    MESSAGING_PROVIDER=gupshup + GUPSHUP_MODE=real → RealGupshupAdapter
    MESSAGING_PROVIDER=gupshup + GUPSHUP_MODE=mock → MockGupshupAdapter
    """
    from core.config import settings
    if settings.messaging_provider == "twilio":
        from services.twilio_adapter import TwilioAdapter
        return TwilioAdapter(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_number=settings.twilio_whatsapp_number,
        )
    if settings.gupshup_mode == "real":
        return RealGupshupAdapter(
            api_key=settings.gupshup_api_key,
            app_name=settings.gupshup_app_name,
            sender=settings.gupshup_sender_number,
            webhook_secret=settings.gupshup_webhook_secret,
        )
    return MockGupshupAdapter()


# Keep old name as alias so nothing breaks
get_gupshup_adapter = get_messaging_adapter
