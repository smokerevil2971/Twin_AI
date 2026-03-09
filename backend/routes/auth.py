from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from core.database import get_db
from core.security import verify_password, create_access_token, hash_password, get_tenant_id
from core.responses import success_response, error_response
from models.models import Tenant

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    business_name: str
    email: str
    password: str


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tenant).where(Tenant.owner_email == body.email))
    tenant = result.scalar_one_or_none()

    if not tenant or not verify_password(body.password, tenant.owner_password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token({
        "sub": str(tenant.id),
        "tenant_id": str(tenant.id),
        "email": tenant.owner_email,
    })

    return success_response({
        "access_token": token,
        "token_type": "bearer",
        "tenant_id": str(tenant.id),
        "business_name": tenant.name,
    })


@router.post("/register", status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """One-time registration for a new tenant/business owner."""
    existing = await db.execute(select(Tenant).where(Tenant.owner_email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    tenant = Tenant(
        name=body.business_name,
        owner_email=body.email,
        owner_password_hash=hash_password(body.password),
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    token = create_access_token({
        "sub": str(tenant.id),
        "tenant_id": str(tenant.id),
        "email": tenant.owner_email,
    })

    return success_response({
        "access_token": token,
        "token_type": "bearer",
        "tenant_id": str(tenant.id),
        "business_name": tenant.name,
    }, status_code=201)


# ─────────────────────────────────────────────────────────────────────────────
# Settings endpoints — GET /auth/me  PATCH /auth/me
#                      POST /auth/change-password   DELETE /auth/account
# ─────────────────────────────────────────────────────────────────────────────

class UpdateMeRequest(BaseModel):
    business_name: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


async def _get_tenant(tenant_id: str, db: AsyncSession) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get("/me")
async def get_me(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Return the current tenant's public profile."""
    tenant = await _get_tenant(tenant_id, db)
    return success_response({
        "id": str(tenant.id),
        "business_name": tenant.name,
        "email": tenant.owner_email,
        "plan": tenant.plan,
    })


@router.patch("/me")
async def update_me(
    body: UpdateMeRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Update mutable tenant fields (business name)."""
    tenant = await _get_tenant(tenant_id, db)
    if body.business_name is not None and body.business_name.strip():
        tenant.name = body.business_name.strip()
    await db.commit()
    await db.refresh(tenant)
    return success_response({
        "business_name": tenant.name,
        "email": tenant.owner_email,
    })


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Verify current password and set a new hashed password."""
    tenant = await _get_tenant(tenant_id, db)
    if not verify_password(body.current_password, tenant.owner_password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    tenant.owner_password_hash = hash_password(body.new_password)
    await db.commit()
    return success_response({"message": "Password updated successfully"})


@router.delete("/account", status_code=204)
async def delete_account(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete this tenant and all their data (cascaded by FK)."""
    tenant = await _get_tenant(tenant_id, db)
    await db.delete(tenant)
    await db.commit()

