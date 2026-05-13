import logging
from fastapi import Response
from core.config import settings
from services import menu_service
from services.rag_bot import run_bot
from services.messaging_adapter import get_messaging_adapter
from handlers.event import InboundEvent

logger = logging.getLogger(__name__)

class ClientMessageHandler:
    @staticmethod
    async def handle(event: InboundEvent, db) -> Response:
        """Handle menu state machine and RAG bot fallback."""
        adapter = get_messaging_adapter()
        client = event.client
        client_id = str(client.id)
        sender_phone = event.sender_phone
        message_text = event.message_text
        button_payload = event.button_payload
        list_id = event.list_id
        inbound_msg_id = event.inbound_msg_id

        # ── Menu state machine (Priority 4) ───────────────────────────────────
        try:
            menu_handled = await menu_service.handle_menu_input(
                adapter=adapter,
                phone=sender_phone,
                msg=message_text,
                button_payload=button_payload,
                list_id=list_id,
                db=db,
                client_id=client_id,
            )
        except Exception as _menu_exc:
            logger.warning(f"[WA WEBHOOK] menu_service error (recovered): {_menu_exc}")
            try:
                await db.rollback()
            except Exception:
                pass
            menu_handled = False
        else:
            if db.in_transaction():
                try:
                    await db.rollback()
                except Exception:
                    pass

        if menu_handled:
            return Response(status_code=200, content="ok")

        # ── Pass to RAG bot as normal ──────────────────
        if inbound_msg_id and settings.messaging_provider == "meta":
            try:
                await adapter.mark_as_read(inbound_msg_id)
            except Exception:
                pass

        logger.info(f"[WA WEBHOOK] Calling run_bot for {sender_phone} | client_id={client_id} | msg={message_text[:60]}")
        try:
            await run_bot(
                phone=sender_phone,
                raw_message=message_text,
                client_id=client_id,
                db=None,  # run_bot opens its own fresh session
            )
            logger.info(f"[WA WEBHOOK] run_bot completed for {sender_phone}")

            try:
                await menu_service.send_main_menu(adapter, sender_phone)
            except Exception as menu_exc:
                logger.warning(f"[WA WEBHOOK] post-RAG menu failed (non-fatal): {menu_exc}")

        except Exception as bot_exc:
            logger.error(
                f"[WA WEBHOOK] run_bot CRASHED for {sender_phone}: "
                f"{type(bot_exc).__name__}: {bot_exc}",
                exc_info=True,
            )
            try:
                await adapter.send_message(
                    phone=sender_phone,
                    message="Sorry, something went wrong on our end. Please try again in a moment! 🙏",
                )
            except Exception:
                pass

        return Response(status_code=200, content="ok")
