"""
Messaging adapter base — provider-agnostic interface.

Swap between providers via MESSAGING_PROVIDER env var:
  meta    → MetaWABAAdapter   (primary / production)
  twilio  → TwilioAdapter     (sandbox / secondary)
  mock    → MockMessagingAdapter (local dev, no real API calls)
"""
import logging
import uuid
from abc import ABC, abstractmethod

from core.config import settings

logger = logging.getLogger(__name__)


class MessagingAdapter(ABC):
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
    async def send_interactive_message(
        self,
        phone: str,
        body: str,
        buttons: list[dict],
        use_list: bool = False,
        list_items: list[dict] | None = None,
    ) -> dict:
        """
        Send a WhatsApp interactive message.

        For quick-reply (use_list=False):
          buttons = [{"id": "products", "title": "🛍️ Products"}, ...]

        For list-picker (use_list=True):
          list_items = [{"id": "row_xyz", "title": "Item Name", "description": "Details"}, ...]
          buttons[0]["title"] is used as the list header/section title.
        """
        ...

    @abstractmethod
    async def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        ...

    # ── Optional Meta-only methods (default no-ops for non-Meta adapters) ───────

    async def mark_as_read(self, message_id: str) -> None:
        """Mark an inbound message as read (shows blue double ticks). Meta only."""
        pass

    async def send_reaction(self, phone: str, message_id: str, emoji: str = "👍") -> None:
        """React to a message with an emoji. Meta only."""
        pass


class MockMessagingAdapter(MessagingAdapter):
    """Safe no-op adapter. Logs all calls. Returns fake success responses."""

    async def send_message(self, phone: str, message: str) -> dict:
        mock_id = str(uuid.uuid4())
        logger.info(f"[MOCK] send_message → {phone} | msg_id={mock_id}")
        logger.info(f"[MOCK] message preview: {message[:80]}...")
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
            f"[MOCK] send_media_message → {phone} | "
            f"type={media_type} url={media_url[:60]} | msg_id={mock_id}"
        )
        return {"status": "submitted", "messageId": mock_id, "phone": phone}

    async def send_interactive_message(
        self,
        phone: str,
        body: str,
        buttons: list[dict],
        use_list: bool = False,
        list_items: list[dict] | None = None,
    ) -> dict:
        """Mock: log the call and fall back to sending body as plain text."""
        items = list_items or buttons
        labels = ", ".join(i.get("title", "") for i in items[:5])
        logger.info(f"[MOCK] send_interactive_message → {phone} | items: {labels}")
        return await self.send_message(phone=phone, message=f"{body}\n\n{labels}")

    async def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        logger.info("[MOCK] verify_webhook_signature → always True in mock mode")
        return True

    async def mark_as_read(self, message_id: str) -> None:
        logger.info(f"[MOCK] mark_as_read → msg_id={message_id}")

    async def send_reaction(self, phone: str, message_id: str, emoji: str = "👍") -> None:
        logger.info(f"[MOCK] send_reaction → {phone} emoji={emoji} msg_id={message_id}")


def get_messaging_adapter() -> MessagingAdapter:
    """
    FastAPI dependency / direct call — returns the correct messaging
    adapter based on MESSAGING_PROVIDER env var.

    MESSAGING_PROVIDER=meta    → MetaWABAAdapter (primary)
    MESSAGING_PROVIDER=twilio  → TwilioAdapter   (sandbox fallback)
    MESSAGING_PROVIDER=mock    → MockMessagingAdapter (local dev)
    """
    from core.config import settings

    if settings.messaging_provider == "meta":
        from services.meta_waba_adapter import MetaWABAAdapter
        return MetaWABAAdapter(
            phone_number_id=settings.meta_phone_number_id,
            access_token=settings.meta_access_token,
            app_secret=settings.meta_app_secret,
            api_version=settings.meta_api_version,
        )

    if settings.messaging_provider == "twilio":
        from services.twilio_adapter import TwilioAdapter
        return TwilioAdapter(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_number=settings.twilio_whatsapp_number,
        )

    # Default: mock (safe for local dev)
    return MockMessagingAdapter()
