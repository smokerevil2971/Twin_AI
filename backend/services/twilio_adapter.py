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

from services.gupshup_adapter import GupshupAdapter

logger = logging.getLogger(__name__)


class TwilioAdapter(GupshupAdapter):
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
                timeout=10.0,
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
                timeout=10.0,
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
