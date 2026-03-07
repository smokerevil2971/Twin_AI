"""
Broadcast service — CRUD, eligibility checks, personalisation, delivery stats.
"""
import uuid
import csv
import io
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from fastapi import HTTPException

from models.models import (
    Broadcast, BroadcastRecipient, Client
)


def utcnow():
    return datetime.now(timezone.utc)


# ─── Personalisation ──────────────────────────────────────────────────────────

def personalise(template: str, client: Client) -> str:
    """Replace {{name}}, {{1}} etc. with client fields."""
    return (
        template
        .replace("{{name}}", client.name)
        .replace("{{1}}", client.name)
        .replace("{{phone}}", client.phone)
    )


# ─── Eligibility check ────────────────────────────────────────────────────────

async def get_eligible_clients(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    client_ids: Optional[list[uuid.UUID]] = None,
) -> list[Client]:
    """
    Returns clients that are:
    - opted_in = True
    - not soft-deleted
    - not messaged in the last 24 hours (no sent/delivered recipient row)
    - optionally filtered to a specific list of client_ids
    """
    q = select(Client).where(
        Client.tenant_id == tenant_id,
        Client.opted_in == True,
        Client.is_deleted == False,
    )
    if client_ids:
        q = q.where(Client.id.in_(client_ids))

    clients = (await db.execute(q)).scalars().all()

    # Filter out clients messaged in the last 24h
    cutoff = utcnow() - timedelta(hours=24)
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


# ─── Create broadcast ─────────────────────────────────────────────────────────

async def create_broadcast(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    name: str,
    message_template: str,
    channel: str = "whatsapp",
    language: str = "en",
    scheduled_at: Optional[datetime] = None,
    target_client_ids: Optional[list[uuid.UUID]] = None,
) -> dict:
    """
    Creates broadcast + recipient rows for all eligible clients.
    Returns broadcast dict with eligible_count.
    """
    eligible = await get_eligible_clients(db, tenant_id, target_client_ids)

    if not eligible:
        raise HTTPException(
            status_code=422,
            detail="No eligible opted-in clients found. "
                   "Either no clients have opted in or all were messaged in the last 24 hours."
        )

    broadcast = Broadcast(
        tenant_id=tenant_id,
        name=name,
        message_template=message_template,
        channel=channel,
        language=language,
        status="draft",
        scheduled_at=scheduled_at,
    )
    db.add(broadcast)
    await db.flush()  # get broadcast.id before adding recipients

    recipients = [
        BroadcastRecipient(
            broadcast_id=broadcast.id,
            client_id=c.id,
            personalised_message=personalise(message_template, c),
            status="pending",
        )
        for c in eligible
    ]
    db.add_all(recipients)
    await db.commit()
    await db.refresh(broadcast)

    return {
        **_broadcast_dict(broadcast),
        "eligible_count": len(eligible),
    }


# ─── List broadcasts ──────────────────────────────────────────────────────────

async def list_broadcasts(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    q = select(Broadcast).where(Broadcast.tenant_id == tenant_id)
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


# ─── Get broadcast detail + per-client stats ──────────────────────────────────

async def get_broadcast_detail(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    broadcast_id: uuid.UUID,
) -> dict:
    b = await _get_or_404(db, tenant_id, broadcast_id)

    recipients_q = (
        select(BroadcastRecipient, Client.name, Client.phone)
        .join(Client, BroadcastRecipient.client_id == Client.id)
        .where(BroadcastRecipient.broadcast_id == broadcast_id)
    )
    rows = (await db.execute(recipients_q)).all()

    # Aggregate counts
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


# ─── Export delivery report as CSV ────────────────────────────────────────────

async def export_broadcast_csv(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    broadcast_id: uuid.UUID,
) -> str:
    """Returns CSV string of per-client delivery report."""
    await _get_or_404(db, tenant_id, broadcast_id)

    rows_q = (
        select(BroadcastRecipient, Client.name, Client.phone)
        .join(Client, BroadcastRecipient.client_id == Client.id)
        .where(BroadcastRecipient.broadcast_id == broadcast_id)
    )
    rows = (await db.execute(rows_q)).all()

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["client_name", "phone", "status", "sent_at", "delivered_at", "read_at", "failed_reason", "retry_count"]
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


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_or_404(db: AsyncSession, tenant_id: uuid.UUID, broadcast_id: uuid.UUID) -> Broadcast:
    result = await db.execute(
        select(Broadcast).where(
            Broadcast.id == broadcast_id,
            Broadcast.tenant_id == tenant_id,
        )
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
