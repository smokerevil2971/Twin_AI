import re
from datetime import datetime, timezone, timedelta
from fastapi import Response
from sqlalchemy import select, func
from core.database import AsyncSessionLocal
from models.models import Client, Conversation, Broadcast, BroadcastRecipient, Product, Offer
from services.messaging_adapter import get_messaging_adapter
from core.redis_client import get_top_menu_items
from handlers.owner_commands.base import BaseCommand, CommandPayload, register_command

from core.logging import logger

@register_command(r"/analytics(?:\s+(7|30))?")
class AnalyticsCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        analytics_days = int(payload.match.group(1) or 7)
        return await AnalyticsHelper.send_analytics(payload, adapter, analytics_days)

@register_command(r"analytics_(30|7)days", exact=True)
class AnalyticsButtonCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        analytics_days = int(payload.match.group(1))
        return await AnalyticsHelper.send_analytics(payload, adapter, analytics_days)

class AnalyticsHelper:
    @staticmethod
    async def send_analytics(payload: CommandPayload, adapter, analytics_days: int) -> Response:
        cutoff = datetime.now(timezone.utc) - timedelta(days=analytics_days)
        async with AsyncSessionLocal() as db:
            new_clients    = (await db.execute(select(func.count(Client.id)).where(Client.created_at >= cutoff, Client.is_deleted == False))).scalar_one()
            conversations  = (await db.execute(select(func.count()).select_from(Conversation).where(Conversation.created_at >= cutoff))).scalar_one()
            broadcasts_cnt = (await db.execute(select(func.count(Broadcast.id)).where(Broadcast.status == "sent", Broadcast.created_at >= cutoff))).scalar_one()

            best_bc_name = "N/A"
            bc_rows = (await db.execute(
                select(Broadcast).where(Broadcast.status == "sent", Broadcast.created_at >= cutoff)
            )).scalars().all()
            if bc_rows:
                bc_ids = [bc.id for bc in bc_rows]
                all_stats_rows = (await db.execute(
                    select(
                        BroadcastRecipient.broadcast_id,
                        BroadcastRecipient.status,
                        func.count().label("cnt"),
                    )
                    .where(BroadcastRecipient.broadcast_id.in_(bc_ids))
                    .group_by(BroadcastRecipient.broadcast_id, BroadcastRecipient.status)
                )).all()
                stats_map: dict = {}
                for row in all_stats_rows:
                    bid = row.broadcast_id
                    if bid not in stats_map:
                        stats_map[bid] = {}
                    stats_map[bid][row.status] = row.cnt

                best_bc, best_rate = None, -1.0
                for bc in bc_rows:
                    s = stats_map.get(bc.id, {})
                    total_s = sum(s.values())
                    read_r = (s.get("read", 0) / total_s * 100) if total_s else 0.0
                    if read_r > best_rate:
                        best_rate, best_bc = read_r, bc
                if best_bc:
                    best_bc_name = f'"{best_bc.name[:30]}" ({int(best_rate)}% read)'

            top_products = await get_top_menu_items("product", 1)
            top_offers   = await get_top_menu_items("offer", 1)

            top_prod_str = "N/A"
            if top_products:
                pid, ptaps = top_products[0]
                prod = (await db.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
                if prod:
                    top_prod_str = f'"{prod.name}" ({ptaps} taps)'

            top_offer_str = "N/A"
            if top_offers:
                oid, otaps = top_offers[0]
                offr = (await db.execute(select(Offer).where(Offer.id == oid))).scalar_one_or_none()
                if offr:
                    top_offer_str = f'"{offr.title}" ({otaps} taps)'

        stats_text = (
            f"📈 *Analytics — Last {analytics_days} Days*\n\n"
            f"👥 New clients:      *{new_clients}*\n"
            f"💬 Conversations:    *{conversations}*\n"
            f"📤 Broadcasts sent:  *{broadcasts_cnt}*\n\n"
            f"🏆 *Top Performers*\n"
            f"📢 Best Broadcast: {best_bc_name}\n"
            f"🛍️ Top Product:    {top_prod_str}\n"
            f"💰 Top Offer:      {top_offer_str}"
        )
        await adapter.send_message(phone=payload.sender_phone, message=stats_text)

        other_days   = 30 if analytics_days == 7 else 7
        toggle_label = f"📅 View Last {other_days} Days"
        toggle_id    = f"analytics_{other_days}days"
        await adapter.send_interactive_message(
            phone=payload.sender_phone,
            body="Switch time window:",
            buttons=[{"id": toggle_id, "title": toggle_label}],
            use_list=False,
        )
        return Response(status_code=200, content="ok")


