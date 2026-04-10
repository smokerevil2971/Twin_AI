"""
Guardrails package — 5-layer safety system for Twin AI WhatsApp bot.

Layers:
    1. input_guard   — length cap, rate limiting, blocklist, spam detection
    2. (rag_bot)     — prompt hardening + injection detection (in rag_bot.py)
    3. output_guard  — response safety filter, length cap, competitor check
    4. ops_guard     — daily token budget, per-user fairness, cost spike alert
    5. privacy_guard — PII detection and redaction before ChromaDB ingestion
"""
from .input_guard import check_input, GuardrailResult
from .output_guard import check_output
from .ops_guard import check_token_budget, record_tokens
from .privacy_guard import scan_and_redact

__all__ = [
    "GuardrailResult",
    "check_input",
    "check_output",
    "check_token_budget",
    "record_tokens",
    "scan_and_redact",
]
