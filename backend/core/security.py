from datetime import datetime, timedelta, timezone
from typing import Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict[str, Any]:
    # HIGH-06 fix: Hardcode the allowed algorithm set instead of reading from
    # config. If ALGORITHM were ever misconfigured to "none" in .env, python-jose
    # would accept unsigned forged tokens. HS256 is the only valid value; HS384/HS512
    # are allowed as safe upgrades but RS*/ES* and "none" are explicitly excluded.
    _ALLOWED_ALGORITHMS = ["HS256", "HS384", "HS512"]
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=_ALLOWED_ALGORITHMS)
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict[str, Any]:
    """FastAPI dependency — decodes JWT and returns payload.
    Use this on any route that requires the owner to be logged in.
    """
    return decode_token(credentials.credentials)
