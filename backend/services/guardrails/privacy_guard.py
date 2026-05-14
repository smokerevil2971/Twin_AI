"""
Layer 5 — Data Privacy Guardrails

Scans text for Indian PII patterns before it is stored in ChromaDB:
  - Aadhaar number  (12-digit groups)
  - PAN card        (AAAAA9999A)
  - Phone numbers   (Indian mobile: 6-9 followed by 9 digits)
  - Email addresses
  - Bank account numbers (9–18 digits)

Usage:
    from services.guardrails.privacy_guard import scan_and_redact

    clean_text = scan_and_redact(raw_text)
    # Then pass clean_text to ChromaDB
"""

import re

from core.logging import logger

# ── PII regex patterns ─────────────────────────────────────────────────────────
PII_PATTERNS: dict[str, re.Pattern] = {
    "aadhaar": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "pan":     re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "phone":   re.compile(r"\b[6-9]\d{9}\b"),
    "email":   re.compile(r"\b[\w._%+\-]+@[\w.\-]+\.[a-zA-Z]{2,}\b"),
    "bank_ac": re.compile(r"\b\d{9,18}\b"),
}

# What to replace detected PII with
_REDACTION_MAP = {
    "aadhaar": "[AADHAAR-REDACTED]",
    "pan":     "[PAN-REDACTED]",
    "phone":   "[PHONE-REDACTED]",
    "email":   "[EMAIL-REDACTED]",
    "bank_ac": "[ACCOUNT-REDACTED]",
}


def scan_and_redact(text: str) -> str:
    """
    Scan `text` for PII patterns and replace matches with redaction tokens.
    Returns the sanitised text.

    If no PII is found the original text is returned unchanged (zero overhead).
    """
    if not text:
        return text

    found_types: list[str] = []
    for pii_type, pattern in PII_PATTERNS.items():
        if pattern.search(text):
            found_types.append(pii_type)
            text = pattern.sub(_REDACTION_MAP[pii_type], text)

    if found_types:
        logger.warning(
            f"[GUARDRAIL][PRIVACY] PII redacted before KB ingestion: "
            f"{', '.join(found_types)}"
        )

    return text


def has_pii(text: str) -> bool:
    """
    Quick check — return True if any PII pattern matches.
    Useful for alerting without modifying the text.
    """
    return any(pattern.search(text) for pattern in PII_PATTERNS.values())


def detect_pii_types(text: str) -> list[str]:
    """Return list of PII type names found in text (for logging/reporting)."""
    return [t for t, p in PII_PATTERNS.items() if p.search(text)]
