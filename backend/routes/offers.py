"""
Offers routes
  GET    /offers          — list all offers (paginated)
  POST   /offers          — create an offer
  PATCH  /offers/{id}     — update / archive
  DELETE /offers/{id}     — delete
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.database import get_db
from core.security import get_tenant_id
from core.responses import success_response
from services import offer_service

router = APIRouter(prefix="/offers", tags=["Offers"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class CreateOfferRequest(BaseModel):
    title: str
    description: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None


class UpdateOfferRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    is_active: Optional[bool] = None  # set False to archive


# ─── GET /offers ──────────────────────────────────────────────────────────────

@router.get("")
async def list_offers(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    tenant_id: str = Depends(get_tenant_id),
    db=Depends(get_db),
):
    result = await offer_service.list_offers(
        db=db,
        tenant_id=uuid.UUID(tenant_id),
        page=page,
        page_size=page_size,
    )
    return success_response(result)


# ─── POST /offers ─────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_offer(
    body: CreateOfferRequest,
    tenant_id: str = Depends(get_tenant_id),
    db=Depends(get_db),
):
    result = await offer_service.create_offer(
        db=db,
        tenant_id=uuid.UUID(tenant_id),
        title=body.title,
        description=body.description,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
    )
    return success_response(result, status_code=201)


# ─── PATCH /offers/{id} ───────────────────────────────────────────────────────

@router.patch("/{offer_id}")
async def update_offer(
    offer_id: uuid.UUID,
    body: UpdateOfferRequest,
    tenant_id: str = Depends(get_tenant_id),
    db=Depends(get_db),
):
    offer = await offer_service.get_offer_or_404(db, uuid.UUID(tenant_id), offer_id)
    result = await offer_service.update_offer(db, offer, body.model_dump(exclude_none=True))
    return success_response(result)


# ─── DELETE /offers/{id} ──────────────────────────────────────────────────────

@router.delete("/{offer_id}", status_code=204)
async def delete_offer(
    offer_id: uuid.UUID,
    tenant_id: str = Depends(get_tenant_id),
    db=Depends(get_db),
):
    offer = await offer_service.get_offer_or_404(db, uuid.UUID(tenant_id), offer_id)
    await offer_service.delete_offer(db, offer)
