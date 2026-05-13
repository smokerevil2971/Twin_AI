import logging
from fastapi import Response
from core.config import settings
from core.redis_client import (
    get_onboard_state, set_onboard_state, clear_onboard_state,
    ONBOARD_AWAITING_CONSENT, ONBOARD_AWAITING_LANGUAGE, ONBOARD_AWAITING_NAME,
)
from services import menu_service
from services.messaging_adapter import get_messaging_adapter
from handlers.event import InboundEvent

logger = logging.getLogger(__name__)

class OnboardingHandler:
    @staticmethod
    async def handle(event: InboundEvent, db) -> Response:
        """Handle onboarding flow (Consent, Language, Name)."""
        adapter = get_messaging_adapter()
        client = event.client
        sender_phone = event.sender_phone
        message_text = event.message_text
        button_payload = event.button_payload

        # ── 1.1 First contact — brand new (or returning deleted) client ───
        if client is None or client.is_deleted:
            if client is None:
                from models.models import Client
                client = Client(
                    name=sender_phone,
                    phone=sender_phone,
                    opted_in=False,
                    language="en",
                )
                db.add(client)
            else:
                client.is_deleted = False
                client.opted_in = False

            await db.commit()
            await db.refresh(client)
            logger.info(f"[ONBOARD] Client onboard started: {sender_phone}")

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
                await set_onboard_state(sender_phone, ONBOARD_AWAITING_NAME)
                await adapter.send_message(
                    phone=sender_phone,
                    message="बढ़िया! 🎉 आपका नाम क्या है? 😊\n(_हम आपका बेहतर तरीके से साथ देना चाहते हैं_)",
                )
            elif is_english:
                client.language = "en"
                await db.commit()
                logger.info(f"[ONBOARD] {sender_phone} language set to English")
                await set_onboard_state(sender_phone, ONBOARD_AWAITING_NAME)
                await adapter.send_message(
                    phone=sender_phone,
                    message="Great! 🎉 One last thing — what's your name? 😊\n_(So we can personalise your experience)_",
                )
            else:
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
                await adapter.send_message(
                    phone=sender_phone,
                    message="Please share your name so we can personalise your experience 😊",
                )
            return Response(status_code=200, content="ok")

        # If it reaches here without returning, the client is fully onboarded.
        # So we return None to let the router pass it to ClientHandler.
        return None
