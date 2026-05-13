import logging
import re
from datetime import datetime, timezone
import httpx
from fastapi import Response
from core.config import settings
from core.database import AsyncSessionLocal
from services.client_service import import_clients, parse_upload_file, detect_column_mapping
from services import knowledge_service
from services.messaging_adapter import get_messaging_adapter
from services.products_offers_service import bulk_import_products, bulk_import_offers, parse_products_file, parse_offers_file
from handlers.owner_commands.base import BaseCommand, CommandPayload, register_upload_handler

logger = logging.getLogger(__name__)

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

@register_upload_handler()
class UploadCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response | None:
        if not payload.media_url or not payload.media_type:
            return None

        adapter = get_messaging_adapter()
        media_type = payload.media_type.lower()
        
        # ── Spreadsheet / Bulk Import ─────────────────────────────────────────
        if media_type in _CLIENT_SHEET_TYPES:
            caption = (payload.msg or "").strip().lower()
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
                    
                    resp = await hclient.get(payload.media_url, auth=req_auth, headers=req_headers)
                    resp.raise_for_status()
                    file_bytes = resp.content

                ext = ".xlsx" if "spreadsheetml" in media_type else ".csv"
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

                await adapter.send_message(phone=payload.sender_phone, message=response_msg)
                logger.info(f"[CMD] {target.capitalize()} import: {imported} imported, {skipped} skipped")
            except Exception as exc:
                logger.error(f"[CMD] {target.capitalize()} import failed: {exc}", exc_info=True)
                try:
                    await adapter.send_message(phone=payload.sender_phone, message=f"❌ {target.capitalize()} import failed. Check server logs for details.")
                except Exception:
                    pass
            return Response(status_code=200, content="ok")

        # ── Document / Knowledge Base Ingestion ──────────────────────────────
        if media_type in _INGESTABLE_TYPES:
            logger.info(f"[CMD] Document received: {media_type} — ingesting into KB")
            try:
                async with httpx.AsyncClient(timeout=settings.file_download_timeout_seconds, follow_redirects=True) as hclient:
                    req_headers = {}
                    req_auth = None
                    if settings.messaging_provider == "twilio" and settings.twilio_account_sid:
                        req_auth = (settings.twilio_account_sid, settings.twilio_auth_token)
                    elif settings.messaging_provider == "meta" and settings.meta_access_token:
                        req_headers = {"Authorization": f"Bearer {settings.meta_access_token}"}

                    resp = await hclient.get(payload.media_url, auth=req_auth, headers=req_headers)
                    resp.raise_for_status()
                    file_bytes = resp.content

                ext = _KB_EXT_MAP.get(media_type, ".bin")
                caption_words = (payload.msg or "").strip()
                
                valid_categories = {"products", "offers", "documents", "broadcasts"}
                caption_lower = caption_words.lower()
                category = caption_lower if caption_lower in valid_categories else "documents"

                is_just_category = caption_lower in ("", "products", "offers", "documents", "broadcasts")
                if not is_just_category and len(caption_words) > 2:
                    safe_name = re.sub(r'[^\w\s\-.]', '', caption_words)[:60].strip().replace(' ', '_')
                    filename = f"{safe_name}{ext}"
                else:
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
                    phone=payload.sender_phone,
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
                logger.error(f"[CMD] KB ingestion failed: {exc}", exc_info=True)
                try:
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message="❌ Failed to ingest document. Check server logs for details.",
                    )
                except Exception:
                    pass
            return Response(status_code=200, content="ok")

        # Return None if it's media but not spreadsheet or document, falling back
        return None
