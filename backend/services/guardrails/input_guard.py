"""
Layer 1 — Input Guardrails

Checks (in order):
  1. Blocklist  — instantly bounce explicitly blocked phone numbers
  2. Length cap — reject messages > MAX_MESSAGE_LENGTH chars
  3. Spam       — same message sent twice within 60 seconds
  4. Rate limit — sliding window: max N messages per user per hour

All checks degrade gracefully if Redis is unavailable — the message is
allowed through rather than silently dropped.

Redis key schema:
  guardrail:blocked          → Redis SET of phone numbers (no TTL)
  guardrail:rate:{phone}     → simple integer counter (TTL = 1 hour)
  guardrail:spam:{phone}:{h} → integer counter (TTL = 60 s)
"""

import hashlib
import logging
from dataclasses import dataclass

from core.config import settings
from core.redis_client import get_redis

logger = logging.getLogger(__name__)

# ── Configurable limits (read from settings, with sane defaults) ──────────────
_MAX_LEN    = getattr(settings, "max_message_length", 1000)
_MAX_PER_HR = getattr(settings, "max_messages_per_hour", settings.bot_rate_limit_per_hour)
_SPAM_TTL   = 10   # seconds — only block true rapid-fire duplicates (not repeated menu taps)

# Menu navigation words that are always legitimate to repeat — never flag as spam
_MENU_KEYWORDS = {
    "offers", "products", "menu", "hi", "hello", "hey", "help",
    "catalogue", "catalog", "start", "stop", "order", "orders",
    "my orders", "back", "main menu", "send menu",
}

# Polite canned responses so guard replies feel human
_REPLY_TOO_LONG = (
    "Your message is a bit long for me to process! 😅 "
    "Could you keep it under 1,000 characters? "
    "I'm here to help with product questions."
)
_REPLY_RATE_LIMITED = (
    "You're sending messages very quickly! 😊 "
    "Please wait a moment and try again — I want to give you the best answer."
)
_REPLY_SPAM = (
    "It looks like you just sent that message. "
    "I'm still processing it — please wait a few seconds! 😊"
)
_REPLY_BLOCKED = (
    "Sorry, we're unable to process your message at this time. "
    "Please contact us directly for assistance."
)


@dataclass
class GuardrailResult:
    allowed: bool
    reason: str | None = None
    reply_override: str | None = None


async def check_input(phone: str, message: str) -> GuardrailResult:
    """
    Run all input guardrail checks.
    Returns a GuardrailResult — if not allowed, reply_override contains the
    ready-to-send WhatsApp message the webhook should send back to the user.
    """
    # ── 1. Blocklist ──────────────────────────────────────────────────────────
    try:
        r = get_redis()
        is_blocked = await r.sismember("guardrail:blocked", phone)
        if is_blocked:
            logger.warning(f"[GUARDRAIL][INPUT] Blocked number: {phone}")
            return GuardrailResult(
                allowed=False, reason="blocklisted", reply_override=_REPLY_BLOCKED
            )
    except Exception as e:
        logger.warning(f"[GUARDRAIL][INPUT] Blocklist check failed (Redis down?): {e}")

    # ── 2. Message length cap ─────────────────────────────────────────────────
    if len(message) > _MAX_LEN:
        logger.info(
            f"[GUARDRAIL][INPUT] Message too long ({len(message)} chars) from {phone}"
        )
        return GuardrailResult(
            allowed=False, reason="too_long", reply_override=_REPLY_TOO_LONG
        )

    # ── 3. Spam detection — identical message within _SPAM_TTL seconds ───────────
    # Menu navigation keywords are intentional repeated taps — never flag as spam.
    try:
        r = get_redis()
        # Skip spam check entirely for common menu navigation words
        if message.strip().lower() not in _MENU_KEYWORDS:
            msg_hash = hashlib.md5(message.encode()).hexdigest()[:12]
            spam_key = f"guardrail:spam:{phone}:{msg_hash}"
            count = await r.incr(spam_key)
            if count == 1:
                await r.expire(spam_key, _SPAM_TTL)
            if count > 1:
                logger.info(f"[GUARDRAIL][INPUT] Spam repeat from {phone}: {message[:40]!r}")
                return GuardrailResult(
                    allowed=False, reason="spam", reply_override=_REPLY_SPAM
                )
    except Exception as e:
        logger.warning(f"[GUARDRAIL][INPUT] Spam check failed (Redis down?): {e}")


    # ── 4. Sliding-window rate limit ──────────────────────────────────────────
    try:
        r = get_redis()
        rate_key = f"guardrail:rate:{phone}"
        count = await r.incr(rate_key)
        if count == 1:
            await r.expire(rate_key, 3600)  # 1-hour sliding window
        if count > _MAX_PER_HR:
            logger.info(
                f"[GUARDRAIL][INPUT] Rate limit hit: {phone} sent {count} msgs/hr"
            )
            return GuardrailResult(
                allowed=False, reason="rate_limited", reply_override=_REPLY_RATE_LIMITED
            )
    except Exception as e:
        logger.warning(f"[GUARDRAIL][INPUT] Rate limit check failed (Redis down?): {e}")

    return GuardrailResult(allowed=True)


# ── Admin helpers (called from owner commands) ────────────────────────────────

async def block_number(phone: str) -> None:
    """Add a phone number to the guardrail blocklist."""
    try:
        await get_redis().sadd("guardrail:blocked", phone)
        logger.info(f"[GUARDRAIL] Blocked number: {phone}")
    except Exception as e:
        logger.error(f"[GUARDRAIL] Failed to block {phone}: {e}")


async def unblock_number(phone: str) -> None:
    """Remove a phone number from the guardrail blocklist."""
    try:
        await get_redis().srem("guardrail:blocked", phone)
        logger.info(f"[GUARDRAIL] Unblocked number: {phone}")
    except Exception as e:
        logger.error(f"[GUARDRAIL] Failed to unblock {phone}: {e}")


async def list_blocked() -> list[str]:
    """Return all currently blocked phone numbers."""
    try:
        members = await get_redis().smembers("guardrail:blocked")
        return list(members)
    except Exception:
        return []
