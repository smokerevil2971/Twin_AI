"""
Products routes
  GET    /products          — paginated list (search, is_active filter)
  POST   /products          — create a product
  PATCH  /products/{id}     — update fields
  DELETE /products/{id}     — delete
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.database import get_db
from core.security import get_tenant_id
from core.responses import success_response
from services import product_service

router = APIRouter(prefix="/products", tags=["Products"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class CreateProductRequest(BaseModel):
    name: str
    description: Optional[str] = None
    price: Optional[float] = None
    is_active: bool = True


class UpdateProductRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    is_active: Optional[bool] = None


# ─── GET /products ─────────────────────────────────────────────────────────────

@router.get("")
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    tenant_id: str = Depends(get_tenant_id),
    db=Depends(get_db),
):
    result = await product_service.list_products(
        db=db,
        tenant_id=uuid.UUID(tenant_id),
        page=page,
        page_size=page_size,
        search=search,
        is_active=is_active,
    )
    return success_response(result)


# ─── POST /products ───────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_product(
    body: CreateProductRequest,
    tenant_id: str = Depends(get_tenant_id),
    db=Depends(get_db),
):
    result = await product_service.create_product(
        db=db,
        tenant_id=uuid.UUID(tenant_id),
        name=body.name,
        description=body.description,
        price=body.price,
        is_active=body.is_active,
    )
    return success_response(result, status_code=201)


# ─── PATCH /products/{id} ─────────────────────────────────────────────────────

@router.patch("/{product_id}")
async def update_product(
    product_id: uuid.UUID,
    body: UpdateProductRequest,
    tenant_id: str = Depends(get_tenant_id),
    db=Depends(get_db),
):
    product = await product_service.get_product_or_404(db, uuid.UUID(tenant_id), product_id)
    result = await product_service.update_product(db, product, body.model_dump(exclude_none=True))
    return success_response(result)


# ─── DELETE /products/{id} ────────────────────────────────────────────────────

@router.delete("/{product_id}", status_code=204)
async def delete_product(
    product_id: uuid.UUID,
    tenant_id: str = Depends(get_tenant_id),
    db=Depends(get_db),
):
    product = await product_service.get_product_or_404(db, uuid.UUID(tenant_id), product_id)
    await product_service.delete_product(db, product)
