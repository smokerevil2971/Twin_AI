"""
Async Redis client — used for rate limiting in the RAG bot
and onboarding state machine.
Thin wrapper around redis.asyncio.
"""
from redis.asyncio import Redis, from_url
from core.config import settings
import json

from core.logging import logger

_redis: Redis | None = None

# Onboarding states stored as onboard:{phone}
ONBOARD_AWAITING_CONSENT  = "awaiting_consent"
ONBOARD_AWAITING_LANGUAGE = "awaiting_language"
ONBOARD_AWAITING_NAME     = "awaiting_name"     # 2.6: capture client name after language

# ── Menu states stored as menu:{phone} ────────────────────────────────────────
MENU_STATE_MAIN     = "menu_main"       # client is at the main menu
MENU_STATE_PRODUCTS = "menu_products"   # client is in the products sub-menu
MENU_STATE_OFFERS   = "menu_offers"     # client is in the offers sub-menu


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
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")
        return None


async def set_onboard_state(phone: str, state: str) -> None:
    """Set onboarding state for phone with 24-hour TTL."""
    try:
        await get_redis().set(f"onboard:{phone}", state, ex=settings.onboard_state_ttl_seconds)
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")
async def get_conversation_history(phone: str) -> list[dict]:
    """Return the last 3 turns of conversation history for this phone."""
    try:
        raw = await get_redis().get(f"chat_history:{phone}")
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")
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
        
        # Keep only the last N messages (max_turns * 2: user + bot per turn)
        max_messages = settings.chat_history_max_turns * 2
        if len(history) > max_messages:
            history = history[-max_messages:]
            
        await r.set(key, json.dumps(history), ex=settings.chat_history_ttl_seconds)  # TTL from config
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")

async def clear_onboard_state(phone: str) -> None:
    """Delete onboarding state — client is fully onboarded."""
    try:
        await get_redis().delete(f"onboard:{phone}")
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")


# ─── Menu state helpers ───────────────────────────────────────────────────────

async def get_menu_state(phone: str) -> str | None:
    """Return current menu state for phone, or None if no active menu."""
    try:
        return await get_redis().get(f"menu:{phone}")
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")
        return None


async def set_menu_state(phone: str, state: str) -> None:
    """Set menu state with TTL from config."""
    try:
        from core.config import settings
        await get_redis().set(f"menu:{phone}", state, ex=settings.menu_state_ttl_seconds)
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")


async def clear_menu_state(phone: str) -> None:
    """Clear both menu state and page mapping for this phone."""
    try:
        r = get_redis()
        await r.delete(f"menu:{phone}")
        await r.delete(f"menu_page:{phone}")
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")


async def get_menu_page(phone: str) -> dict:
    """
    Return the button-ID → DB-item-ID mapping for the current menu page.
    Format: {"row_<uuid>": "<product_or_offer_uuid>", ...}
    """
    try:
        raw = await get_redis().get(f"menu_page:{phone}")
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")
    return {}


async def set_menu_page(phone: str, mapping: dict) -> None:
    """Store current page's button→item mapping with same TTL as menu state."""
    try:
        from core.config import settings
        await get_redis().set(
            f"menu_page:{phone}",
            json.dumps(mapping),
            ex=settings.menu_state_ttl_seconds,
        )
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")


# ─── Twilio ContentSid cache ──────────────────────────────────────────────────

async def get_cached_content_sid(cache_key: str) -> str | None:
    """
    Retrieve a cached Twilio ContentSid.
    Keys used:
      'twilio:main_menu_sid'    — quick-reply main menu
      'twilio:dynamic_list_sid' — list-picker for products/offers
    """
    try:
        return await get_redis().get(cache_key)
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")
        return None


async def cache_content_sid(cache_key: str, sid: str) -> None:
    """Cache a Twilio ContentSid permanently (no expiry — it never changes)."""
    try:
        await get_redis().set(cache_key, sid)
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")


# ─── Menu interaction counters (for analytics) ────────────────────────────────

async def increment_menu_counter(item_type: str, item_id: str) -> None:
    """
    Increment the tap counter for a product or offer.
    Keys: counter:product:{uuid} / counter:offer:{uuid}
    TTL: 90 days (rolling window for analytics)

    MED-08 fix: The old implementation had a race condition — three non-atomic
    Redis calls (INCR → EXPIRE xx=True → TTL check → EXPIRE) left a window
    where two concurrent workers could each try to set the TTL independently,
    or both skip it (leaving the key with no expiry = memory leak).

    Fix: Use SET NX EX to atomically initialise the key with TTL=90d on the
    very first tap. Subsequent taps just INCR (TTL is already set).
    """
    _TTL = 90 * 24 * 3600  # 90 days in seconds
    try:
        key = f"counter:{item_type}:{item_id}"
        r = get_redis()
        # Attempt to atomically create the key with value "1" and TTL.
        # NX means "only set if Not eXists" — if another worker beats us here,
        # SET NX returns False/None and we fall through to INCR which is safe.
        created = await r.set(key, 1, nx=True, ex=_TTL)
        if not created:
            # Key already existed — just increment (TTL stays intact from creation)
            await r.incr(key)
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")


async def get_top_menu_items(item_type: str, n: int = 3) -> list[tuple[str, int]]:
    """
    Return top N most-tapped product or offer IDs with their counts.
    Returns: [(item_id, count), ...] sorted by count desc.
    Scans keys matching counter:{item_type}:*
    """
    try:
        r = get_redis()
        pattern = f"counter:{item_type}:*"
        keys = [key async for key in r.scan_iter(pattern, count=200)]
        if not keys:
            return []
        counts = await r.mget(*keys)
        pairs = []
        for key, cnt in zip(keys, counts):
            if cnt:
                item_id = key.split(":", 2)[-1]  # strip "counter:product:"
                pairs.append((item_id, int(cnt)))
        pairs.sort(key=lambda x: x[1], reverse=True)
        return pairs[:n]
    except Exception as e:
        logger.warning(f"Redis operation failed: {e}")
        return []
