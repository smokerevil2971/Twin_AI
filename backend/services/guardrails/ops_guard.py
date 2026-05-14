"""
Layer 4 — Operational Guardrails

Controls:
  4a. Daily global token budget   — cap total LLM usage per calendar day
  4b. Per-user daily token limit  — prevents a single user from burning the budget
  4c. Cost spike alert            — logs CRITICAL + notifies owner at 80% of limit

Redis key schema:
  guardrail:tokens:{YYYY-MM-DD}              → int, total tokens today   (TTL 25h)
  guardrail:user_tokens:{phone}:{YYYY-MM-DD} → int, user tokens today    (TTL 25h)

All checks degrade gracefully if Redis is unavailable — LLM calls are allowed
through rather than silently dropped, with a warning log.
"""

from datetime import datetime, timezone
from dataclasses import dataclass

from core.config import settings
from core.redis_client import get_redis

from core.logging import logger

# ── Configurable limits ─────────────────────────────────────────────────────
_DAILY_LIMIT        = getattr(settings, "daily_token_limit", 0)          # 0 = unlimited
_USER_DAILY_LIMIT   = getattr(settings, "per_user_daily_token_limit", 5000)
_ALERT_THRESHOLD    = getattr(settings, "guardrail_alert_threshold", 0.8)
_TTL_SECONDS        = 25 * 3600  # 25 hours — survives midnight rollover

_BUDGET_EXCEEDED_MSG = (
    "I'm a bit overwhelmed with requests right now! 😅 "
    "Please try again later, or contact us directly for urgent queries."
)
_USER_LIMIT_MSG = (
    "You've reached my daily conversation limit for today. 😊 "
    "Please come back tomorrow or contact us directly for urgent help."
)


@dataclass
class TokenBudgetResult:
    allowed: bool
    reason: str | None = None
    reply_override: str | None = None


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def check_token_budget(phone: str) -> TokenBudgetResult:
    """
    Check both the global daily budget and per-user daily limit.
    Call this BEFORE making an LLM API call.

    Returns TokenBudgetResult — if not allowed, reply_override is the ready-to-send reply.
    """
    today = _today_key()

    try:
        r = get_redis()

        # ── 4a. Global daily budget ────────────────────────────────────────────
        if _DAILY_LIMIT > 0:
            global_key = f"guardrail:tokens:{today}"
            used = int(await r.get(global_key) or 0)
            if used >= _DAILY_LIMIT:
                logger.critical(
                    f"[GUARDRAIL][OPS] DAILY TOKEN BUDGET EXCEEDED "
                    f"({used}/{_DAILY_LIMIT}) — blocking LLM call"
                )
                return TokenBudgetResult(
                    allowed=False,
                    reason="daily_budget_exceeded",
                    reply_override=_BUDGET_EXCEEDED_MSG,
                )

            # Cost spike alert at threshold %
            if used >= int(_DAILY_LIMIT * _ALERT_THRESHOLD):
                logger.critical(
                    f"[GUARDRAIL][OPS] TOKEN SPIKE ALERT: "
                    f"{used}/{_DAILY_LIMIT} tokens used "
                    f"({100 * used / _DAILY_LIMIT:.1f}% of daily budget)"
                )
                await _alert_owner_if_needed(used, _DAILY_LIMIT)

        # ── 4b. Per-user daily limit ───────────────────────────────────────────
        if _USER_DAILY_LIMIT > 0:
            user_key = f"guardrail:user_tokens:{phone}:{today}"
            user_used = int(await r.get(user_key) or 0)
            if user_used >= _USER_DAILY_LIMIT:
                logger.info(
                    f"[GUARDRAIL][OPS] Per-user token limit hit: "
                    f"{phone} used {user_used}/{_USER_DAILY_LIMIT} tokens today"
                )
                return TokenBudgetResult(
                    allowed=False,
                    reason="user_limit_exceeded",
                    reply_override=_USER_LIMIT_MSG,
                )

    except Exception as e:
        logger.warning(
            f"[GUARDRAIL][OPS] Token budget check failed (Redis down?) — allowing through: {e}"
        )

    return TokenBudgetResult(allowed=True)


async def record_tokens(phone: str, tokens_used: int) -> None:
    """
    Increment global and per-user token counters after a successful LLM call.
    Non-fatal — silently ignores Redis errors.

    Args:
        phone:       The WhatsApp phone number of the user.
        tokens_used: Total tokens consumed by the LLM (prompt + completion).
    """
    if tokens_used <= 0:
        return

    today = _today_key()
    try:
        r = get_redis()

        global_key = f"guardrail:tokens:{today}"
        user_key   = f"guardrail:user_tokens:{phone}:{today}"

        # Atomically increment both counters; set TTL on first write
        global_val = await r.incrby(global_key, tokens_used)
        if global_val == tokens_used:  # first write today
            await r.expire(global_key, _TTL_SECONDS)

        user_val = await r.incrby(user_key, tokens_used)
        if user_val == tokens_used:  # first write for this user today
            await r.expire(user_key, _TTL_SECONDS)

        logger.debug(
            f"[GUARDRAIL][OPS] Tokens recorded: {tokens_used} "
            f"(global={global_val}, user={user_val})"
        )
    except Exception as e:
        logger.warning(f"[GUARDRAIL][OPS] Failed to record tokens: {e}")


# ── Internal helper ───────────────────────────────────────────────────────────

_alert_sent_today: str | None = None   # module-level guard: one alert per day


async def _alert_owner_if_needed(used: int, limit: int) -> None:
    """Send a one-per-day WhatsApp alert to the owner about token usage."""
    global _alert_sent_today
    today = _today_key()
    if _alert_sent_today == today:
        return  # already alerted today
    _alert_sent_today = today

    try:
        if not settings.owner_phone:
            return
        from services.messaging_adapter import get_messaging_adapter
        adapter = get_messaging_adapter()
        pct = 100 * used / limit
        msg = (
            f"⚠️ *Twin AI Token Alert*\n\n"
            f"You've used *{used:,} / {limit:,}* tokens today ({pct:.0f}%).\n"
            f"The daily limit is *{limit:,}*.\n\n"
            f"_Increase DAILY_TOKEN_LIMIT in .env if needed._"
        )
        await adapter.send_message(phone=settings.owner_phone, message=msg)
        logger.info("[GUARDRAIL][OPS] Token spike alert sent to owner")
    except Exception as e:
        logger.warning(f"[GUARDRAIL][OPS] Failed to send owner alert: {e}")
