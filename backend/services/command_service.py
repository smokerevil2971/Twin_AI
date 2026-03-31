"""
Owner Command Service — Phase 2 Refactor

Extracts all owner command handlers from the monolithic webhooks.py into a
dedicated, testable service module. The webhook route now calls a single
`dispatch_owner_command(...)` entry point and returns the FastAPI Response.

Supported commands:
  /help, /status, /clients, /report, /catalogue=<url>
  BROADCAST: <msg>
  SCHEDULE: YYYY-MM-DD HH:MM <msg>
  ADD: <phone>, <name>
  REMOVE: <phone>
  <CSV/XLSX media>  → bulk client import
  <PDF/DOCX/TXT media>  → knowledge base ingestion
  Anything else → falls through to the RAG bot
"""
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import Response
from sqlalchemy import select, func

from core.config import settings
from core.database import get_db_context, AsyncSessionLocal
from models.models import Broadcast, BroadcastRecipient, Client
from services.broadcast_service import create_broadcast
from services.client_service import import_clients, parse_upload_file, detect_column_mapping
from services.gupshup_adapter import get_messaging_adapter
from services import knowledge_service
from tasks.broadcast_tasks import send_broadcast

logger = logging.getLogger(__name__)


# ─── MIME type sets ───────────────────────────────────────────────────────────

_CLIENT_SHEET_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_INGESTABLE_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
    "text/markdown",
}

_KB_EXT_MAP = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "text/plain": ".txt",
    "text/markdown": ".md",
}


# ─── Entry point (called by webhooks.py) ─────────────────────────────────────

async def dispatch_owner_command(
    msg: str,
    sender_phone: str,
    media_url: str = "",
    media_type: str = "",
    base_url: str = "",
) -> Optional[Response]:
    """
    Routes an inbound owner WhatsApp message to the correct handler.

    Returns a FastAPI Response if the command was handled, or None to signal
    that the message should fall through to the RAG bot (owner testing mode).
    """
    adapter = get_messaging_adapter()

    # ── /help ─────────────────────────────────────────────────────────────────
    if msg.lower() == "/help":
        await adapter.send_message(
            phone=sender_phone,
            message=(
                "🤖 *TwinAI Owner Bot — Help Guide*\n\n"

                "━━━━━━━━━━━━━━━━━━\n"
                "📢 *BROADCAST* — Send to all clients now\n"
                "Format: `BROADCAST: <your message>`\n"
                "Example: _BROADCAST: 🎉 Flash sale today! 20% off all solar panels._\n\n"

                "━━━━━━━━━━━━━━━━━━\n"
                "🕐 *SCHEDULE* — Send at a specific date & time (IST)\n"
                "Format: `SCHEDULE: YYYY-MM-DD HH:MM <your message>`\n"
                "Example: _SCHEDULE: 2026-03-25 10:00 New inverter stock is live!_\n\n"

                "━━━━━━━━━━━━━━━━━━\n"
                "👤 *ADD CLIENT* — Add one client by phone\n"
                "Format: `ADD: <phone>, <Name>`\n"
                "Example: _ADD: 9876543210, Ravi Kumar_\n\n"

                "━━━━━━━━━━━━━━━━━━\n"
                "🗑️ *REMOVE CLIENT* — Remove client by phone\n"
                "Format: `REMOVE: <phone>`\n"
                "Example: _REMOVE: 9876543210_\n\n"

                "━━━━━━━━━━━━━━━━━━\n"
                "📋 *BULK IMPORT* — Send a CSV or Excel file\n"
                "Required columns: `name`, `phone`\n"
                "Optional column: `email`\n"
                "All imported clients will be opted-in automatically.\n\n"

                "━━━━━━━━━━━━━━━━━━\n"
                "📚 *ADD TO KNOWLEDGE BASE* — Send a PDF or Word doc\n"
                "Caption = category: `products` / `offers` / `documents`\n"
                "Supported: PDF, DOCX, DOC, TXT\n\n"

                "━━━━━━━━━━━━━━━━━━\n"
                "📊 *COMMANDS*\n"
                "• `/status` — Platform stats\n"
                "• `/clients` — Opted-in count\n"
                "• `/report` — Broadcast analytics\n"
                "• `/catalogue= URL` — Set catalogue link\n"
                "• `/help` — This guide\n\n"

                "━━━━━━━━━━━━━━━━━━\n"
                "🧪 *TEST THE BOT*\n"
                "Send any message without a prefix to test the RAG bot.\n"
                "Example: _what is the price of solar inverter?_"
            ),
        )
        return Response(status_code=200, content="ok")

    # ── /status ───────────────────────────────────────────────────────────────
    if msg.lower() == "/status":
        async with get_db_context() as db:
            total_clients = (await db.execute(
                select(func.count()).where(Client.opted_in == True, Client.is_deleted == False)
            )).scalar_one()
            last_broadcast = (await db.execute(
                select(Broadcast.created_at).order_by(Broadcast.created_at.desc()).limit(1)
            )).scalar_one_or_none()
            lb_str = last_broadcast.strftime("%d-%b %H:%M UTC") if last_broadcast else "None yet"
        await adapter.send_message(
            phone=sender_phone,
            message=(
                f"📊 *TwinAI Status*\n\n"
                f"👥 Opted-in clients: *{total_clients}*\n"
                f"📤 Last broadcast: *{lb_str}*\n\n"
                f"Type `/help` to see all commands & formats."
            ),
        )
        return Response(status_code=200, content="ok")

    # ── /clients ──────────────────────────────────────────────────────────────
    if msg.lower() == "/clients":
        async with get_db_context() as db:
            count = (await db.execute(
                select(func.count()).where(Client.opted_in == True, Client.is_deleted == False)
            )).scalar_one()
        await adapter.send_message(phone=sender_phone, message=f"👥 Opted-in clients: {count}")
        return Response(status_code=200, content="ok")

    # ── /report ───────────────────────────────────────────────────────────────
    if msg.lower() == "/report":
        async with get_db_context() as db:
            stmt = select(Broadcast).order_by(Broadcast.created_at.desc()).limit(1)
            latest_broadcast = (await db.execute(stmt)).scalar_one_or_none()

            if not latest_broadcast:
                await adapter.send_message(phone=sender_phone, message="No broadcasts found.")
                return Response(status_code=200, content="ok")

            stats_stmt = select(BroadcastRecipient.status, func.count(BroadcastRecipient.id)).where(
                BroadcastRecipient.broadcast_id == latest_broadcast.id
            ).group_by(BroadcastRecipient.status)
            stats = dict((await db.execute(stats_stmt)).all())

            sent_count = stats.get("sent", 0) + stats.get("delivered", 0) + stats.get("read", 0)
            delivered_count = stats.get("delivered", 0) + stats.get("read", 0)
            read_count = stats.get("read", 0)
            failed_count = stats.get("failed", 0)

            report_msg = (
                f"📊 *Last Broadcast Report*\n\n"
                f"🏷️ Name: {latest_broadcast.name}\n"
                f"📅 Date: {latest_broadcast.created_at.strftime('%d %b, %H:%M')}\n\n"
                f"📤 Sent: {sent_count}\n"
                f"✅ Delivered: {delivered_count}\n"
                f"👁️ Read: {read_count}\n"
                f"❌ Failed: {failed_count}"
            )
        await adapter.send_message(phone=sender_phone, message=report_msg)
        return Response(status_code=200, content="ok")

    # ── /catalogue=<url> ──────────────────────────────────────────────────────
    cat_match = re.match(r"(?i)^/CATALOGUE\s*=\s*(.+)$", msg)
    if cat_match:
        new_url = cat_match.group(1).strip()
        from core.redis_client import get_redis
        r = get_redis()
        await r.set(settings.catalogue_redis_key, new_url)
        await adapter.send_message(
            phone=sender_phone,
            message=f"✅ Catalogue URL updated successfully to:\n{new_url}",
        )
        return Response(status_code=200, content="ok")

    # ── SCHEDULE: YYYY-MM-DD HH:MM <message> ─────────────────────────────────
    schedule_match = re.match(
        r"(?i)^schedule:\s*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s+(.+)$",
        msg,
        re.DOTALL,
    )
    if schedule_match:
        date_str, time_str, broadcast_msg = schedule_match.groups()
        broadcast_msg = broadcast_msg.strip()
        IST = ZoneInfo("Asia/Kolkata")
        try:
            scheduled_dt_ist = datetime.strptime(
                f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=IST)
            scheduled_dt_utc = scheduled_dt_ist.astimezone(timezone.utc)
        except ValueError:
            await adapter.send_message(
                phone=sender_phone,
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
                    phone=sender_phone,
                    message=(
                        f"🕐 Broadcast scheduled for {display_time} "
                        f"for {eligible_count} client(s).\n\"{preview}\""
                    ),
                )
                logger.info(f"[CMD] Scheduled {broadcast_id} for {display_time}")
            except Exception as exc:
                logger.error(f"[CMD] Failed to schedule: {exc}")
                try:
                    await adapter.send_message(phone=sender_phone, message=f"❌ Scheduling failed: {str(exc)[:100]}")
                except Exception:
                    pass
        return Response(status_code=200, content="ok")

    # ── BROADCAST with media (owner sends image/PDF with BROADCAST: caption) ──
    if media_url and msg.upper().startswith("BROADCAST:"):
        broadcast_caption = msg[len("BROADCAST:"):].strip()
        if "pdf" in media_type.lower():
            bc_media_type = "document"
            bc_filename = "product_catalogue.pdf"
            file_ext = ".pdf"
        else:
            bc_media_type = "image"
            bc_filename = "image.jpg"
            file_ext = ".jpg"

        public_media_url = media_url
        try:
            import os as _os, uuid as _uuid
            uploads_dir = settings.media_cache_dir
            _os.makedirs(uploads_dir, exist_ok=True)
            file_name = f"{_uuid.uuid4().hex}{file_ext}"
            save_path = f"{uploads_dir}/{file_name}"

            async with httpx.AsyncClient(timeout=settings.rerank_timeout_seconds) as hclient:
                dl = await hclient.get(
                    media_url,
                    auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                    follow_redirects=True,
                )
                dl.raise_for_status()
                with open(save_path, "wb") as f:
                    f.write(dl.content)

            if base_url:
                public_media_url = f"{base_url.rstrip('/')}/media/{file_name}"
            logger.info(f"[CMD] Cached media → {save_path} | public URL: {public_media_url}")
        except Exception as dl_exc:
            logger.error(f"[CMD] Failed to download/cache Twilio media: {dl_exc}")

        logger.info(f"[CMD] Owner triggered media broadcast: type={bc_media_type} caption={broadcast_caption[:40]}")
        async with get_db_context() as db:
            try:
                result = await create_broadcast(
                    db=db,
                    name=f"Media broadcast — {broadcast_caption[:30]}",
                    message_template=broadcast_caption,
                    channel="whatsapp",
                    media_url=public_media_url,
                    media_type=bc_media_type,
                    media_filename=bc_filename,
                )
                broadcast_id = result["id"]
                eligible_count = result["eligible_count"]
                send_broadcast.delay(broadcast_id)
                await adapter.send_message(
                    phone=sender_phone,
                    message=(
                        f"✅ Media broadcast queued for *{eligible_count}* client(s)!\n"
                        f"📎 Type: {bc_media_type}\n"
                        f"💬 Caption: \"{broadcast_caption[:60]}\""
                    ),
                )
                logger.info(f"[CMD] Media broadcast {broadcast_id} queued for {eligible_count} clients")
            except Exception as exc:
                logger.error(f"[CMD] Media broadcast failed: {exc}")
                try:
                    await adapter.send_message(phone=sender_phone, message=f"❌ Media broadcast failed: {str(exc)[:100]}")
                except Exception:
                    pass
        return Response(status_code=200, content="ok")

    # ── BROADCAST: <message> — text-only broadcast ────────────────────────────
    broadcast_match = re.match(r"(?i)^broadcast:\s*(.+)$", msg, re.DOTALL)
    if broadcast_match:
        broadcast_msg = broadcast_match.group(1).strip()
        logger.info(f"[CMD] Owner triggered broadcast: {broadcast_msg[:60]}")
        async with get_db_context() as db:
            try:
                result = await create_broadcast(
                    db=db,
                    name=f"WhatsApp broadcast {broadcast_msg[:30]}",
                    message_template=broadcast_msg,
                    channel="whatsapp",
                )
                broadcast_id = result["id"]
                eligible_count = result["eligible_count"]
                send_broadcast.delay(broadcast_id)
                preview = broadcast_msg[:60] + ("..." if len(broadcast_msg) > 60 else "")
                await adapter.send_message(
                    phone=sender_phone,
                    message=f"✅ Broadcast queued for {eligible_count} client(s):\n\"{preview}\"",
                )
                logger.info(f"[CMD] Queued broadcast {broadcast_id} for {eligible_count} clients")
            except Exception as exc:
                logger.error(f"[CMD] Failed to create broadcast: {exc}")
                try:
                    await adapter.send_message(phone=sender_phone, message=f"❌ Broadcast failed: {str(exc)[:100]}")
                except Exception:
                    pass
        return Response(status_code=200, content="ok")

    # ── ADD: <phone>, <name> ──────────────────────────────────────────────────
    add_match = re.match(r"(?i)^add:\s*(\+?\d[\d\s\-]{7,15})\s*,\s*(.+)$", msg)
    if add_match:
        raw_phone, name = add_match.group(1).strip(), add_match.group(2).strip()
        digits = re.sub(r"\D", "", raw_phone)
        if len(digits) == 10:
            phone = f"+91{digits}"
        elif digits.startswith("91") and len(digits) == 12:
            phone = f"+{digits}"
        else:
            phone = f"+{digits}" if not raw_phone.startswith("+") else raw_phone
        try:
            async with AsyncSessionLocal() as db:
                existing = (await db.execute(
                    select(Client).where(Client.phone == phone, Client.is_deleted == False)
                )).scalar_one_or_none()
                if existing:
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"⚠️ Client already exists:\n👤 {existing.name} ({phone})",
                    )
                else:
                    client = Client(name=name, phone=phone, opted_in=True)
                    db.add(client)
                    await db.commit()
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"✅ Client added & opted-in:\n👤 *{name}*\n📞 {phone}",
                    )
                    logger.info(f"[CMD] Added client: {name} ({phone})")
        except Exception as exc:
            logger.error(f"[CMD] ADD: failed: {exc}")
            await adapter.send_message(phone=sender_phone, message=f"❌ Failed to add client: {str(exc)[:120]}")
        return Response(status_code=200, content="ok")

    # ── REMOVE: <phone> ───────────────────────────────────────────────────────
    remove_match = re.match(r"(?i)^remove:\s*(\+?\d[\d\s\-]{7,15})$", msg)
    if remove_match:
        raw_phone = remove_match.group(1).strip()
        digits = re.sub(r"\D", "", raw_phone)
        if len(digits) == 10:
            phone = f"+91{digits}"
        elif digits.startswith("91") and len(digits) == 12:
            phone = f"+{digits}"
        else:
            phone = f"+{digits}" if not raw_phone.startswith("+") else raw_phone
        try:
            async with AsyncSessionLocal() as db:
                client = (await db.execute(
                    select(Client).where(Client.phone == phone, Client.is_deleted == False)
                )).scalar_one_or_none()
                if not client:
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"⚠️ No active client found for {phone}",
                    )
                else:
                    client_name = client.name
                    client.is_deleted = True
                    client.opted_in = False
                    await db.commit()
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"🗑️ Client removed:\n👤 *{client_name}* ({phone})",
                    )
                    logger.info(f"[CMD] Removed client: {client_name} ({phone})")
        except Exception as exc:
            logger.error(f"[CMD] REMOVE: failed: {exc}")
            await adapter.send_message(phone=sender_phone, message=f"❌ Failed to remove client: {str(exc)[:120]}")
        return Response(status_code=200, content="ok")

    # ── Owner sends CSV/XLSX → bulk import clients ────────────────────────────
    if media_url and media_type and media_type.lower() in _CLIENT_SHEET_TYPES:
        logger.info(f"[CMD] Client spreadsheet received ({media_type})")
        try:
            async with httpx.AsyncClient(timeout=settings.file_download_timeout_seconds, follow_redirects=True) as hclient:
                if settings.messaging_provider == "twilio" and settings.twilio_account_sid:
                    resp = await hclient.get(
                        media_url,
                        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                    )
                else:
                    resp = await hclient.get(media_url)
                resp.raise_for_status()
                file_bytes = resp.content

            ext = ".xlsx" if "spreadsheetml" in media_type.lower() else ".csv"
            filename = f"clients_import{ext}"

            async with AsyncSessionLocal() as db:
                rows = parse_upload_file(file_bytes, filename)
                columns = list(rows[0].keys()) if rows else []
                col_map = detect_column_mapping(columns)
                summary = await import_clients(
                    db=db,
                    content=file_bytes,
                    filename=filename,
                    column_mapping=col_map,
                    set_opted_in=True,
                )

            imported = summary.get("imported", 0)
            skipped = summary.get("skipped_duplicates", 0) + summary.get("skipped_invalid", 0)
            await adapter.send_message(
                phone=sender_phone,
                message=(
                    f"✅ *Client import complete!*\n"
                    f"✅ Imported: *{imported}*\n"
                    f"⏭️ Skipped (duplicates/invalid): *{skipped}*\n\n"
                    f"_All imported clients are opted-in._\n"
                    f"CSV column names expected: `name`, `phone`, `email` (optional)"
                ),
            )
            logger.info(f"[CMD] Client import: {imported} imported, {skipped} skipped")
        except Exception as exc:
            logger.error(f"[CMD] Client import failed: {exc}")
            try:
                await adapter.send_message(phone=sender_phone, message=f"❌ Import failed: {str(exc)[:150]}")
            except Exception:
                pass
        return Response(status_code=200, content="ok")

    # ── Owner sends PDF/DOCX/TXT → ingest into Knowledge Base ────────────────
    if media_url and media_type and media_type.lower() in _INGESTABLE_TYPES:
        logger.info(f"[CMD] Document received: {media_type} — ingesting into KB")
        try:
            async with httpx.AsyncClient(timeout=settings.file_download_timeout_seconds, follow_redirects=True) as hclient:
                if settings.messaging_provider == "twilio" and settings.twilio_account_sid:
                    resp = await hclient.get(
                        media_url,
                        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                    )
                else:
                    resp = await hclient.get(media_url)
                resp.raise_for_status()
                file_bytes = resp.content

            ext = _KB_EXT_MAP.get(media_type.lower(), ".bin")
            filename = f"owner_upload_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}{ext}"

            valid_categories = {"products", "offers", "documents", "broadcasts"}
            caption_lower = (msg or "").strip().lower()
            category = caption_lower if caption_lower in valid_categories else "documents"

            async with AsyncSessionLocal() as db:
                result = await knowledge_service.ingest_document(
                    db=db,
                    file_bytes=file_bytes,
                    filename=filename,
                    category=category,
                    valid_from=None,
                    valid_until=None,
                )

            chunks = result.get("chunks_indexed", "?")
            await adapter.send_message(
                phone=sender_phone,
                message=(
                    f"✅ *Document ingested!*\n"
                    f"📄 File: {filename}\n"
                    f"📂 Category: *{category}*\n"
                    f"🧩 Chunks indexed: *{chunks}*\n\n"
                    f"_Tip: Send caption as `products`, `offers`, or `documents` to set category._"
                ),
            )
            logger.info(f"[CMD] KB ingestion complete: {filename}, {chunks} chunks, category={category}")
        except Exception as exc:
            logger.error(f"[CMD] KB ingestion failed: {exc}")
            try:
                await adapter.send_message(
                    phone=sender_phone,
                    message=f"❌ Failed to ingest document: {str(exc)[:150]}",
                )
            except Exception:
                pass
        return Response(status_code=200, content="ok")

    # ── No command matched — owner is testing the RAG bot ────────────────────
    logger.info(f"[CMD] No command matched — routing to RAG bot: {msg[:60]}")
    return None  # Caller should fall through to the RAG bot
