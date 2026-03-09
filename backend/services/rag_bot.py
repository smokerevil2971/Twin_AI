"""
LangGraph RAG Bot — Phase 3.2

Pipeline:
  sanitise → rate_limit → detect_language → injection_guard →
  embed_query → retrieve → context_check → generate_response →
  confidence_check → fallback / output → END

Each node receives the full BotState dict and returns a partial update.
"""
import re
import logging
import uuid
from datetime import datetime, timezone
from typing import TypedDict, Optional

import google.generativeai as genai
from langgraph.graph import StateGraph, END

from core.config import settings
from core.redis_client import increment_rate
from services.knowledge_service import embed_texts, query_knowledge_base
from services.gupshup_adapter import MockGupshupAdapter, RealGupshupAdapter

logger = logging.getLogger(__name__)

# ─── Rate limit constant ──────────────────────────────────────────────────────
MAX_MSGS_PER_HOUR = 20

# ─── Injection guard blocklist ────────────────────────────────────────────────
BLOCKED_TOPICS = [
    "politics", "news", "cricket", "weather", "code", "program",
    "hack", "joke", "poem", "recipe", "medicine", "doctor",
    "stock market", "investment", "crypto", "bitcoin",
]

# ─── Hindi Unicode range ──────────────────────────────────────────────────────
HINDI_RE = re.compile(r"[\u0900-\u097F]")

# ─── Fallback messages ────────────────────────────────────────────────────────
FALLBACK_MSGS = {
    "en": (
        "I'm sorry, I can only assist with questions about our products and services. "
        "For other queries, please contact us directly."
    ),
    "hi": (
        "माफ़ करें, मैं केवल हमारे उत्पादों और सेवाओं के बारे में सहायता कर सकता हूँ। "
        "अन्य प्रश्नों के लिए, कृपया हमसे सीधे संपर्क करें।"
    ),
}

RATE_LIMIT_MSGS = {
    "en": "You've sent too many messages this hour. Please try again later.",
    "hi": "आपने इस घंटे बहुत अधिक संदेश भेजे हैं। कृपया बाद में पुनः प्रयास करें।",
}


# ─── State ────────────────────────────────────────────────────────────────────

class BotState(TypedDict):
    tenant_id: str
    client_id: Optional[str]
    phone: str
    raw_message: str
    clean_message: str
    language: str
    query_embedding: list
    retrieved_chunks: list
    retrieved_distances: list
    response: str
    confidence_score: float
    flagged: bool
    fallback_reason: str   # "" | "rate_limit" | "injection" | "no_context"
    done: bool


# ─── Nodes ────────────────────────────────────────────────────────────────────

def sanitise_node(state: BotState) -> dict:
    """Strip HTML, script tags, collapse whitespace, truncate to 1000 chars."""
    text = state["raw_message"]
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^\w\s,.?!।\-'\"@\u0900-\u097F]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:1000]
    logger.info(f"[BOT] sanitised message: {text[:80]}")
    return {"clean_message": text, "language": "en"}


async def rate_limit_node(state: BotState) -> dict:
    """Allow max 20 msgs per client per hour via Redis counter."""
    client_key = state.get("client_id") or state["phone"]
    key = f"rate:{state['tenant_id']}:{client_key}"
    count = await increment_rate(key, window_seconds=3600)
    logger.info(f"[BOT] rate check → {key} = {count}")
    if count > MAX_MSGS_PER_HOUR:
        return {"done": True, "fallback_reason": "rate_limit"}
    return {"done": False}


def detect_language_node(state: BotState) -> dict:
    """Detect Hindi or English based on Unicode character count."""
    text = state["clean_message"]
    if not text:
        return {"language": "en"}
    hindi_count = len(HINDI_RE.findall(text))
    ratio = hindi_count / max(len(text), 1)
    lang = "hi" if ratio > 0.15 else "en"
    logger.info(f"[BOT] language = {lang} (Hindi ratio: {ratio:.2f})")
    return {"language": lang}


def injection_guard_node(state: BotState) -> dict:
    """Reject out-of-scope queries using keyword blocklist."""
    msg = state["clean_message"].lower()
    for topic in BLOCKED_TOPICS:
        if topic in msg:
            logger.info(f"[BOT] injection guard → blocked topic: {topic}")
            return {"done": True, "fallback_reason": "injection"}
    return {}


def embed_node(state: BotState) -> dict:
    """Embed the query using Gemini."""
    try:
        genai.configure(api_key=settings.gemini_api_key)
        result = genai.embed_content(
            model=settings.embedding_model,
            content=state["clean_message"],
            task_type="retrieval_query",
        )
        return {"query_embedding": result["embedding"]}
    except Exception as e:
        logger.error(f"[BOT] embed failed: {e}")
        return {"query_embedding": [], "done": True, "fallback_reason": "no_context"}


def retrieve_node(state: BotState) -> dict:
    """Query ChromaDB for top-5 relevant chunks."""
    if not state.get("query_embedding"):
        return {"retrieved_chunks": [], "retrieved_distances": []}
    results = query_knowledge_base(
        tenant_id=uuid.UUID(state["tenant_id"]),
        query_embedding=state["query_embedding"],
        n_results=5,
    )
    return {
        "retrieved_chunks": results["documents"],
        "retrieved_distances": results["distances"],
    }


def context_check_node(state: BotState) -> dict:
    """Check if retrieved context is useful (distance threshold 0.7)."""
    dists = state.get("retrieved_distances", [])
    chunks = state.get("retrieved_chunks", [])
    if not chunks or not dists or min(dists) > 0.7:
        logger.info(f"[BOT] context check → no useful context (dists={dists[:3]})")
        return {"done": True, "fallback_reason": "no_context"}
    return {}


def generate_node(state: BotState) -> dict:
    """Generate a grounded response from Gemini using retrieved context."""
    lang_label = "Hindi" if state["language"] == "hi" else "English"
    context = "\n\n".join(state["retrieved_chunks"])
    prompt = (
        f"You are a friendly customer service assistant.\n"
        f"Answer ONLY based on the context provided below. "
        f"Do NOT make up information not in the context.\n"
        f"Respond in {lang_label}. Be concise (2-4 sentences).\n\n"
        f"Context:\n{context}\n\n"
        f"Customer question: {state['clean_message']}\n\n"
        f"Answer:"
    )
    try:
        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(settings.llm_model)
        resp = model.generate_content(prompt)
        # Safely extract text from response
        if hasattr(resp, "text") and resp.text:
            response_text = resp.text.strip()
        elif resp.candidates:
            response_text = resp.candidates[0].content.parts[0].text.strip()
        else:
            raise ValueError("Empty response from Gemini LLM")
        logger.info(f"[BOT] generated response ({len(response_text)} chars)")
        return {"response": response_text}
    except Exception as e:
        logger.error(f"[BOT] generation failed: {e}")
        return {"fallback_reason": "no_context", "done": True}


def confidence_check_node(state: BotState) -> dict:
    """Compute confidence from minimum ChromaDB distance. Flag if < 0.75."""
    dists = state.get("retrieved_distances", [])
    if not dists:
        confidence = 0.0
    else:
        # ChromaDB cosine distance: 0 = identical, 2 = opposite
        # Normalize to 0-1: score = 1 - (min_dist / 2)
        confidence = round(max(0.0, 1.0 - (min(dists) / 2.0)), 4)
    flagged = confidence < 0.75
    logger.info(f"[BOT] confidence={confidence}, flagged={flagged}")
    return {"confidence_score": confidence, "flagged": flagged}


def fallback_node(state: BotState) -> dict:
    """Compose a polite fallback message in the detected language."""
    lang = state.get("language", "en")
    reason = state.get("fallback_reason", "")
    if reason == "rate_limit":
        msg = RATE_LIMIT_MSGS.get(lang, RATE_LIMIT_MSGS["en"])
    else:
        msg = FALLBACK_MSGS.get(lang, FALLBACK_MSGS["en"])
    return {
        "response": msg,
        "confidence_score": 0.0,
        "flagged": False,
    }


async def output_node(state: BotState) -> dict:
    """Send response via Gupshup and log Conversation to Postgres."""
    response = state.get("response", FALLBACK_MSGS["en"])

    # Send via Gupshup adapter
    adapter = _get_adapter()
    try:
        await adapter.send_message(phone=state["phone"], message=response)
    except Exception as e:
        logger.error(f"[BOT] send_message failed: {e}")

    # Log to Postgres (skip if no db session injected)
    db = state.get("_db")
    if db:
        from models.models import Conversation
        conv = Conversation(
            tenant_id=uuid.UUID(state["tenant_id"]),
            client_id=uuid.UUID(state["client_id"]) if state.get("client_id") else None,
            direction="inbound",
            message=state["raw_message"],
            response=response,
            language=state.get("language", "en"),
            confidence_score=state.get("confidence_score"),
            flagged=state.get("flagged", False),
        )
        db.add(conv)
        await db.commit()
        logger.info(f"[BOT] conversation logged (flagged={conv.flagged})")

    return {}


# ─── Conditional edge helpers ─────────────────────────────────────────────────

def should_fallback_after_rate(state: BotState) -> str:
    return "fallback" if state.get("done") else "detect_language"


def should_fallback_after_injection(state: BotState) -> str:
    return "fallback" if state.get("done") else "embed"


def should_fallback_after_context(state: BotState) -> str:
    return "fallback" if state.get("done") else "generate"


def should_fallback_after_embed(state: BotState) -> str:
    return "fallback" if state.get("done") else "retrieve"


def should_fallback_after_generate(state: BotState) -> str:
    return "fallback" if state.get("done") else "confidence_check"


# ─── Build graph ──────────────────────────────────────────────────────────────

def build_rag_graph():
    g = StateGraph(BotState)

    g.add_node("sanitise", sanitise_node)
    g.add_node("rate_limit", rate_limit_node)
    g.add_node("detect_language", detect_language_node)
    g.add_node("injection_guard", injection_guard_node)
    g.add_node("embed", embed_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("context_check", context_check_node)
    g.add_node("generate", generate_node)
    g.add_node("confidence_check", confidence_check_node)
    g.add_node("fallback", fallback_node)
    g.add_node("output", output_node)

    g.set_entry_point("sanitise")
    g.add_edge("sanitise", "rate_limit")
    g.add_conditional_edges("rate_limit", should_fallback_after_rate)
    g.add_edge("detect_language", "injection_guard")
    g.add_conditional_edges("injection_guard", should_fallback_after_injection)
    g.add_conditional_edges("embed", should_fallback_after_embed)
    g.add_edge("retrieve", "context_check")
    g.add_conditional_edges("context_check", should_fallback_after_context)
    g.add_conditional_edges("generate", should_fallback_after_generate)  # fixed
    g.add_edge("confidence_check", "output")
    g.add_edge("fallback", "output")
    g.add_edge("output", END)

    return g.compile()


# Singleton — compiled once at import time
_rag_graph = build_rag_graph()


# ─── Gupshup adapter helper ───────────────────────────────────────────────────

def _get_adapter():
    if settings.gupshup_mode == "real":
        return RealGupshupAdapter(
            api_key=settings.gupshup_api_key,
            app_name=settings.gupshup_app_name,
            sender=settings.gupshup_sender_number,
            webhook_secret=settings.gupshup_webhook_secret,
        )
    return MockGupshupAdapter()


# ─── Public entrypoint ────────────────────────────────────────────────────────

async def run_bot(
    tenant_id: str,
    phone: str,
    raw_message: str,
    client_id: str | None = None,
    db=None,
) -> dict:
    """
    Runs the full RAG pipeline and returns the final state.
    Call this from the inbound webhook handler (Phase 3.3).
    """
    initial: BotState = {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "phone": phone,
        "raw_message": raw_message,
        "clean_message": "",
        "language": "en",
        "query_embedding": [],
        "retrieved_chunks": [],
        "retrieved_distances": [],
        "response": "",
        "confidence_score": 0.0,
        "flagged": False,
        "fallback_reason": "",
        "done": False,
        "_db": db,
    }
    final_state = await _rag_graph.ainvoke(initial)
    return final_state
