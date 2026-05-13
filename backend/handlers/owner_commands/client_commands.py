import logging
from fastapi import Response
from sqlalchemy import select
from core.database import AsyncSessionLocal
from models.models import Client
from services.messaging_adapter import get_messaging_adapter
from handlers.owner_commands.base import BaseCommand, CommandPayload, register_command

logger = logging.getLogger(__name__)

def _normalise_phone(raw: str) -> str:
    import re
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+91{digits}"
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    return f"+{digits}" if not raw.strip().startswith("+") else raw.strip()

@register_command(r"add:\s*(\+?\d[\d\s\-]{7,15})\s*,\s*(.+)")
class AddClientCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        raw_phone, name = payload.match.group(1).strip(), payload.match.group(2).strip()
        phone = _normalise_phone(raw_phone)
        try:
            async with AsyncSessionLocal() as db:
                existing = (await db.execute(
                    select(Client).where(Client.phone == phone)
                )).scalar_one_or_none()

                if existing and not existing.is_deleted:
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message=f"⚠️ Client already exists:\n👤 {existing.name} ({phone})",
                    )
                elif existing and existing.is_deleted:
                    existing.is_deleted = False
                    existing.opted_in = True
                    existing.name = name
                    await db.commit()
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message=f"✅ Client re-activated & opted-in:\n👤 *{name}*\n📞 {phone}",
                    )
                    logger.info(f"[CMD] Re-activated client: {name} ({phone})")
                else:
                    client = Client(name=name, phone=phone, opted_in=True)
                    db.add(client)
                    await db.commit()
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message=f"✅ Client added & opted-in:\n👤 *{name}*\n📞 {phone}",
                    )
                    logger.info(f"[CMD] Added client: {name} ({phone})")
        except Exception as exc:
            logger.error(f"[CMD] ADD: failed: {exc}", exc_info=True)
            await adapter.send_message(phone=payload.sender_phone, message="❌ Failed to add client. Check server logs for details.")
        return Response(status_code=200, content="ok")

@register_command(r"remove:\s*(\+?\d[\d\s\-]{7,15})")
class RemoveClientCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        raw_phone = payload.match.group(1).strip()
        phone = _normalise_phone(raw_phone)
        phone_no_plus = phone.lstrip("+")
        try:
            async with AsyncSessionLocal() as db:
                client = (await db.execute(
                    select(Client).where(
                        Client.phone.in_([phone, phone_no_plus]),
                        Client.is_deleted == False,
                    )
                )).scalar_one_or_none()
                if not client:
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message=f"⚠️ No active client found for {phone}",
                    )
                else:
                    client_name = client.name
                    client.is_deleted = True
                    client.opted_in = False
                    await db.commit()
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message=f"🗑️ Client removed:\n👤 *{client_name}* ({phone})",
                    )
                    logger.info(f"[CMD] Removed client: {client_name} ({phone})")
        except Exception as exc:
            logger.error(f"[CMD] REMOVE: failed: {exc}", exc_info=True)
            await adapter.send_message(phone=payload.sender_phone, message="❌ Failed to remove client. Check server logs for details.")
        return Response(status_code=200, content="ok")
