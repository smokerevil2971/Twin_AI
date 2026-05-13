import logging
import uuid
from fastapi import Response
from sqlalchemy import select
from core.database import AsyncSessionLocal
from services import command_service
from services.messaging_adapter import get_messaging_adapter
from handlers.event import InboundEvent

logger = logging.getLogger(__name__)

class OwnerHandler:
    @staticmethod
    async def handle(event: InboundEvent) -> Response:
        """Handle incoming messages from the owner."""
        # 3.5: Handle offer expiry button taps BEFORE command dispatch
        if event.button_payload.startswith("broadcast_expiry_") or event.button_payload.startswith("skip_expiry_"):
            adapter = get_messaging_adapter()
            try:
                offer_id_str = event.button_payload.split("_", 2)[-1]
                from models.models import Offer
                from services.broadcast_service import create_broadcast

                # Parse offer_id_str to uuid.UUID before querying.
                try:
                    offer_uuid = uuid.UUID(offer_id_str)
                except ValueError:
                    logger.warning(f"[EXPIRY] Invalid offer UUID in button payload: {offer_id_str!r}")
                    return Response(status_code=200, content="ok")

                async with AsyncSessionLocal() as _db:
                    offer = (await _db.execute(
                        select(Offer).where(Offer.id == offer_uuid)
                    )).scalar_one_or_none()

                if event.button_payload.startswith("broadcast_expiry_") and offer:
                    # Auto-create a broadcast for this expiring offer
                    offer_desc = offer.description or "Don’t miss out — contact us today!"
                    msg_text = (
                        f"⏰ *Last chance!* Our offer *\"{offer.title}\"* expires soon.\n\n"
                        f"{offer_desc}\n\n"
                        f"_Reply *ORDER* to place your order now!_"
                    )
                    async with AsyncSessionLocal() as _db:
                        bc = await create_broadcast(
                            db=_db,
                            name=f"Expiry reminder: {offer.title[:40]}",
                            message_template=msg_text,
                            override_cooldown=False,
                        )
                        from tasks.broadcast_tasks import send_broadcast
                        send_broadcast.delay(str(bc["id"]))
                    await adapter.send_message(
                        phone=event.sender_phone,
                        message=f"✅ Broadcast queued for offer expiry: *\"{offer.title}\"*",
                    )
                    logger.info(f"[EXPIRY] Owner approved broadcast for: {offer.title}")
                elif event.button_payload.startswith("skip_expiry_"):
                    await adapter.send_message(
                        phone=event.sender_phone,
                        message=f"✅ Skipped — no broadcast sent for this offer.",
                    )
            except Exception as exc:
                logger.error(f"[EXPIRY] Button handler failed: {exc}", exc_info=True)
            return Response(status_code=200, content="ok")

        try:
            cmd_response = await command_service.dispatch_owner_command(
                msg=event.message_text.strip(),
                sender_phone=event.sender_phone,
                media_url=event.media_url,
                media_type=event.media_type,
                base_url=event.base_url,
                message_id=event.inbound_msg_id,
                button_payload=event.button_payload,
            )
            if cmd_response is not None:
                return cmd_response
            
            # None return means owner is testing the RAG bot — fall through below
            logger.info(f"[WA WEBHOOK] Owner testing RAG bot: {event.message_text[:60]}")
            
            # Since owner is testing RAG bot, let it pass to client handler
            from handlers.client import ClientHandler
            return await ClientHandler.handle(event, db=None)
            
        except Exception as exc:
            logger.error(f"[WA WEBHOOK] dispatch_owner_command CRASHED: {exc}", exc_info=True)
            try:
                adapter = get_messaging_adapter()
                await adapter.send_message(phone=event.sender_phone, message=f"❌ System Error in Owner Command: {str(exc)}")
            except Exception:
                pass
            return Response(status_code=500, content="owner_command_error")
