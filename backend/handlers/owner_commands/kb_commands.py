import logging
from fastapi import Response
from sqlalchemy import select
from core.database import AsyncSessionLocal
from models.models import KnowledgeBase
from services.messaging_adapter import get_messaging_adapter
from handlers.owner_commands.base import BaseCommand, CommandPayload, register_command

logger = logging.getLogger(__name__)

@register_command(r"/kb", exact=True)
class KBCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(KnowledgeBase).where(KnowledgeBase.is_active == True).order_by(KnowledgeBase.created_at.desc())
            )).scalars().all()
            if not rows:
                await adapter.send_message(phone=payload.sender_phone, message="📚 No documents in the knowledge base yet.")
            else:
                lines = [f"📚 *Knowledge Base ({len(rows)} docs)*"]
                for i, kb in enumerate(rows, 1):
                    chunks = len(kb.chroma_ids) if kb.chroma_ids else 0
                    date = kb.created_at.strftime("%d %b, %H:%M")
                    display_name = kb.filename
                    if display_name.startswith("owner_upload_"):
                        display_name = f"{kb.category.capitalize()} doc — {date}"
                    lines.append(
                        f"\n{i}. *{display_name}*\n"
                        f"   🏷️ {kb.category} | 📄 {chunks} chunks | 📅 {date}"
                    )
                await adapter.send_message(phone=payload.sender_phone, message="\n".join(lines))
        return Response(status_code=200, content="ok")
