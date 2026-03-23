"""
Knowledge Base periodic tasks — Celery Beat.

Tasks:
- deactivate_expired_offers: daily — marks KnowledgeBase offers past
  their valid_until date as is_active=False in both Postgres and ChromaDB.

IMPORTANT: The beat schedule in core/celery_app.py references the task name
    "tasks.knowledge_tasks.deactivate_expired_offers"
This file MUST define the task with exactly that name to avoid the
"Task not found" silent failure exposed in TC-029.
"""
import asyncio
import logging
from datetime import datetime, timezone

from core.celery_app import celery_app
from core.database import get_async_sessionmaker

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.knowledge_tasks.deactivate_expired_offers")
def deactivate_expired_offers():
    """
    Daily beat task — deactivates KnowledgeBase entries whose valid_until
    date has passed. Also removes stale chunks from ChromaDB so the RAG
    bot stops returning expired offer information.

    Runs every 86400 seconds (24 hours) as configured in celery_app.py.
    """
    asyncio.run(_deactivate_expired_offers_async())


async def _deactivate_expired_offers_async():
    from sqlalchemy import select, update
    from models.models import KnowledgeBase

    AsyncSessionLocal = get_async_sessionmaker()
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)

        # Find all active offers whose valid_until has passed
        result = await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.category == "offers",
                KnowledgeBase.is_active == True,
                KnowledgeBase.valid_until < now,
            )
        )
        expired_records = result.scalars().all()

        if not expired_records:
            logger.info("[KB BEAT] No expired offers found — skipping")
            return

        # Remove from ChromaDB first (best-effort)
        try:
            from services.knowledge_service import get_chroma_collection
            collection = get_chroma_collection()
            for record in expired_records:
                if record.chroma_ids:
                    collection.delete(ids=record.chroma_ids)
                    logger.info(
                        f"[KB BEAT] Removed {len(record.chroma_ids)} ChromaDB vectors "
                        f"for expired offer doc {record.id}"
                    )
        except Exception as e:
            logger.warning(f"[KB BEAT] ChromaDB cleanup warning (non-fatal): {e}")

        # Mark inactive in Postgres
        expired_ids = [r.id for r in expired_records]
        await db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id.in_(expired_ids))
            .values(is_active=False)
        )
        await db.commit()
        logger.info(f"[KB BEAT] Deactivated {len(expired_ids)} expired offer document(s)")
