from fastapi import Request, HTTPException
from core.redis_client import increment_rate

from core.logging import logger

async def api_rate_limiter(request: Request):
    """
    Dependency to rate limit REST API endpoints based on client IP.
    Limits to 100 requests per minute.
    """
    client_ip = request.client.host if request.client else "unknown"
    key = f"api_rate:{client_ip}"
    try:
        count = await increment_rate(key, window_seconds=60)
        if count > 100:
            logger.warning(f"[RATE LIMIT] IP {client_ip} exceeded API rate limit")
            raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[RATE LIMIT] Redis check failed, bypassing: {e}")
