"""
Mock Gupshup adapter — used during development while awaiting Meta approval.
Swap to RealGupshupAdapter by setting GUPSHUP_MODE=real in .env.

All outbound calls are logged. Mock returns success for every message.
"""
import logging
from abc import ABC, abstractmethod
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)


class GupshupAdapter(ABC):
    @abstractmethod
    async def send_message(self, phone: str, message: str) -> dict:
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
        return {
            "status": "submitted",
            "messageId": mock_id,
            "phone": phone,
        }

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
        self.client = httpx.AsyncClient(base_url="https://api.gupshup.io", timeout=10.0)

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

    async def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        import hmac
        import hashlib
        expected = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


def get_gupshup_adapter() -> GupshupAdapter:
    """FastAPI dependency — returns mock or real adapter based on GUPSHUP_MODE env var."""
    from core.config import settings
    if settings.gupshup_mode == "real":
        return RealGupshupAdapter(
            api_key=settings.gupshup_api_key,
            app_name=settings.gupshup_app_name,
            sender=settings.gupshup_sender_number,
            webhook_secret=settings.gupshup_webhook_secret,
        )
    return MockGupshupAdapter()
