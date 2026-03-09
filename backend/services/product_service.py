"""
Product service — CRUD for the products table.
"""
import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from models.models import Product


# ─── Serialiser ───────────────────────────────────────────────────────────────

def _product_dict(p: Product) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "price": p.price,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ─── List ─────────────────────────────────────────────────────────────────────

async def list_products(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> dict:
    q = select(Product).where(Product.tenant_id == tenant_id)

    if is_active is not None:
        q = q.where(Product.is_active == is_active)

    if search:
        term = f"%{search}%"
        q = q.where(
            or_(
                Product.name.ilike(term),
                Product.description.ilike(term),
            )
        )

    total_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(total_q)).scalar_one()

    q = q.order_by(Product.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    return {
        "products": [_product_dict(p) for p in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


# ─── Create ───────────────────────────────────────────────────────────────────

async def create_product(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    name: str,
    description: Optional[str],
    price: Optional[float],
    is_active: bool = True,
) -> dict:
    product = Product(
        tenant_id=tenant_id,
        name=name,
        description=description,
        price=price,
        is_active=is_active,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return _product_dict(product)


# ─── Get or 404 ───────────────────────────────────────────────────────────────

async def get_product_or_404(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_id: uuid.UUID,
) -> Product:
    result = await db.execute(
        select(Product).where(
            Product.id == product_id,
            Product.tenant_id == tenant_id,
        )
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


# ─── Update ───────────────────────────────────────────────────────────────────

async def update_product(
    db: AsyncSession,
    product: Product,
    fields: dict,
) -> dict:
    for key, value in fields.items():
        if hasattr(product, key):
            setattr(product, key, value)
    await db.commit()
    await db.refresh(product)
    return _product_dict(product)


# ─── Delete ───────────────────────────────────────────────────────────────────

async def delete_product(db: AsyncSession, product: Product) -> None:
    await db.delete(product)
    await db.commit()
