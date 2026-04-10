"""
Layer 3 — Output Guardrails

Checks applied to every LLM response before it is sent to the user:
  1. Response length cap  — truncate at 1,500 chars with a call-us CTA
  2. Competitor mention   — block responses that name competitor brands
  3. Content safety       — detect profanity / off-brand content
  4. PII in response      — warn if response accidentally contains PII

All checks are non-blocking stubs if not configured — they log a warning
and return the original response rather than silently dropping it.
"""

import re
import logging
from dataclasses import dataclass

from core.config import settings

logger = logging.getLogger(__name__)

# ── Configurable limits ────────────────────────────────────────────────────────
_MAX_RESPONSE_LEN = getattr(settings, "max_response_length", 1500)
_SUPPORT_PHONE    = settings.support_phone or settings.owner_phone

# ── Competitor brand names to suppress ────────────────────────────────────────
# Add your competitors here — case-insensitive regex match
COMPETITOR_PATTERNS: list[str] = [
    # Example: r"\bAcme\s*Corp\b", r"\bRival\s*Brand\b"
    # Left empty by default — populate from your business context
]

# ── Basic profanity / off-brand keywords (extend as needed) ───────────────────
PROFANITY_PATTERNS: list[str] = [
    r"\bfuck\b", r"\bshit\b", r"\bbitch\b", r"\basshole\b",
]

# ── PII patterns (same as privacy_guard — catch accidental leaks in output) ───
_PII_PATTERNS = {
    "aadhaar": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "pan":     re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "bank_ac": re.compile(r"\b\d{9,18}\b"),
}

_FALLBACK_RESPONSE = (
    "I'm sorry, I couldn't process that properly. "
    f"Please contact us directly for assistance"
    + (f" at {_SUPPORT_PHONE}." if _SUPPORT_PHONE else ".")
)

_TRUNCATION_SUFFIX = (
    f"\n\n_For more details, please call us"
    + (f" at {_SUPPORT_PHONE}." if _SUPPORT_PHONE else "._")
)


@dataclass
class OutputGuardrailResult:
    response: str            # Possibly sanitized / truncated response
    blocked: bool = False    # True if entire response was suppressed
    reason: str | None = None


def check_output(response: str, context: dict | None = None) -> OutputGuardrailResult:
    """
    Sanitize and validate LLM output before sending to the user.

    Args:
        response: Raw LLM-generated response text.
        context:  Optional dict with extra context (e.g. language, phone).

    Returns:
        OutputGuardrailResult with the (possibly modified) response.
    """
    if not response or not response.strip():
        return OutputGuardrailResult(
            response=_FALLBACK_RESPONSE, blocked=True, reason="empty_response"
        )

    # ── 1. Length cap ──────────────────────────────────────────────────────────
    if len(response) > _MAX_RESPONSE_LEN:
        logger.info(
            f"[GUARDRAIL][OUTPUT] Response truncated "
            f"({len(response)} → {_MAX_RESPONSE_LEN} chars)"
        )
        # Truncate at last word boundary before the cap
        truncated = response[:_MAX_RESPONSE_LEN].rsplit(" ", 1)[0]
        response = truncated + _TRUNCATION_SUFFIX

    # ── 2. Competitor mention ──────────────────────────────────────────────────
    for pattern in COMPETITOR_PATTERNS:
        if re.search(pattern, response, flags=re.IGNORECASE):
            logger.warning(
                f"[GUARDRAIL][OUTPUT] Competitor mention blocked: {pattern!r}"
            )
            return OutputGuardrailResult(
                response=_FALLBACK_RESPONSE,
                blocked=True,
                reason="competitor_mention",
            )

    # ── 3. Profanity / content safety ─────────────────────────────────────────
    for pattern in PROFANITY_PATTERNS:
        if re.search(pattern, response, flags=re.IGNORECASE):
            logger.warning(
                f"[GUARDRAIL][OUTPUT] Profanity detected — suppressing response"
            )
            return OutputGuardrailResult(
                response=_FALLBACK_RESPONSE,
                blocked=True,
                reason="profanity",
            )

    # ── 4. PII leak detection ────────────────────────────────────────────────
    for pii_type, pattern in _PII_PATTERNS.items():
        if pattern.search(response):
            logger.warning(
                f"[GUARDRAIL][OUTPUT] Possible PII ({pii_type}) detected in response — logging only"
            )
            # Log but don't block — human review via flagged conversations
            break

    return OutputGuardrailResult(response=response)
