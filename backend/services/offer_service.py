"""
Offer service — CRUD for the offers table.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from models.models import Offer


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _compute_status(offer: Offer) -> str:
    """Compute display status: active | upcoming | expired | archived."""
    if not offer.is_active:
        return "archived"
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC comparison
    until = offer.valid_until.replace(tzinfo=None) if offer.valid_until else None
    frm = offer.valid_from.replace(tzinfo=None) if offer.valid_from else None

    if until and until < now:
        return "expired"
    if frm and frm > now:
        return "upcoming"
    return "active"


def _offer_dict(o: Offer) -> dict:
    return {
        "id": str(o.id),
        "title": o.title,
        "description": o.description,
        "valid_from": o.valid_from.isoformat() if o.valid_from else None,
        "valid_until": o.valid_until.isoformat() if o.valid_until else None,
        "is_active": o.is_active,
        "status": _compute_status(o),
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


# ─── List ─────────────────────────────────────────────────────────────────────

async def list_offers(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    q = select(Offer).where(Offer.tenant_id == tenant_id)

    total_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(total_q)).scalar_one()

    q = q.order_by(Offer.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    return {
        "offers": [_offer_dict(o) for o in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


# ─── Create ───────────────────────────────────────────────────────────────────

async def create_offer(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    title: str,
    description: Optional[str],
    valid_from: Optional[datetime],
    valid_until: Optional[datetime],
) -> dict:
    offer = Offer(
        tenant_id=tenant_id,
        title=title,
        description=description,
        valid_from=valid_from,
        valid_until=valid_until,
        is_active=True,
    )
    db.add(offer)
    await db.commit()
    await db.refresh(offer)
    return _offer_dict(offer)


# ─── Get or 404 ───────────────────────────────────────────────────────────────

async def get_offer_or_404(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    offer_id: uuid.UUID,
) -> Offer:
    result = await db.execute(
        select(Offer).where(
            Offer.id == offer_id,
            Offer.tenant_id == tenant_id,
        )
    )
    offer = result.scalar_one_or_none()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    return offer


# ─── Update ───────────────────────────────────────────────────────────────────

async def update_offer(
    db: AsyncSession,
    offer: Offer,
    fields: dict,
) -> dict:
    for key, value in fields.items():
        if hasattr(offer, key):
            setattr(offer, key, value)
    await db.commit()
    await db.refresh(offer)
    return _offer_dict(offer)


# ─── Delete ───────────────────────────────────────────────────────────────────

async def delete_offer(db: AsyncSession, offer: Offer) -> None:
    await db.delete(offer)
    await db.commit()
