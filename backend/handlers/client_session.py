import re
from datetime import timezone
from fastapi import Response
from sqlalchemy import select
from core.config import settings
from core.redis_client import set_onboard_state, ONBOARD_AWAITING_LANGUAGE
from services import menu_service
from services.messaging_adapter import get_messaging_adapter
from handlers.event import InboundEvent

from core.logging import logger

class ClientSessionHandler:
    @staticmethod
    async def handle(event: InboundEvent, db) -> Response | None:
        """Handle predefined commands like STOP, START, MENU, CATALOGUE, etc."""
        adapter = get_messaging_adapter()
        client = event.client
        sender_phone = event.sender_phone
        message_text = event.message_text
        button_payload = event.button_payload
        msg_upper = message_text.strip().upper()

        # ── Handle STOP / START self-service opt commands ─────
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

        # ── Catalogue ─────────────────────
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

        # ── Explicit Menu & Greetings ────────────────────────
        cleaned_msg = re.sub(r'[^\w\s]', '', msg_upper).strip()
        basic_greetings = {
            "HI", "HELLO", "HEY", "GOOD MORNING", "GOOD AFTERNOON", 
            "GOOD EVENING", "HI THERE", "HELLO SIR", "HI SIR", "HEY THERE", 
            "NAMASTE", "HALLO", "HII", "HIIO", "HELO"
        }
        
        if cleaned_msg == "MENU" or cleaned_msg in basic_greetings:
            await menu_service.clear_menu_state(sender_phone)
            
            if cleaned_msg != "MENU":
                greeting_msg = (
                    f"Hello! Welcome to *{settings.business_name}*. 🏢\n\n"
                    f"I am your AI assistant, ready to answer your questions and help you with our latest products and offers. 😊"
                )
                await adapter.send_message(phone=sender_phone, message=greeting_msg)
            
            await menu_service.send_main_menu(adapter, sender_phone)
            logger.info(f"[MENU] {sender_phone} greeted/requested menu directly: {cleaned_msg}")
            return Response(status_code=200, content="ok")

        # ── MY ORDERS self-service ────────────────────────────────────────────────────────────────────
        if msg_upper in ("MY ORDERS", "MY ORDER", "ORDERS", "ORDER HISTORY", "MY ENQUIRIES"):
            from models.models import Conversation
            from core.database import AsyncSessionLocal
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
                        dt_utc = conv.created_at.replace(tzinfo=timezone.utc) if not conv.created_at.tzinfo else conv.created_at
                        dt_ist = dt_utc.astimezone(IST)
                        date = dt_ist.strftime("%d %b, %I:%M %p")
                        question = (conv.message or "").strip()
                        
                        if question.upper() == "ORDER":
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

        # ── Language switch mid-session ──────────────────────────────────────────────────────────────
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
            await set_onboard_state(sender_phone, ONBOARD_AWAITING_LANGUAGE)
            return Response(status_code=200, content="ok")

        # Not a session command, fall through
        return None
