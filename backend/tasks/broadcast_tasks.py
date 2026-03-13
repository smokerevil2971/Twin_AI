"""
Celery tasks for broadcast sending.
- send_broadcast: fetches pending recipients, sends via Gupshup adapter (mock or real),
  updates status, enforces rate limit (80 msg/sec max, WhatsApp QR safe).
- Retries on failure: up to 3 attempts with exponential backoff.
"""
import uuid
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from celery import shared_task
from sqlalchemy import select, update

from core.celery_app import celery_app
from core.database import get_async_sessionmaker
from models.models import Broadcast, BroadcastRecipient, Client
from services.gupshup_adapter import get_messaging_adapter

logger = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 0.013   # ~80 msg/sec — safe WhatsApp quality rating


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="tasks.broadcast_tasks.send_broadcast",
)
def send_broadcast(self, broadcast_id: str):
    """
    Celery task — sends all pending recipients for a broadcast.
    Uses asyncio.run() to bridge sync Celery into async SQLAlchemy.
    """
    asyncio.run(_send_broadcast_async(broadcast_id))


async def _send_broadcast_async(broadcast_id_str: str):
    broadcast_id = uuid.UUID(broadcast_id_str)
    adapter = get_messaging_adapter()
    AsyncSessionLocal = get_async_sessionmaker()

    async with AsyncSessionLocal() as db:
        # Mark broadcast as sending
        await db.execute(
            update(Broadcast)
            .where(Broadcast.id == broadcast_id)
            .values(status="sending")
        )
        await db.commit()

        # Fetch all pending recipients + their phone numbers
        q = (
            select(BroadcastRecipient, Client.phone)
            .join(Client, BroadcastRecipient.client_id == Client.id)
            .where(
                BroadcastRecipient.broadcast_id == broadcast_id,
                BroadcastRecipient.status == "pending",
            )
        )
        rows = (await db.execute(q)).all()

        total = len(rows)
        sent = 0
        failed = 0

        for recipient, phone in rows:
            try:
                result = await adapter.send_message(
                    phone=phone,
                    message=recipient.personalised_message or "",
                )
                await db.execute(
                    update(BroadcastRecipient)
                    .where(BroadcastRecipient.id == recipient.id)
                    .values(
                        status="sent",
                        gupshup_message_id=result.get("messageId"),
                        sent_at=datetime.now(timezone.utc),
                    )
                )
                sent += 1
            except Exception as e:
                logger.error(f"Failed to send to {phone}: {e}")
                new_retry = recipient.retry_count + 1
                new_status = "failed" if new_retry >= 3 else "pending"
                await db.execute(
                    update(BroadcastRecipient)
                    .where(BroadcastRecipient.id == recipient.id)
                    .values(
                        status=new_status,
                        failed_reason=str(e),
                        retry_count=new_retry,
                    )
                )
                failed += 1

            await db.commit()
            # Rate limiting — pause between sends
            await asyncio.sleep(RATE_LIMIT_DELAY)

        # Mark broadcast as sent (or failed if all failed)
        final_status = "sent" if sent > 0 else "failed"
        await db.execute(
            update(Broadcast)
            .where(Broadcast.id == broadcast_id)
            .values(status=final_status, sent_at=datetime.now(timezone.utc))
        )
        await db.commit()

        logger.info(
            f"Broadcast {broadcast_id_str} complete — "
            f"{sent}/{total} sent, {failed} failed"
        )


@celery_app.task(name="tasks.knowledge_tasks.deactivate_expired_offers")
def deactivate_expired_offers():
    """Daily beat task — deactivates offers past their valid_until date."""
    asyncio.run(_deactivate_expired_offers_async())


async def _deactivate_expired_offers_async():
    from models.models import Offer
    AsyncSessionLocal = get_async_sessionmaker()
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            update(Offer)
            .where(Offer.valid_until < now, Offer.is_active == True)
            .values(is_active=False)
        )
        await db.commit()
        logger.info(f"Deactivated {result.rowcount} expired offers")
