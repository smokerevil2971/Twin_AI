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
from core.config import settings
from core.database import get_async_sessionmaker
from models.models import Broadcast, BroadcastRecipient, Client, Offer
from services.messaging_adapter import get_messaging_adapter

logger = logging.getLogger(__name__)


# ─── 3.5: Offer Expiry Check ──────────────────────────────────────────────────

@celery_app.task(name="tasks.broadcast_tasks.check_expiring_offers")
def check_expiring_offers():
    """
    Celery Beat task — runs daily at 8 AM IST (2:30 AM UTC).
    For each offer expiring within the next 24 hours, sends the owner an
    interactive WhatsApp message with two choices:
      [ 📢 Broadcast Reminder ] — auto-queues a client broadcast
      [ ❌ Skip ]               — no action taken
    No client messages are sent without explicit owner approval.
    """
    async def _run():
        from sqlalchemy import select
        # LOW-04 fix: `from core.database import AsyncSessionLocal` imports the
        # module-level session factory which is bound to the main process event loop.
        # Celery tasks run in a DIFFERENT event loop (via asyncio.new_event_loop()),
        # so using the main engine here raises: "Future attached to different loop".
        # get_async_sessionmaker() creates a fresh SQLAlchemy async engine + session
        # factory that is safe to use in any event loop.
        from core.database import get_async_sessionmaker
        AsyncSessionLocal = get_async_sessionmaker()

        now = datetime.now(timezone.utc)
        window_end = now + timedelta(hours=24)

        async with AsyncSessionLocal() as db:
            expiring = (await db.execute(
                select(Offer).where(
                    Offer.is_active == True,
                    Offer.valid_until >= now,
                    Offer.valid_until <= window_end,
                )
            )).scalars().all()

            if not expiring:
                logger.info("[EXPIRY] No offers expiring in next 24h")
                return

            adapter = get_messaging_adapter()

            for offer in expiring:
                # Count opted-in clients who haven't been messaged recently
                from core.redis_client import get_redis
                r = get_redis()
                # Store pending state so webhook can handle the owner's button tap
                key = f"expiry_pending:{offer.id}"
                await r.set(key, str(offer.id), ex=48 * 3600)  # 48h TTL

                expires_str = offer.valid_until.strftime("%d %b at %I:%M %p") if offer.valid_until else "soon"
                body = (
                    f"⚠️ *Offer Expiring Tomorrow!*\n\n"
                    f'*"{offer.title}"* expires on {expires_str}\n\n'
                    f"Should we send a reminder broadcast to subscribed clients?"
                )
                try:
                    await adapter.send_interactive_message(
                        phone=settings.owner_phone,
                        body=body,
                        buttons=[
                            {"id": f"broadcast_expiry_{offer.id}", "title": "📢 Broadcast Reminder"},
                            {"id": f"skip_expiry_{offer.id}",      "title": "❌ Skip"},
                        ],
                        use_list=False,
                    )
                    logger.info(f"[EXPIRY] Sent expiry alert to owner for offer: {offer.title}")
                except Exception as e:
                    logger.error(f"[EXPIRY] Failed to send alert for {offer.title}: {e}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()



@celery_app.task(
    bind=True,
    max_retries=settings.broadcast_max_retries,
    default_retry_delay=settings.broadcast_retry_delay_seconds,
    name="tasks.broadcast_tasks.send_broadcast",
)
def send_broadcast(self, broadcast_id: str):
    """
    Celery task — sends all pending recipients for a broadcast.
    Uses asyncio.run() to bridge sync Celery into async SQLAlchemy.

    Retries up to 3 times (60s, 120s, 240s) on catastrophic failures
    (e.g., DB down, unhandled exception in the async runner).
    Per-recipient send failures are handled gracefully inside
    _send_broadcast_async and do NOT trigger a task-level retry.
    """
    try:
        asyncio.run(_send_broadcast_async(broadcast_id))
    except Exception as exc:
        logger.error(
            f"[BROADCAST] Task failed for broadcast_id={broadcast_id}: {exc}. "
            f"Attempt {self.request.retries + 1}/{self.max_retries + 1}."
        )
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


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

        # Fetch broadcast media fields once
        bc_row = await db.execute(select(Broadcast).where(Broadcast.id == broadcast_id))
        broadcast = bc_row.scalar_one_or_none()
        media_url = broadcast.media_url if broadcast else None
        media_type = broadcast.media_type if broadcast else None
        media_filename = (broadcast.media_filename or "document.pdf") if broadcast else "document.pdf"

        total = len(rows)
        sent = 0
        failed = 0

        # MED-03 fix: Previously committed after every single recipient (1 DB round-trip
        # per send). For a 500-recipient broadcast that was 500 commits — each one is a
        # synchronous Postgres round-trip adding ~2-5 ms, totalling 1-2.5 seconds of
        # pure DB overhead. Now we batch commits every 50 recipients.
        COMMIT_BATCH_SIZE = 50

        for i, (recipient, phone) in enumerate(rows):
            try:
                if media_url and media_type:
                    # Media broadcast — send image or document with caption
                    result = await adapter.send_media_message(
                        phone=phone,
                        media_url=media_url,
                        media_type=media_type,
                        caption=recipient.personalised_message or "",
                        filename=media_filename,
                    )
                else:
                    # Text-only broadcast
                    result = await adapter.send_message(
                        phone=phone,
                        message=recipient.personalised_message or "",
                    )
                await db.execute(
                    update(BroadcastRecipient)
                    .where(BroadcastRecipient.id == recipient.id)
                    .values(
                        status="sent",
                        provider_message_id=result.get("messageId"),
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

            # Batch commit every N recipients instead of every single one
            if (i + 1) % COMMIT_BATCH_SIZE == 0:
                await db.commit()

            # Rate limiting — pause between sends
            await asyncio.sleep(settings.broadcast_send_delay_seconds)

        # Final flush for the remaining partial batch
        await db.commit()

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

        # Notify owner with delivery summary
        if settings.owner_phone:
            try:
                if failed == 0:
                    summary = f"✅ Broadcast delivered for {sent} client(s)."
                else:
                    summary = (
                        f"📊 Broadcast complete — "
                        f"{sent} sent, {failed} failed (out of {total})."
                    )
                await adapter.send_message(
                    phone=settings.owner_phone,
                    message=summary,
                )
            except Exception as e:
                logger.warning(f"[BROADCAST] Could not notify owner: {e}")




@celery_app.task(name="tasks.broadcast_tasks.send_flagged_digest")
def send_flagged_digest():
    """
    Periodic beat task — queries all flagged+unalerted conversations and
    sends ONE WhatsApp digest to the owner. Marks them alert_sent=True.
    Skips silently if disabled (flagged_digest_hours=0) or no owner phone set.
    """
    if not settings.flagged_digest_hours or not settings.owner_phone:
        return
    asyncio.run(_send_flagged_digest_async())


async def _send_flagged_digest_async():
    from models.models import Conversation, Client
    AsyncSessionLocal = get_async_sessionmaker()
    adapter = get_messaging_adapter()

    async with AsyncSessionLocal() as db:
        # Fetch flagged conversations not yet alerted, with optional client info
        q = (
            select(Conversation, Client.name, Client.phone)
            .outerjoin(Client, Conversation.client_id == Client.id)
            .where(
                Conversation.flagged == True,
                Conversation.alert_sent == False,
            )
            .order_by(Conversation.created_at.desc())
            .limit(settings.digest_max_items)   # cap from config
        )
        rows = (await db.execute(q)).all()

        if not rows:
            logger.info("[DIGEST] No unalerted flagged queries — skipping")
            return

        total = len(rows)
        lines = [f"\u2753 {total} unanswered quer{'y' if total==1 else 'ies'} — please follow up:\n"]
        ids_to_mark = []

        for conv, client_name, client_phone in rows:
            name_str = client_name or "Unknown"
            phone_str = client_phone or conv.client_id or "?"
            question = (conv.message or "")[:120]
            lines.append(f"\u2022 {name_str} ({phone_str})\n  \"{question}\"")
            ids_to_mark.append(conv.id)

        digest_msg = "\n\n".join(lines)

        try:
            await adapter.send_message(
                phone=settings.owner_phone,
                message=digest_msg,
            )
            logger.info(f"[DIGEST] Sent digest with {total} flagged queries to owner")
        except Exception as e:
            logger.error(f"[DIGEST] Failed to send digest: {e}")
            return

        # Mark all included conversations as alert_sent
        await db.execute(
            update(Conversation)
            .where(Conversation.id.in_(ids_to_mark))
            .values(alert_sent=True)
        )
        await db.commit()
        logger.info(f"[DIGEST] Marked {len(ids_to_mark)} conversations as alert_sent")


# ─── 2.6: Daily New-Client Digest ────────────────────────────────────────────

@celery_app.task(name="tasks.broadcast_tasks.send_new_client_digest")
def send_new_client_digest():
    """
    Celery Beat task — runs nightly at 9 PM IST.
    Finds all clients who joined in the last 24 hours and sends the owner
    a digest: how many connected, their names, and their phones.
    """
    # LOW-05 fix: `import asyncio` was duplicated — once inside `_run()` and again
    # at the bottom of the task body. `asyncio` is already imported at the module
    # top (line 8), so both in-function imports are redundant.
    async def _run():
        from core.database import get_async_sessionmaker
        from models.models import Client
        from sqlalchemy import select
        from datetime import timedelta

        # LOW-04 fix: Use get_async_sessionmaker() for Celery task safety
        AsyncSessionLocal = get_async_sessionmaker()

        async with AsyncSessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            new_clients = (await db.execute(
                select(Client)
                .where(Client.created_at >= cutoff, Client.is_deleted == False)
                .order_by(Client.created_at.asc())
            )).scalars().all()

            if not new_clients:
                logger.info("[NEW-CLIENT DIGEST] No new clients in last 24 hours — skipping")
                return

            from services.messaging_adapter import get_messaging_adapter
            adapter = get_messaging_adapter()

            lines = [f"🆕 *New Clients Today — {len(new_clients)} joined*\n"]
            for i, c in enumerate(new_clients, 1):
                # If name == phone, client never completed name capture yet
                name_display = c.name if c.name != c.phone else "_(not provided)_"
                opted = "✅ Subscribed" if c.opted_in else "❌ Not subscribed"
                lines.append(f"{i}. *{name_display}*\n   📱 {c.phone} | {opted}")

            digest_msg = "\n\n".join(lines)
            try:
                await adapter.send_message(phone=settings.owner_phone, message=digest_msg)
                logger.info(f"[NEW-CLIENT DIGEST] Sent digest for {len(new_clients)} new client(s) to owner")
            except Exception as e:
                logger.error(f"[NEW-CLIENT DIGEST] Failed to send: {e}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()
