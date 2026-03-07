from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from core.database import get_db
from core.security import verify_password, create_access_token, hash_password
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
