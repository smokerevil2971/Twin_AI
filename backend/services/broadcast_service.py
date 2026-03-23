"""
Broadcast service — CRUD, eligibility checks, personalisation, delivery stats.
Multi-tenancy removed — single owner system.
"""
import uuid
import csv
import io
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from fastapi import HTTPException
from openai import OpenAI

from core.config import settings
from models.models import Broadcast, BroadcastRecipient, Client

logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


def personalise(template: str, client: Client) -> str:
    """Replace {{name}}, {{1}} etc. with client fields."""
    return (
        template
        .replace("{{name}}", client.name)
        .replace("{{1}}", client.name)
        .replace("{{phone}}", client.phone)
    )


async def ai_personalise(owner_message: str, client: Client) -> str:
    """
    Use NIM llama-4-maverick to generate a unique personalised message for
    each client based on their name and preferred language.
    Falls back to basic template substitution if NIM call fails.
    """
    lang_label = "Hindi" if client.language == "hi" else "English"
    prompt = (
        f"You are a WhatsApp sales assistant for a solar energy company.\n"
        f"The business owner wants to send this message to a client:\n"
        f'"{owner_message}"\n\n'
        f"Client profile:\n"
        f"- Name: {client.name}\n"
        f"- Preferred language: {lang_label}\n\n"
        f"Write a personalised WhatsApp message for this specific client:\n"
        f"- Address them by name naturally\n"
        f"- Write entirely in {lang_label}\n"
        f"- Keep it 2-3 sentences, friendly and concise\n"
        f"- Preserve the owner's core offer/information\n"
        f"- Do NOT add subject lines or formal greetings like 'Dear'\n"
        f"Respond with ONLY the message text, nothing else."
    )
    try:
        nim_client = OpenAI(
            base_url=settings.nim_base_url,
            api_key=settings.nim_llm_api_key,
        )
        resp = nim_client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
            temperature=0.8,
        )
        text = (resp.choices[0].message.content or "").strip()
        if text:
            logger.info(f"[BROADCAST] NIM personalised for {client.name} ({lang_label})")
            return text
    except Exception as e:
        logger.warning(f"[BROADCAST] NIM personalisation failed for {client.name}: {e}")
    # Fallback: basic template substitution
    return personalise(owner_message, client)


async def get_eligible_clients(
    db: AsyncSession,
    client_ids: Optional[list[uuid.UUID]] = None,
) -> list[Client]:
    """
    Returns clients that are:
    - opted_in = True
    - not soft-deleted
    - not messaged in the last 24 hours
    """
    q = select(Client).where(
        Client.opted_in == True,
        Client.is_deleted == False,
    )
    if client_ids:
        q = q.where(Client.id.in_(client_ids))

    clients = (await db.execute(q)).scalars().all()

    if not settings.broadcast_cooldown_enabled:
        return list(clients)

    # Filter out clients messaged within the cooldown window
    cutoff = utcnow() - timedelta(hours=settings.broadcast_cooldown_hours)
    recently_messaged_q = (
        select(BroadcastRecipient.client_id)
        .where(
            BroadcastRecipient.sent_at >= cutoff,
            BroadcastRecipient.status.in_(["sent", "delivered", "read"]),
        )
    )
    recently_messaged = {
        row[0] for row in (await db.execute(recently_messaged_q)).all()
    }

    return [c for c in clients if c.id not in recently_messaged]


async def create_broadcast(
    db: AsyncSession,
    name: str,
    message_template: str,
    channel: str = "whatsapp",
    language: str = "en",
    scheduled_at: Optional[datetime] = None,
    target_client_ids: Optional[list[uuid.UUID]] = None,
    media_url: Optional[str] = None,
    media_type: Optional[str] = None,      # 'image' | 'document'
    media_filename: Optional[str] = None,  # label for document downloads
) -> dict:
    eligible = await get_eligible_clients(db, target_client_ids)

    if not eligible:
        raise HTTPException(
            status_code=422,
            detail="No eligible opted-in clients found. "
                   "Either no clients have opted in or all were messaged in the last 24 hours."
        )

    broadcast = Broadcast(
        name=name,
        message_template=message_template,
        channel=channel,
        language=language,
        status="draft",
        scheduled_at=scheduled_at,
        media_url=media_url,
        media_type=media_type,
        media_filename=media_filename,
    )
    db.add(broadcast)
    await db.flush()

    # Build recipients with AI-personalised messages
    recipients = []
    for c in eligible:
        msg = await ai_personalise(message_template, c)
        recipients.append(BroadcastRecipient(
            broadcast_id=broadcast.id,
            client_id=c.id,
            personalised_message=msg,
            status="pending",
        ))
    db.add_all(recipients)
    await db.commit()
    await db.refresh(broadcast)

    return {
        **_broadcast_dict(broadcast),
        "eligible_count": len(eligible),
    }


async def list_broadcasts(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    q = select(Broadcast)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(
            q.order_by(Broadcast.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return {
        "broadcasts": [_broadcast_dict(b) for b in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


async def get_broadcast_detail(
    db: AsyncSession,
    broadcast_id: uuid.UUID,
) -> dict:
    b = await _get_or_404(db, broadcast_id)

    recipients_q = (
        select(BroadcastRecipient, Client.name, Client.phone)
        .join(Client, BroadcastRecipient.client_id == Client.id)
        .where(BroadcastRecipient.broadcast_id == broadcast_id)
    )
    rows = (await db.execute(recipients_q)).all()

    counts = {"pending": 0, "sent": 0, "delivered": 0, "read": 0, "failed": 0}
    recipients_out = []
    for r, name, phone in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
        recipients_out.append({
            "id": str(r.id),
            "client_id": str(r.client_id),
            "client_name": name,
            "client_phone": phone,
            "personalised_message": r.personalised_message,
            "status": r.status,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
            "read_at": r.read_at.isoformat() if r.read_at else None,
            "failed_reason": r.failed_reason,
            "retry_count": r.retry_count,
        })

    return {
        **_broadcast_dict(b),
        "stats": counts,
        "recipients": recipients_out,
    }


async def export_broadcast_csv(
    db: AsyncSession,
    broadcast_id: uuid.UUID,
) -> str:
    await _get_or_404(db, broadcast_id)

    rows_q = (
        select(BroadcastRecipient, Client.name, Client.phone)
        .join(Client, BroadcastRecipient.client_id == Client.id)
        .where(BroadcastRecipient.broadcast_id == broadcast_id)
    )
    rows = (await db.execute(rows_q)).all()

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["client_name", "phone", "status", "sent_at",
                    "delivered_at", "read_at", "failed_reason", "retry_count"]
    )
    writer.writeheader()
    for r, name, phone in rows:
        writer.writerow({
            "client_name": name,
            "phone": phone,
            "status": r.status,
            "sent_at": r.sent_at.isoformat() if r.sent_at else "",
            "delivered_at": r.delivered_at.isoformat() if r.delivered_at else "",
            "read_at": r.read_at.isoformat() if r.read_at else "",
            "failed_reason": r.failed_reason or "",
            "retry_count": r.retry_count,
        })
    return output.getvalue()


async def _get_or_404(db: AsyncSession, broadcast_id: uuid.UUID) -> Broadcast:
    result = await db.execute(
        select(Broadcast).where(Broadcast.id == broadcast_id)
    )
    b = result.scalar_one_or_none()
    if not b:
        raise HTTPException(404, "Broadcast not found")
    return b


def _broadcast_dict(b: Broadcast) -> dict:
    return {
        "id": str(b.id),
        "name": b.name,
        "message_template": b.message_template,
        "channel": b.channel,
        "language": b.language,
        "status": b.status,
        "scheduled_at": b.scheduled_at.isoformat() if b.scheduled_at else None,
        "sent_at": b.sent_at.isoformat() if b.sent_at else None,
        "created_at": b.created_at.isoformat(),
    }
