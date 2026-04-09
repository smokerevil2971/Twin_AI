"""
Owner Command Service — Phase 2 Refactor

Supported commands:
  /help, /status, /clients, /report, /broadcasts, /analytics [7|30], /kb
  /catalogue=<url>
  /products, /offers
  BROADCAST: <msg>           — text broadcast
  BROADCAST (urgent): <msg>  — skip cooldown window
  CANCEL BROADCAST: <name>   — cancel by partial name
  SCHEDULE: YYYY-MM-DD HH:MM <msg>
  ADD: <phone>, <name>
  REMOVE: <phone>
  PRODUCT: <name> | <price> | <description>
  OFFER:   <title> | <description>
  UPDATE PRODUCT: <name> | <new_price>
  DEL PRODUCT: <name>
  DEL OFFER: <title>
  <CSV/XLSX media>       → bulk client import
  <PDF/DOCX/TXT media>   → knowledge base ingestion
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
from models.models import Broadcast, BroadcastRecipient, Client, Product, Offer, Conversation
from services.broadcast_service import create_broadcast
from services.client_service import import_clients, parse_upload_file, detect_column_mapping
from services.messaging_adapter import get_messaging_adapter
from services import knowledge_service
from services.products_offers_service import (
    parse_products_file,
    parse_offers_file,
    bulk_import_products,
    bulk_import_offers,
)
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
    message_id: str = "",   # 1.2: for emoji reactions
    button_payload: str = "", # 2.3: for analytics toggle button
) -> Optional[Response]:
    """
    Routes an inbound owner WhatsApp message to the correct handler.

    Returns a FastAPI Response if the command was handled, or None to signal
    that the message should fall through to the RAG bot (owner testing mode).
    """
    # 2.3: Reroute analytics button taps as analytics commands
    if button_payload in ("analytics_7days", "analytics_30days"):
        msg = button_payload
    adapter = get_messaging_adapter()

    if media_url and settings.messaging_provider == "meta" and not media_url.startswith("http"):
        try:
            from services.media_processor import _resolve_meta_media
            real_url, detected_mime = await _resolve_meta_media(media_url)
            media_url = real_url
            if detected_mime:
                media_type = detected_mime
        except Exception as e:
            logger.error(f"[CMD] Failed to resolve Meta media_id {media_url}: {e}")

    # ── /help ─────────────────────────────────────────────────────────────────
    if msg.lower() == "/help":
        await adapter.send_message(
            phone=sender_phone,
            message=(
                "🤖 *Devraj Traders Admin Bot — Quick Guide*\n\n"
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
                f"📊 *Devraj Traders Status*\n\n"
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

            total     = sum(stats.values())
            sent_count      = stats.get("sent", 0) + stats.get("delivered", 0) + stats.get("read", 0)
            delivered_count = stats.get("delivered", 0) + stats.get("read", 0)
            read_count      = stats.get("read", 0)
            failed_count    = stats.get("failed", 0)

            # 1.4: percentage rates
            def pct(n, d):
                return f" ({int(n / d * 100)}%)" if d else ""

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
    urgent_media = bool(re.search(r"\(urgent\)", msg, re.IGNORECASE))
    clean_media_msg = re.sub(r"\(urgent\)\s*", "", msg, flags=re.IGNORECASE).strip()
    if media_url and clean_media_msg.upper().startswith("BROADCAST:"):
        broadcast_caption = clean_media_msg[len("BROADCAST:"):].strip()
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

            # Provider-agnostic download: Twilio needs Basic Auth, Meta needs Bearer
            req_headers = {}
            req_auth = None
            if settings.messaging_provider == "twilio" and settings.twilio_account_sid:
                req_auth = (settings.twilio_account_sid, settings.twilio_auth_token)
            elif settings.messaging_provider == "meta" and settings.meta_access_token:
                req_headers = {"Authorization": f"Bearer {settings.meta_access_token}"}

            async with httpx.AsyncClient(timeout=settings.rerank_timeout_seconds) as hclient:
                dl = await hclient.get(
                    media_url,
                    auth=req_auth,
                    headers=req_headers,
                    follow_redirects=True,
                )
                dl.raise_for_status()
                with open(save_path, "wb") as f:
                    f.write(dl.content)

            if base_url:
                public_media_url = f"{base_url.rstrip('/')}/media/{file_name}"
            logger.info(f"[CMD] Cached media → {save_path} | public URL: {public_media_url}")
        except Exception as dl_exc:
            logger.error(f"[CMD] Failed to download/cache media: {dl_exc}")

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
                    override_cooldown=urgent_media,
                )
                broadcast_id = result["id"]
                eligible_count = result["eligible_count"]
                send_broadcast.delay(broadcast_id)
                urgent_label = " *(urgent — cooldown skipped)*" if urgent_media else ""
                await adapter.send_message(
                    phone=sender_phone,
                    message=(
                        f"✅ Media broadcast queued for *{eligible_count}* client(s)!{urgent_label}\n"
                        f"📎 Type: {bc_media_type}\n"
                        f"💬 Caption: \"{broadcast_caption[:60]}\""
                    ),
                )
                if message_id:
                    await adapter.send_reaction(sender_phone, message_id, "👍")
                logger.info(f"[CMD] Media broadcast {broadcast_id} queued for {eligible_count} clients")
            except Exception as exc:
                logger.error(f"[CMD] Media broadcast failed: {exc}")
                try:
                    await adapter.send_message(phone=sender_phone, message=f"❌ Media broadcast failed: {str(exc)[:100]}")
                except Exception:
                    pass
        return Response(status_code=200, content="ok")

    # ── BROADCAST: <message> — text-only, supports (urgent) cooldown skip ──────
    broadcast_match = re.match(r"(?i)^broadcast(?:\s*\(urgent\))?:\s*(.+)$", msg, re.DOTALL)
    if broadcast_match:
        urgent = bool(re.search(r"\(urgent\)", msg, re.IGNORECASE))
        broadcast_msg = broadcast_match.group(1).strip()
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
                    phone=sender_phone,
                    message=f"✅ Broadcast queued for *{eligible_count}* client(s){urgent_label}:\n\"{preview}\"",
                )
                if message_id:
                    await adapter.send_reaction(sender_phone, message_id, "👍")
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

    # ── Owner sends CSV/XLSX → bulk import based on caption ───────────────────
    if media_url and media_type and media_type.lower() in _CLIENT_SHEET_TYPES:
        caption = (msg or "").strip().lower()
        target = caption if caption in ("products", "offers", "clients") else "clients"
        logger.info(f"[CMD] Spreadsheet received ({media_type}) — Target: {target}")

        try:
            async with httpx.AsyncClient(timeout=settings.file_download_timeout_seconds, follow_redirects=True) as hclient:
                req_headers = {}
                req_auth = None
                if settings.messaging_provider == "twilio" and settings.twilio_account_sid:
                    req_auth = (settings.twilio_account_sid, settings.twilio_auth_token)
                elif settings.messaging_provider == "meta" and settings.meta_access_token:
                    req_headers = {"Authorization": f"Bearer {settings.meta_access_token}"}
                
                resp = await hclient.get(media_url, auth=req_auth, headers=req_headers)
                resp.raise_for_status()
                file_bytes = resp.content

            ext = ".xlsx" if "spreadsheetml" in media_type.lower() else ".csv"
            filename = f"bulk_import_{target}{ext}"

            async with AsyncSessionLocal() as db:
                if target == "products":
                    parsed = parse_products_file(file_bytes, filename)
                    if not parsed["rows"]:
                        raise ValueError("No data rows found or missing 'name' column.")
                    summary = await bulk_import_products(db, parsed["rows"])
                    imported = summary.get("imported", 0)
                    skipped = summary.get("skipped", 0)
                    response_msg = (
                        f"✅ *Products Import complete!*\n"
                        f"✅ Imported: *{imported}*\n"
                        f"⏭️ Skipped (errors/missing names): *{skipped}*\n\n"
                        f"_Products are now live on the client menu._"
                    )

                elif target == "offers":
                    parsed = parse_offers_file(file_bytes, filename)
                    if not parsed["rows"]:
                        raise ValueError("No data rows found or missing 'title' column.")
                    summary = await bulk_import_offers(db, parsed["rows"])
                    imported = summary.get("imported", 0)
                    skipped = summary.get("skipped", 0)
                    response_msg = (
                        f"✅ *Offers Import complete!*\n"
                        f"✅ Imported: *{imported}*\n"
                        f"⏭️ Skipped (errors/missing titles): *{skipped}*\n\n"
                        f"_Offers are now live on the client menu._"
                    )

                else:
                    # Default: clients
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
                    response_msg = (
                        f"✅ *Client Import complete!*\n"
                        f"✅ Imported: *{imported}*\n"
                        f"⏭️ Skipped (duplicates/invalid): *{skipped}*\n\n"
                        f"_All imported clients are opted-in._"
                    )

            await adapter.send_message(phone=sender_phone, message=response_msg)
            logger.info(f"[CMD] {target.capitalize()} import: {imported} imported, {skipped} skipped")
        except Exception as exc:
            logger.error(f"[CMD] {target.capitalize()} import failed: {exc}")
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
                req_headers = {}
                req_auth = None
                if settings.messaging_provider == "twilio" and settings.twilio_account_sid:
                    req_auth = (settings.twilio_account_sid, settings.twilio_auth_token)
                elif settings.messaging_provider == "meta" and settings.meta_access_token:
                    req_headers = {"Authorization": f"Bearer {settings.meta_access_token}"}

                resp = await hclient.get(media_url, auth=req_auth, headers=req_headers)
                resp.raise_for_status()
                file_bytes = resp.content

            ext = _KB_EXT_MAP.get(media_type.lower(), ".bin")
            # Use caption as the document's display name if it's meaningful
            # (owner can send: image.pdf with caption "Gyproc Product List")
            caption_words = (msg or "").strip()
            
            valid_categories = {"products", "offers", "documents", "broadcasts"}
            caption_lower = caption_words.lower()
            category = caption_lower if caption_lower in valid_categories else "documents"

            # Detect if caption is a category keyword or empty
            is_just_category = caption_lower in ("", "products", "offers", "documents", "broadcasts")
            if not is_just_category and len(caption_words) > 2:
                # Caption is a meaningful name — use it as the filename
                safe_name = re.sub(r'[^\w\s\-.]', '', caption_words)[:60].strip().replace(' ', '_')
                filename = f"{safe_name}{ext}"
            else:
                # Fallback: friendly timestamp name
                ts = datetime.now(timezone.utc).strftime('%d%b_%H%M').lower()
                filename = f"{category}_{ts}{ext}"

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

    # ── /products — list all active products ────────────────────────────────
    if msg.lower() == "/products":
        async with get_db_context() as db:
            result = await db.execute(
                select(Product).where(Product.is_active == True).order_by(Product.name)
            )
            products = result.scalars().all()

        if not products:
            await adapter.send_message(
                phone=sender_phone,
                message="📦 No products yet. Add one with:\n`PRODUCT: <name> | <price> | <description>`",
            )
        else:
            lines = [f"📦 *Products ({len(products)})*\n"]
            for i, p in enumerate(products, 1):
                price_str = f"₹{p.price:,.0f}" if p.price else "Price on request"
                desc = f" — {p.description[:50]}" if p.description else ""
                img = " 🖼️" if p.image_url else ""
                lines.append(f"{i}. *{p.name}* ({price_str}){desc}{img}")
            lines.append("\n_Use `DEL PRODUCT: <name>` to remove._")
            await adapter.send_message(phone=sender_phone, message="\n".join(lines))
        return Response(status_code=200, content="ok")

    # ── /offers — list all active offers ────────────────────────────────────
    if msg.lower() == "/offers":
        async with get_db_context() as db:
            result = await db.execute(
                select(Offer).where(Offer.is_active == True).order_by(Offer.title)
            )
            offers = result.scalars().all()

        if not offers:
            await adapter.send_message(
                phone=sender_phone,
                message="💰 No offers yet. Add one with:\n`OFFER: <title> | <description>`",
            )
        else:
            lines = [f"💰 *Offers ({len(offers)})*\n"]
            for i, o in enumerate(offers, 1):
                desc = f" — {o.description[:60]}" if o.description else ""
                lines.append(f"{i}. *{o.title}*{desc}")
            lines.append("\n_Use `DEL OFFER: <title>` to remove._")
            await adapter.send_message(phone=sender_phone, message="\n".join(lines))
        return Response(status_code=200, content="ok")

    # ── PRODUCT: <name> | <price> | <description> [| <image_url>] ───────────
    # 3.2: Optional 4th field is an image URL (https://...) for product card display
    product_add_match = re.match(
        r"(?i)^product:\s*(.+?)\s*\|\s*([\d.,]*)\s*(?:\|\s*(.+?))?\s*(?:\|\s*(https?://\S+))?$",
        msg.strip(),
    )
    if product_add_match:
        name        = product_add_match.group(1).strip()
        price_raw   = (product_add_match.group(2) or "").strip().replace(",", "")
        description = (product_add_match.group(3) or "").strip() or None
        image_url   = (product_add_match.group(4) or "").strip() or None
        price       = float(price_raw) if price_raw else None

        try:
            async with AsyncSessionLocal() as db:
                existing = (await db.execute(
                    select(Product).where(Product.name.ilike(name), Product.is_active == True)
                )).scalar_one_or_none()
                if existing:
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"⚠️ Product already exists: *{existing.name}*\nUse `DEL PRODUCT: {existing.name}` first to replace it.",
                    )
                else:
                    product = Product(
                        name=name, description=description,
                        price=price, image_url=image_url, is_active=True
                    )
                    db.add(product)
                    await db.commit()
                    price_str = f"₹{price:,.0f}" if price else "Price on request"
                    img_tag = "\n🖼️ Image: attached" if image_url else ""
                    await adapter.send_message(
                        phone=sender_phone,
                        message=(
                            f"✅ *Product added!*\n"
                            f"🛒 Name: *{name}*\n"
                            f"💰 Price: {price_str}\n"
                            f"📝 Description: {description or '—'}{img_tag}\n\n"
                            f"_It will now appear in the client product menu._"
                        ),
                    )
                    if message_id:
                        await adapter.send_reaction(sender_phone, message_id, "👍")
                    logger.info(f"[CMD] Product added: {name} @ {price} image={'yes' if image_url else 'no'}")
        except Exception as exc:
            logger.error(f"[CMD] PRODUCT add failed: {exc}")
            await adapter.send_message(phone=sender_phone, message=f"❌ Failed to add product: {str(exc)[:120]}")
        return Response(status_code=200, content="ok")

    # ── OFFER: <title> | <description> ───────────────────────────────────────
    offer_add_match = re.match(
        r"(?i)^offer:\s*(.+?)\s*\|\s*(.+)$", msg.strip(), re.DOTALL
    )
    if offer_add_match:
        title = offer_add_match.group(1).strip()
        description = offer_add_match.group(2).strip()

        try:
            async with AsyncSessionLocal() as db:
                existing = (await db.execute(
                    select(Offer).where(Offer.title.ilike(title), Offer.is_active == True)
                )).scalar_one_or_none()
                if existing:
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"⚠️ Offer already exists: *{existing.title}*\nUse `DEL OFFER: {existing.title}` first to replace it.",
                    )
                else:
                    offer = Offer(title=title, description=description, is_active=True)
                    db.add(offer)
                    await db.commit()
                    await adapter.send_message(
                        phone=sender_phone,
                        message=(
                            f"✅ *Offer added!*\n"
                            f"💰 Title: *{title}*\n"
                            f"📝 Description: {description}\n\n"
                            f"_It will now appear in the client offers menu._"
                        ),
                    )
                    logger.info(f"[CMD] Offer added: {title}")
        except Exception as exc:
            logger.error(f"[CMD] OFFER add failed: {exc}")
            await adapter.send_message(phone=sender_phone, message=f"❌ Failed to add offer: {str(exc)[:120]}")
        return Response(status_code=200, content="ok")

    # ── DEL PRODUCT: <name> ───────────────────────────────────────────────────
    del_product_match = re.match(r"(?i)^del\s+product:\s*(.+)$", msg.strip())
    if del_product_match:
        name = del_product_match.group(1).strip()
        try:
            async with AsyncSessionLocal() as db:
                product = (await db.execute(
                    select(Product).where(Product.name.ilike(name), Product.is_active == True)
                )).scalar_one_or_none()
                if not product:
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"⚠️ No active product found matching: *{name}*\nUse `/products` to see all products.",
                    )
                else:
                    product.is_active = False
                    await db.commit()
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"🗑️ Product removed: *{product.name}*\n_It will no longer appear in the client menu._",
                    )
                    logger.info(f"[CMD] Product deactivated: {product.name}")
        except Exception as exc:
            logger.error(f"[CMD] DEL PRODUCT failed: {exc}")
            await adapter.send_message(phone=sender_phone, message=f"❌ Failed to remove product: {str(exc)[:120]}")
        return Response(status_code=200, content="ok")

    # ── DEL OFFER: <title> ────────────────────────────────────────────────────
    del_offer_match = re.match(r"(?i)^del\s+offer:\s*(.+)$", msg.strip())
    if del_offer_match:
        title = del_offer_match.group(1).strip()
        try:
            async with AsyncSessionLocal() as db:
                offer = (await db.execute(
                    select(Offer).where(Offer.title.ilike(title), Offer.is_active == True)
                )).scalar_one_or_none()
                if not offer:
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"⚠️ No active offer found matching: *{title}*\nUse `/offers` to see all offers.",
                    )
                else:
                    offer.is_active = False
                    await db.commit()
                    await adapter.send_message(
                        phone=sender_phone,
                        message=f"🗑️ Offer removed: *{offer.title}*\n_It will no longer appear in the client menu._",
                    )
                    logger.info(f"[CMD] Offer deactivated: {offer.title}")
        except Exception as exc:
            logger.error(f"[CMD] DEL OFFER failed: {exc}")
            await adapter.send_message(phone=sender_phone, message=f"❌ Failed to remove offer: {str(exc)[:120]}")
        return Response(status_code=200, content="ok")

    # ── /broadcasts — list recent broadcasts ─────────────────────────────────
    if msg.lower().strip() in ("/broadcasts", "/broadcast"):
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(Broadcast).order_by(Broadcast.created_at.desc()).limit(5)
            )).scalars().all()
            if not rows:
                await adapter.send_message(phone=sender_phone, message="No broadcasts found yet.")
            else:
                lines = ["📋 *Last 5 Broadcasts*"]
                for i, b in enumerate(rows, 1):
                    date = b.created_at.strftime("%d %b, %H:%M")
                    # Show actual message preview so owner can identify what was sent
                    preview = (b.message_template or "")[:80].strip()
                    if len(b.message_template or "") > 80:
                        preview += "..."
                    media_tag = " 📎" if b.media_url else ""
                    lines.append(
                        f"\n{i}.{media_tag} 📅 *{date}* | `{b.status}`\n"
                        f"   _{preview}_"
                    )
                await adapter.send_message(phone=sender_phone, message="\n".join(lines))
        return Response(status_code=200, content="ok")

    # ── CANCEL BROADCAST: <partial name> ─────────────────────────────────────
    cancel_match = re.match(r"(?i)^cancel\s+broadcast:\s*(.+)$", msg.strip())
    if cancel_match:
        partial = cancel_match.group(1).strip()
        async with AsyncSessionLocal() as db:
            results = (await db.execute(
                select(Broadcast).where(
                    Broadcast.name.ilike(f"%{partial}%"),
                    Broadcast.status.in_(["draft", "sending", "pending"]),
                ).limit(5)
            )).scalars().all()
            if not results:
                await adapter.send_message(
                    phone=sender_phone,
                    message=f"⚠️ No active broadcast found matching: *{partial}*\nCheck `/broadcasts` for names.",
                )
            elif len(results) == 1:
                b = results[0]
                b.status = "cancelled"
                await db.commit()
                await adapter.send_message(
                    phone=sender_phone,
                    message=f"🗑️ Broadcast *'{b.name}'* cancelled successfully.",
                )
                if message_id:
                    await adapter.send_reaction(sender_phone, message_id, "👍")
                logger.info(f"[CMD] Broadcast cancelled: {b.name}")
            else:
                names = "\n".join(f"• {b.name}" for b in results)
                await adapter.send_message(
                    phone=sender_phone,
                    message=f"⚠️ Multiple matches found — be more specific:\n\n{names}",
                )
        return Response(status_code=200, content="ok")

    # ── /analytics [30] — rich stats with top performers ─────────────────────
    analytics_match = re.match(r"(?i)^/analytics(?:\s+(7|30))?$", msg.strip())
    # Also handle button_payload from "View 30-day" button tap
    analytics_days = None
    if analytics_match:
        analytics_days = int(analytics_match.group(1) or 7)
    elif msg.strip().lower() == "analytics_30days":
        analytics_days = 30
    elif msg.strip().lower() == "analytics_7days":
        analytics_days = 7

    if analytics_days is not None:
        from datetime import timedelta
        from core.redis_client import get_top_menu_items
        cutoff = datetime.now(timezone.utc) - timedelta(days=analytics_days)
        async with AsyncSessionLocal() as db:
            new_clients    = (await db.execute(select(func.count(Client.id)).where(Client.created_at >= cutoff, Client.is_deleted == False))).scalar_one()
            conversations  = (await db.execute(select(func.count()).select_from(Conversation).where(Conversation.created_at >= cutoff))).scalar_one()
            broadcasts_cnt = (await db.execute(select(func.count(Broadcast.id)).where(Broadcast.status == "sent", Broadcast.created_at >= cutoff))).scalar_one()

            # Best broadcast by read rate
            best_bc_name = "N/A"
            bc_rows = (await db.execute(
                select(Broadcast).where(Broadcast.status == "sent", Broadcast.created_at >= cutoff)
            )).scalars().all()
            if bc_rows:
                best_bc, best_rate = None, -1
                for bc in bc_rows:
                    stats = dict((await db.execute(
                        select(BroadcastRecipient.status, func.count()).where(BroadcastRecipient.broadcast_id == bc.id).group_by(BroadcastRecipient.status)
                    )).all())
                    total_s = sum(stats.values())
                    read_r = (stats.get("read", 0) / total_s * 100) if total_s else 0
                    if read_r > best_rate:
                        best_rate, best_bc = read_r, bc
                if best_bc:
                    best_bc_name = f'"{best_bc.name[:30]}" ({int(best_rate)}% read)'

            # Top product & offer from Redis counters
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
        await adapter.send_message(phone=sender_phone, message=stats_text)

        # Send toggle button for the other time window
        other_days   = 30 if analytics_days == 7 else 7
        toggle_label = f"📅 View Last {other_days} Days"
        toggle_id    = f"analytics_{other_days}days"
        await adapter.send_interactive_message(
            phone=sender_phone,
            body="Switch time window:",
            buttons=[{"id": toggle_id, "title": toggle_label}],
            use_list=False,
        )
        return Response(status_code=200, content="ok")

    # ── UPDATE PRODUCT: <name> | <new_price> ─────────────────────────────────
    update_prod_match = re.match(r"(?i)^update\s+product:\s*(.+?)\s*\|\s*([\d.]+)\s*$", msg.strip())
    if update_prod_match:
        name       = update_prod_match.group(1).strip()
        new_price  = float(update_prod_match.group(2))
        async with AsyncSessionLocal() as db:
            product = (await db.execute(
                select(Product).where(Product.name.ilike(f"%{name}%"), Product.is_active == True)
            )).scalar_one_or_none()
            if not product:
                await adapter.send_message(
                    phone=sender_phone,
                    message=f"⚠️ No active product found matching: *{name}*",
                )
            else:
                old_price = product.price
                product.price = new_price
                await db.commit()
                await adapter.send_message(
                    phone=sender_phone,
                    message=(
                        f"✅ *Price updated!*\n\n"
                        f"🛍️ Product: *{product.name}*\n"
                        f"💰 Old price: ₹{old_price:,.0f}\n"
                        f"💰 New price: ₹{new_price:,.0f}"
                    ),
                )
                if message_id:
                    await adapter.send_reaction(sender_phone, message_id, "👍")
                logger.info(f"[CMD] Product price updated: {product.name} → ₹{new_price}")
        return Response(status_code=200, content="ok")

    # ── /kb — list knowledge base documents ──────────────────────────────────
    if msg.lower().strip() == "/kb":
        async with AsyncSessionLocal() as db:
            from models.models import KnowledgeBase
            rows = (await db.execute(
                select(KnowledgeBase).where(KnowledgeBase.is_active == True).order_by(KnowledgeBase.created_at.desc())
            )).scalars().all()
            if not rows:
                await adapter.send_message(phone=sender_phone, message="📚 No documents in the knowledge base yet.")
            else:
                lines = [f"📚 *Knowledge Base ({len(rows)} docs)*"]
                for i, kb in enumerate(rows, 1):
                    chunks = len(kb.chroma_ids) if kb.chroma_ids else 0
                    date = kb.created_at.strftime("%d %b, %H:%M")
                    # Make legacy owner_upload_* filenames human-readable
                    display_name = kb.filename
                    if display_name.startswith("owner_upload_"):
                        display_name = f"{kb.category.capitalize()} doc — {date}"
                    lines.append(
                        f"\n{i}. *{display_name}*\n"
                        f"   🏷️ {kb.category} | 📄 {chunks} chunks | 📅 {date}"
                    )
                await adapter.send_message(phone=sender_phone, message="\n".join(lines))
        return Response(status_code=200, content="ok")

    # ── No command matched — owner is testing the RAG bot ────────────────────
    logger.info(f"[CMD] No command matched — routing to RAG bot: {msg[:60]}")
    return None  # Caller should fall through to the RAG bot
