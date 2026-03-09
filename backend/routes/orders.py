import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
import httpx

from core.database import get_db
from core.security import get_tenant_id
from core.responses import success_response
from services.order_service import (
    list_orders,
    create_order,
    get_order_or_404,
    update_order,
    delete_order,
)

router = APIRouter(prefix="/orders", tags=["orders"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    client_id: uuid.UUID
    product_name: str
    amount: float
    status: str = "pending"


class UpdateOrderRequest(BaseModel):
    status: Optional[str] = None
    invoice_path: Optional[str] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def get_orders_route(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """List orders for the current tenant (with optional filters)."""
    data = await list_orders(
        db=db,
        tenant_id=uuid.UUID(tenant_id),
        page=page,
        page_size=page_size,
        status=status,
        search=search,
    )
    return success_response(data)


@router.post("", status_code=201)
async def create_order_route(
    body: CreateOrderRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a new order linked to a client."""
    order_dict = await create_order(
        db=db,
        tenant_id=uuid.UUID(tenant_id),
        client_id=body.client_id,
        product_name=body.product_name,
        amount=body.amount,
        status=body.status,
    )
    return success_response(order_dict, status_code=201)


@router.patch("/{order_id}")
async def patch_order_route(
    order_id: uuid.UUID,
    body: UpdateOrderRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Update order details (e.g. mark confirmed/cancelled)."""
    order, client = await get_order_or_404(db, uuid.UUID(tenant_id), order_id)
    await update_order(db, order, body.model_dump(exclude_none=True))
    from services.order_service import _order_dict
    return success_response(_order_dict(order, client))


@router.delete("/{order_id}", status_code=204)
async def delete_order_route(
    order_id: uuid.UUID,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete an order."""
    order, _ = await get_order_or_404(db, uuid.UUID(tenant_id), order_id)
    await delete_order(db, order)

