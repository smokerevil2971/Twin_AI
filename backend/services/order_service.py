"""
Order service — CRUD for the orders table.
Joins with Client to return client_name and client_phone with each order.
"""
import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload

from models.models import Order, Client


# ─── Serialiser ───────────────────────────────────────────────────────────────

def _order_dict(o: Order, client: Optional[Client] = None) -> dict:
    return {
        "id":           str(o.id),
        "client_id":    str(o.client_id),
        "client_name":  client.name  if client else None,
        "client_phone": client.phone if client else None,
        "product_name": o.product_name,
        "amount":       o.amount,
        "status":       o.status,
        "invoice_path": o.invoice_path,
        "created_at":   o.created_at.isoformat() if o.created_at else None,
        "updated_at":   o.updated_at.isoformat() if o.updated_at else None,
    }


# ─── List ─────────────────────────────────────────────────────────────────────

async def list_orders(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    page: int = 1,
    page_size: int = 25,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> dict:
    q = (
        select(Order, Client)
        .join(Client, Order.client_id == Client.id, isouter=True)
        .where(Order.tenant_id == tenant_id)
    )

    if status:
        q = q.where(Order.status == status)

    if search:
        term = f"%{search}%"
        q = q.where(
            func.lower(Client.name).like(func.lower(term)) |
            func.lower(Order.product_name).like(func.lower(term))
        )

    total_q = select(func.count()).select_from(
        select(Order).where(Order.tenant_id == tenant_id).subquery()
    )
    total = (await db.execute(total_q)).scalar_one()

    q = q.order_by(Order.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).all()

    return {
        "orders":    [_order_dict(o, c) for o, c in rows],
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "pages":     max(1, (total + page_size - 1) // page_size),
    }


# ─── Create ───────────────────────────────────────────────────────────────────

async def create_order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    client_id: uuid.UUID,
    product_name: str,
    amount: float,
    status: str = "pending",
) -> dict:
    # Verify client belongs to this tenant
    client_row = await db.execute(
        select(Client).where(Client.id == client_id, Client.tenant_id == tenant_id)
    )
    client = client_row.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    order = Order(
        tenant_id=tenant_id,
        client_id=client_id,
        product_name=product_name,
        amount=amount,
        status=status,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return _order_dict(order, client)


# ─── Get or 404 ───────────────────────────────────────────────────────────────

async def get_order_or_404(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    order_id: uuid.UUID,
) -> tuple[Order, Optional[Client]]:
    row = await db.execute(
        select(Order, Client)
        .join(Client, Order.client_id == Client.id, isouter=True)
        .where(Order.id == order_id, Order.tenant_id == tenant_id)
    )
    result = row.first()
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    return result  # (Order, Client)


# ─── Update status ────────────────────────────────────────────────────────────

VALID_STATUSES = {"pending", "confirmed", "cancelled"}

async def update_order(
    db: AsyncSession,
    order: Order,
    fields: dict,
) -> None:
    if "status" in fields and fields["status"] not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}")
    for key, value in fields.items():
        if hasattr(order, key):
            setattr(order, key, value)
    await db.commit()
    await db.refresh(order)


# ─── Delete ───────────────────────────────────────────────────────────────────

async def delete_order(db: AsyncSession, order: Order) -> None:
    await db.delete(order)
    await db.commit()
