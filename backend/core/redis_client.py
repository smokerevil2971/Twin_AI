"""
Async Redis client — used for rate limiting in the RAG bot
and onboarding state machine.
Thin wrapper around redis.asyncio.
"""
from redis.asyncio import Redis, from_url
from core.config import settings
import json

_redis: Redis | None = None

# Onboarding states stored as onboard:{phone}
ONBOARD_AWAITING_CONSENT  = "awaiting_consent"
ONBOARD_AWAITING_LANGUAGE = "awaiting_language"
ONBOARD_TTL = 86_400  # 24 hours — expire if client never responds


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    return _redis


async def increment_rate(key: str, window_seconds: int = 3600) -> int:
    """
    Atomically increment counter for `key`.
    Sets expiry of `window_seconds` on first increment.
    Returns the new counter value.
    """
    r = get_redis()
    current = await r.incr(key)
    if current == 1:
        await r.expire(key, window_seconds)
    return current


# ─── Onboarding state helpers ─────────────────────────────────────────────────

async def get_onboard_state(phone: str) -> str | None:
    """Return current onboarding state for phone, or None if not onboarding."""
    try:
        return await get_redis().get(f"onboard:{phone}")
    except Exception:
        return None


async def set_onboard_state(phone: str, state: str) -> None:
    """Set onboarding state for phone with 24-hour TTL."""
    try:
        await get_redis().set(f"onboard:{phone}", state, ex=ONBOARD_TTL)
    except Exception:
        pass
async def get_conversation_history(phone: str) -> list[dict]:
    """Return the last 3 turns of conversation history for this phone."""
    try:
        raw = await get_redis().get(f"chat_history:{phone}")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return []


async def add_conversation_history(phone: str, user_msg: str, bot_msg: str) -> None:
    """Append a turn to the conversation history, keeping only the last 3 turns."""
    try:
        r = get_redis()
        key = f"chat_history:{phone}"
        raw = await r.get(key)
        history = json.loads(raw) if raw else []
        
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": bot_msg})
        
        # Keep only the last 6 messages (3 turns = 3 user + 3 bot)
        if len(history) > 6:
            history = history[-6:]
            
        await r.set(key, json.dumps(history), ex=3600)  # 1 hour TTL
    except Exception:
        pass

async def clear_onboard_state(phone: str) -> None:
    """Delete onboarding state — client is fully onboarded."""
    try:
        await get_redis().delete(f"onboard:{phone}")
    except Exception:
        pass
