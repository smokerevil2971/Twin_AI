import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import httpx
from fastapi import Response
from sqlalchemy import select
from core.config import settings
from core.database import get_db_context, AsyncSessionLocal
from models.models import Broadcast
from services.broadcast_service import create_broadcast
from services.messaging_adapter import get_messaging_adapter
from tasks.broadcast_tasks import send_broadcast
from handlers.owner_commands.base import BaseCommand, CommandPayload, register_command

from core.logging import logger

@register_command(r"/broadcasts?")
class BroadcastsCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(Broadcast).order_by(Broadcast.created_at.desc()).limit(5)
            )).scalars().all()
            if not rows:
                await adapter.send_message(phone=payload.sender_phone, message="No broadcasts found yet.")
            else:
                lines = ["📋 *Last 5 Broadcasts*"]
                for i, b in enumerate(rows, 1):
                    date = b.created_at.strftime("%d %b, %H:%M")
                    preview = (b.message_template or "")[:80].strip()
                    if len(b.message_template or "") > 80:
                        preview += "..."
                    media_tag = " 📎" if b.media_url else ""
                    lines.append(
                        f"\n{i}.{media_tag} 📅 *{date}* | `{b.status}`\n"
                        f"   _{preview}_"
                    )
                await adapter.send_message(phone=payload.sender_phone, message="\n".join(lines))
        return Response(status_code=200, content="ok")

@register_command(r"cancel\s+broadcast:\s*(.+)")
class CancelBroadcastCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        partial = payload.match.group(1).strip()
        async with AsyncSessionLocal() as db:
            results = (await db.execute(
                select(Broadcast).where(
                    Broadcast.name.ilike(f"%{partial}%"),
                    Broadcast.status.in_(["draft", "sending", "pending"]),
                ).limit(5)
            )).scalars().all()
            if not results:
                await adapter.send_message(
                    phone=payload.sender_phone,
                    message=f"⚠️ No active broadcast found matching: *{partial}*\nCheck `/broadcasts` for names.",
                )
            elif len(results) == 1:
                b = results[0]
                b.status = "cancelled"
                await db.commit()
                await adapter.send_message(
                    phone=payload.sender_phone,
                    message=f"🗑️ Broadcast *'{b.name}'* cancelled successfully.",
                )
                if payload.message_id:
                    await adapter.send_reaction(payload.sender_phone, payload.message_id, "👍")
                logger.info(f"[CMD] Broadcast cancelled: {b.name}")
            else:
                names = "\n".join(f"• {b.name}" for b in results)
                await adapter.send_message(
                    phone=payload.sender_phone,
                    message=f"⚠️ Multiple matches found — be more specific:\n\n{names}",
                )
        return Response(status_code=200, content="ok")

@register_command(r"schedule:\s*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s+(.+)")
class ScheduleCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        date_str, time_str, broadcast_msg = payload.match.groups()
        broadcast_msg = broadcast_msg.strip()
        IST = ZoneInfo("Asia/Kolkata")
        try:
            scheduled_dt_ist = datetime.strptime(
                f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=IST)
            scheduled_dt_utc = scheduled_dt_ist.astimezone(timezone.utc)
        except ValueError:
            await adapter.send_message(
                phone=payload.sender_phone,
                message="❌ Invalid format. Use:\nSCHEDULE: YYYY-MM-DD HH:MM Your message here",
            )
            return Response(status_code=200, content="ok")

        logger.info(f"[CMD] Scheduling broadcast for {scheduled_dt_ist}: {broadcast_msg[:40]}")
        async with get_db_context() as db:
            try:
                result = await create_broadcast(
                    db=db,
                    name=f"Scheduled {date_str} {time_str} — {broadcast_msg[:25]}",
                    message_template=broadcast_msg,
                    channel="whatsapp",
                    scheduled_at=scheduled_dt_utc,
                )
                broadcast_id = result["id"]
                eligible_count = result["eligible_count"]
                send_broadcast.apply_async(args=[broadcast_id], eta=scheduled_dt_utc)
                display_time = scheduled_dt_ist.strftime("%d-%b-%Y at %I:%M %p")
                preview = broadcast_msg[:60] + ("..." if len(broadcast_msg) > 60 else "")
                await adapter.send_message(
                    phone=payload.sender_phone,
                    message=(
                        f"🕐 Broadcast scheduled for {display_time} "
                        f"for {eligible_count} client(s).\n\"{preview}\""
                    ),
                )
                logger.info(f"[CMD] Scheduled {broadcast_id} for {display_time}")
            except Exception as exc:
                logger.error(f"[CMD] Failed to schedule: {exc}", exc_info=True)
                try:
                    await adapter.send_message(phone=payload.sender_phone, message="❌ Scheduling failed. Check server logs for details.")
                except Exception:
                    pass
        return Response(status_code=200, content="ok")

@register_command(r"broadcast(?:\s*\(urgent\))?:\s*(.+)")
class BroadcastTextCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        # Only execute if no media is attached, media is handled separately
        if payload.media_url:
            return None

        adapter = get_messaging_adapter()
        urgent = bool(re.search(r"\(urgent\)", payload.msg, re.IGNORECASE))
        broadcast_msg = payload.match.group(1).strip()
        logger.info(f"[CMD] Owner triggered {'URGENT ' if urgent else ''}broadcast: {broadcast_msg[:60]}")
        async with get_db_context() as db:
            try:
                result = await create_broadcast(
                    db=db,
                    name=f"WhatsApp broadcast {broadcast_msg[:30]}",
                    message_template=broadcast_msg,
                    channel="whatsapp",
                    override_cooldown=urgent,
                )
                broadcast_id = result["id"]
                eligible_count = result["eligible_count"]
                send_broadcast.delay(broadcast_id)
                preview = broadcast_msg[:60] + ("..." if len(broadcast_msg) > 60 else "")
                urgent_label = " *(urgent — cooldown skipped)*" if urgent else ""
                await adapter.send_message(
                    phone=payload.sender_phone,
                    message=f"✅ Broadcast queued for *{eligible_count}* client(s){urgent_label}:\n\"{preview}\"",
                )
                if payload.message_id:
                    await adapter.send_reaction(payload.sender_phone, payload.message_id, "👍")
                logger.info(f"[CMD] Queued broadcast {broadcast_id} for {eligible_count} clients")
            except Exception as exc:
                logger.error(f"[CMD] Failed to create broadcast: {exc}", exc_info=True)
                try:
                    await adapter.send_message(phone=payload.sender_phone, message="❌ Broadcast failed. Check server logs for details.")
                except Exception:
                    pass
        return Response(status_code=200, content="ok")
