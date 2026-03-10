"""
Auth routes — Two-Bot version
  POST /auth/register  — one-time owner account creation
  POST /auth/login     — returns JWT token
  GET  /auth/me        — returns owner profile
  PATCH /auth/me       — update business name
  POST /auth/change-password — update password
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from core.database import get_db
from core.security import verify_password, create_access_token, hash_password, get_current_user
from core.responses import success_response
from models.models import Owner

router = APIRouter(prefix="/auth", tags=["auth"])


# ─── Request schemas ──────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    business_name: str
    email: str
    password: str


class UpdateMeRequest(BaseModel):
    business_name: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _get_owner(db: AsyncSession) -> Owner:
    """Get the single owner record. Raises 404 if not set up yet."""
    result = await db.execute(select(Owner))
    owner = result.scalar_one_or_none()
    if not owner:
        raise HTTPException(status_code=404, detail="Owner account not found")
    return owner


# ─── POST /auth/register ──────────────────────────────────────────────────────

@router.post("/register", status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    One-time owner registration. Only one owner account is allowed.
    Returns JWT token on success.
    """
    existing = await db.execute(select(Owner))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Owner account already exists. Only one owner is allowed."
        )

    owner = Owner(
        business_name=body.business_name,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(owner)
    await db.commit()
    await db.refresh(owner)

    token = create_access_token({
        "sub": str(owner.id),
        "email": owner.email,
    })

    return success_response({
        "access_token": token,
        "token_type": "bearer",
        "business_name": owner.business_name,
    }, status_code=201)


# ─── POST /auth/login ─────────────────────────────────────────────────────────

@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    owner = await _get_owner(db)

    if not verify_password(body.password, owner.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token({
        "sub": str(owner.id),
        "email": owner.email,
    })

    return success_response({
        "access_token": token,
        "token_type": "bearer",
        "business_name": owner.business_name,
    })


# ─── GET /auth/me ─────────────────────────────────────────────────────────────

@router.get("/me")
async def get_me(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    owner = await _get_owner(db)
    return success_response({
        "id": str(owner.id),
        "business_name": owner.business_name,
        "email": owner.email,
    })


# ─── PATCH /auth/me ───────────────────────────────────────────────────────────

@router.patch("/me")
async def update_me(
    body: UpdateMeRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    owner = await _get_owner(db)
    if body.business_name and body.business_name.strip():
        owner.business_name = body.business_name.strip()
    await db.commit()
    await db.refresh(owner)
    return success_response({
        "business_name": owner.business_name,
        "email": owner.email,
    })


# ─── POST /auth/change-password ───────────────────────────────────────────────

@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    owner = await _get_owner(db)
    if not verify_password(body.current_password, owner.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    owner.password_hash = hash_password(body.new_password)
    await db.commit()
    return success_response({"message": "Password updated successfully"})
