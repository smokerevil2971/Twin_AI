import logging
from fastapi import Response
from sqlalchemy import select, func
from core.database import get_db_context
from core.config import settings
from models.models import Client, Broadcast, BroadcastRecipient
from services.messaging_adapter import get_messaging_adapter
from handlers.owner_commands.base import BaseCommand, CommandPayload, register_command

logger = logging.getLogger(__name__)

@register_command(r"/help", exact=True)
class HelpCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        await adapter.send_message(
            phone=payload.sender_phone,
            message=(
                f"🤖 *{settings.business_name} Admin Bot — Quick Guide*\n\n"
                "🛍️ *MANAGE MENU*\n"
                "• Add Product:\n `PRODUCT: Fan | 1500 | Desc`\n"
                "• Update Price:\n `UPDATE PRODUCT: Fan | 1600`\n"
                "• Add Offer:\n `OFFER: Sale | 10% off`\n"
                "• Delete:\n `DEL PRODUCT: Fan` | `DEL OFFER: Sale`\n"
                "• View All: `/products` | `/offers`\n\n"
                "📢 *BROADCASTS*\n"
                "• Send:\n `BROADCAST: Msg`\n"
                "• Schedule:\n `SCHEDULE: YYYY-MM-DD HH:MM Msg`\n"
                "• Cancel:\n `CANCEL BROADCAST: Name`\n"
                "• View Recent: `/broadcasts`\n\n"
                "👥 *CLIENTS*\n"
                "• Add:\n `ADD: xxxxxxxxxx, Name`\n"
                "• Remove:\n `REMOVE: xxxxxxxxxx`\n\n"
                "📁 *UPLOADS (Send file with caption)*\n"
                "• Bulk upload (CSV):\n `products`, `offers`, `clients`\n"
                "• Pretrain bots (PDF):\n `documents`, `products`\n"
                "• View Docs: `/kb`\n\n"
                "📊 *REPORTS*\n"
                "• `/analytics` — 7 or 30-day performance\n"
                "• `/status` — General bot stats\n"
                "• `/clients` — Total client count\n"
                "• `/report` — Last broadcast results\n"
                "• `/catalogue=<link>` — Set catalogue link\n\n"
                "📝 _Tip: Ask any normal question to test the AI!_"
            ),
        )
        return Response(status_code=200, content="ok")

@register_command(r"/status", exact=True)
class StatusCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        async with get_db_context() as db:
            total_clients = (await db.execute(
                select(func.count()).where(Client.opted_in == True, Client.is_deleted == False)
            )).scalar_one()
            last_broadcast = (await db.execute(
                select(Broadcast.created_at).order_by(Broadcast.created_at.desc()).limit(1)
            )).scalar_one_or_none()
            lb_str = last_broadcast.strftime("%d-%b %H:%M UTC") if last_broadcast else "None yet"
        await adapter.send_message(
            phone=payload.sender_phone,
            message=(
                f"📊 *{settings.business_name} Status*\n\n"
                f"👥 Opted-in clients: *{total_clients}*\n"
                f"📤 Last broadcast: *{lb_str}*\n\n"
                f"Type `/help` to see all commands & formats."
            ),
        )
        return Response(status_code=200, content="ok")

@register_command(r"/clients", exact=True)
class ClientsCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        async with get_db_context() as db:
            count = (await db.execute(
                select(func.count()).where(Client.opted_in == True, Client.is_deleted == False)
            )).scalar_one()
        await adapter.send_message(phone=payload.sender_phone, message=f"👥 Opted-in clients: {count}")
        return Response(status_code=200, content="ok")

@register_command(r"/report", exact=True)
class ReportCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        async with get_db_context() as db:
            stmt = select(Broadcast).order_by(Broadcast.created_at.desc()).limit(1)
            latest_broadcast = (await db.execute(stmt)).scalar_one_or_none()

            if not latest_broadcast:
                await adapter.send_message(phone=payload.sender_phone, message="No broadcasts found.")
                return Response(status_code=200, content="ok")

            stats_stmt = select(BroadcastRecipient.status, func.count(BroadcastRecipient.id)).where(
                BroadcastRecipient.broadcast_id == latest_broadcast.id
            ).group_by(BroadcastRecipient.status)
            stats = dict((await db.execute(stats_stmt)).all())

            sent_count      = stats.get("sent", 0) + stats.get("delivered", 0) + stats.get("read", 0)
            delivered_count = stats.get("delivered", 0) + stats.get("read", 0)
            read_count      = stats.get("read", 0)
            failed_count    = stats.get("failed", 0)

            report_msg = (
                f"📊 *Last Broadcast Report*\n\n"
                f"🏷️ Name: {latest_broadcast.name}\n"
                f"📅 Date: {latest_broadcast.created_at.strftime('%d %b, %H:%M')}\n\n"
                f"📤 Sent: {sent_count}\n"
                f"✅ Delivered: {delivered_count}\n"
                f"👁️ Read: {read_count}\n"
                f"❌ Failed: {failed_count}"
            )
        await adapter.send_message(phone=payload.sender_phone, message=report_msg)
        return Response(status_code=200, content="ok")

@register_command(r"/catalogue\s*=\s*(.+)")
class CatalogueCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        new_url = payload.match.group(1).strip()
        from core.redis_client import get_redis
        r = get_redis()
        await r.set(settings.catalogue_redis_key, new_url)
        await adapter.send_message(
            phone=payload.sender_phone,
            message=f"✅ Catalogue URL updated successfully to:\n{new_url}",
        )
        return Response(status_code=200, content="ok")
