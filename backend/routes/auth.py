"""
Auth routes — Two-Bot version
  POST /auth/register  — one-time owner account creation
  POST /auth/login     — returns JWT token
  GET  /auth/me        — returns owner profile
  PATCH /auth/me       — update business name
  POST /auth/change-password — update password
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from core.database import get_db
from core.security import verify_password, create_access_token, hash_password, get_current_user
from core.responses import success_response
from core.config import settings
from models.models import Owner

router = APIRouter(prefix="/auth", tags=["auth"])


from models.schemas import LoginRequest, RegisterRequest, UpdateMeRequest, ChangePasswordRequest


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
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    TC-003 fix: Returns the same generic 401 whether the owner account
    doesn't exist OR the password is wrong — prevents email enumeration.

    HIGH-01 fix: Redis-backed rate limiting — max 5 failed attempts per
    client IP per 15-minute window. Counter is cleared on successful login
    so legitimate owners are never locked out permanently.
    """
    # ── Rate limiting (HIGH-01) ─────────────────────────────────────────────────
    from core.redis_client import get_redis
    _MAX_ATTEMPTS = 5          # failed attempts before lockout
    _WINDOW_SECONDS = 15 * 60  # 15-minute sliding window
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"login_attempts:{client_ip}"
    try:
        r = get_redis()
        attempts = await r.get(rate_key)
        if attempts and int(attempts) >= _MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many login attempts. Try again in {_WINDOW_SECONDS // 60} minutes.",
            )
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Redis rate limit check failed: {e}")
        pass  # Degrade gracefully if Redis is unavailable — never hard-block login

    # ── Credential check ──────────────────────────────────────────────────────
    # LOW-07 fix: The email from request body was never checked against the
    # database — any email string with the correct password would log in.
    # While there's only one owner row, this is semantically wrong and would
    # silently succeed for `{"email": "anything@example.com", "password": "correct"}`.
    result = await db.execute(select(Owner).where(Owner.email == body.email))
    owner = result.scalar_one_or_none()

    if not owner or not verify_password(body.password, owner.password_hash):
        # Increment failure counter; set TTL only on first failure
        try:
            r = get_redis()
            new_count = await r.incr(rate_key)
            if new_count == 1:
                await r.expire(rate_key, _WINDOW_SECONDS)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Success — clear failure counter so owner is never permanently locked out
    try:
        r = get_redis()
        await r.delete(rate_key)
    except Exception:
        pass

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
    if len(body.new_password) < settings.min_password_length:
        raise HTTPException(status_code=400, detail=f"New password must be at least {settings.min_password_length} characters")
    owner.password_hash = hash_password(body.new_password)
    await db.commit()
    return success_response({"message": "Password updated successfully"})
