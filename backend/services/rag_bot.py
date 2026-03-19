"""
LangGraph RAG Bot — Phase 3.2 (dual-provider: NIM or Gemini)

Pipeline:
  sanitise → rate_limit → detect_language → injection_guard →
  embed_query → retrieve → rerank → context_check → generate_response →
  confidence_check → fallback / output → END

Provider switch: set LLM_PROVIDER=nim or LLM_PROVIDER=gemini in .env
Each node receives the full BotState dict and returns a partial update.
"""
import re
import logging
import uuid
import httpx
from datetime import datetime, timezone
from typing import Any, TypedDict, Optional

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

UNANSWERED_MSGS = {
    "en": "Great question! Our team will get back to you shortly. 🙏",
    "hi": "बहुत अच्छा सवाल! हमारी टीम जल्द ही आपसे संपर्क करेगी। 🙏",
}

RATE_LIMIT_MSGS = {
    "en": "You've sent too many messages this hour. Please try again later.",
    "hi": "आपने इस घंटे बहुत अधिक संदेश भेजे हैं। कृपया बाद में पुनः प्रयास करें।",
}


# ─── State ────────────────────────────────────────────────────────────────────

class BotState(TypedDict):
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
    _db: Any               # AsyncSession — passed through graph, not modified


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
    key = f"rate:{client_key}"
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
    """Embed the query using the configured provider (NIM or Gemini)."""
    try:
        if settings.is_nim:
            embedding = _embed_nim(state["clean_message"])
        else:
            embedding = _embed_gemini(state["clean_message"])
        return {"query_embedding": embedding}
    except Exception as e:
        logger.error(f"[BOT] embed failed: {e}")
        return {"query_embedding": [], "done": True, "fallback_reason": "no_context"}


def _embed_nim(text: str) -> list:
    """Single-query NIM embedding."""
    from openai import OpenAI
    client = OpenAI(base_url=settings.nim_base_url, api_key=settings.nim_embed_api_key)
    response = client.embeddings.create(
        model=settings.embedding_model,
        input=[text],
        encoding_format="float",
        extra_body={"input_type": "query", "truncate": "END"},
    )
    return response.data[0].embedding


def _embed_gemini(text: str) -> list:
    """Single-query Gemini embedding."""
    import google.generativeai as genai
    genai.configure(api_key=settings.gemini_api_key)
    result = genai.embed_content(
        model=settings.embedding_model,
        content=text,
        task_type="retrieval_query",
    )
    return result["embedding"]


def retrieve_node(state: BotState) -> dict:
    """Query ChromaDB for top-5 relevant chunks."""
    if not state.get("query_embedding"):
        return {"retrieved_chunks": [], "retrieved_distances": []}
    results = query_knowledge_base(
        query_embedding=state["query_embedding"],
        n_results=5,
    )
    return {
        "retrieved_chunks": results["documents"],
        "retrieved_distances": results["distances"],
    }


async def rerank_node(state: BotState) -> dict:
    """
    Rerank retrieved chunks using NIM rerank-qa-mistral-4b.
    Only active when LLM_PROVIDER=nim and chunks exist.
    Falls back gracefully if reranking fails — pipeline continues unchanged.
    """
    chunks = state.get("retrieved_chunks", [])
    distances = state.get("retrieved_distances", [])
    query = state.get("clean_message", "")

    if not chunks or not query or not settings.is_nim:
        return {}  # skip reranking for Gemini provider or empty results

    try:
        url = f"{settings.nim_base_url}/ranking"
        headers = {
            "Authorization": f"Bearer {settings.nim_rerank_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.rerank_model,
            "query": {"text": query},
            "passages": [{"text": chunk} for chunk in chunks],
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        rankings = data.get("rankings", [])
        if not rankings:
            return {}

        # Reorder chunks and distances by reranker score (highest first)
        sorted_rankings = sorted(rankings, key=lambda x: x.get("logit", 0), reverse=True)
        reranked_chunks = []
        reranked_distances = []
        for rank in sorted_rankings:
            idx = rank.get("index", 0)
            if idx < len(chunks):
                reranked_chunks.append(chunks[idx])
                reranked_distances.append(distances[idx] if idx < len(distances) else 1.0)

        logger.info(f"[BOT][NIM] reranked {len(reranked_chunks)} chunks")
        return {
            "retrieved_chunks": reranked_chunks,
            "retrieved_distances": reranked_distances,
        }

    except Exception as e:
        logger.warning(f"[BOT] rerank skipped (non-fatal): {e}")
        return {}  # pipeline continues with original retrieval order


def context_check_node(state: BotState) -> dict:
    """Check if retrieved context is useful (distance threshold 0.7)."""
    dists = state.get("retrieved_distances", [])
    chunks = state.get("retrieved_chunks", [])
    if not chunks or not dists or min(dists) > 0.7:
        logger.info(f"[BOT] context check → no useful context (dists={dists[:3]})")
        return {"done": True, "fallback_reason": "no_context"}
    return {}


def generate_node(state: BotState) -> dict:
    """Generate a grounded response using the configured provider (NIM or Gemini)."""
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
        if settings.is_nim:
            response_text = _generate_nim(prompt)
        else:
            response_text = _generate_gemini(prompt)
        logger.info(f"[BOT] generated response ({len(response_text)} chars)")
        return {"response": response_text}
    except Exception as e:
        logger.error(f"[BOT] generation failed: {e}")
        return {"fallback_reason": "no_context", "done": True}


def _generate_nim(prompt: str) -> str:
    """Generate via NVIDIA NIM (OpenAI-compatible chat completions)."""
    from openai import OpenAI
    client = OpenAI(base_url=settings.nim_base_url, api_key=settings.nim_llm_api_key)
    resp = client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=512,
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


def _generate_gemini(prompt: str) -> str:
    """Generate via Google Gemini."""
    import google.generativeai as genai
    genai.configure(api_key=settings.gemini_api_key)
    model_name = settings.llm_model.removeprefix("models/")
    model = genai.GenerativeModel(model_name)
    resp = model.generate_content(prompt)
    if hasattr(resp, "text") and resp.text:
        return resp.text.strip()
    elif resp.candidates:
        return resp.candidates[0].content.parts[0].text.strip()
    raise ValueError("Empty response from Gemini LLM")


def confidence_check_node(state: BotState) -> dict:
    """Compute confidence from minimum ChromaDB distance. Flag if < 0.75."""
    dists = state.get("retrieved_distances", [])
    if not dists:
        confidence = 0.0
    else:
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
    elif reason == "no_context":
        msg = UNANSWERED_MSGS.get(lang, UNANSWERED_MSGS["en"])
    else:
        msg = FALLBACK_MSGS.get(lang, FALLBACK_MSGS["en"])
    return {
        "response": msg,
        "confidence_score": 0.0,
        "flagged": True if reason == "no_context" else False,
    }


async def output_node(state: BotState) -> dict:
    """Send response via messaging adapter and log Conversation to Postgres."""
    response = state.get("response", FALLBACK_MSGS["en"])

    adapter = _get_adapter()
    try:
        await adapter.send_message(phone=state["phone"], message=response)
    except Exception as e:
        logger.error(f"[BOT] send_message failed: {e}")

    db = state.get("_db")
    if db:
        from models.models import Conversation
        conv = Conversation(
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
    g.add_node("rerank", rerank_node)          # NEW — NIM reranker (no-op for Gemini)
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
    g.add_edge("retrieve", "rerank")           # retrieve → rerank → context_check
    g.add_edge("rerank", "context_check")
    g.add_conditional_edges("context_check", should_fallback_after_context)
    g.add_conditional_edges("generate", should_fallback_after_generate)
    g.add_edge("confidence_check", "output")
    g.add_edge("fallback", "output")
    g.add_edge("output", END)

    return g.compile()


# Singleton — compiled once at import time
_rag_graph = build_rag_graph()


# ─── Messaging adapter helper ─────────────────────────────────────────────────

def _get_adapter():
    from services.gupshup_adapter import get_messaging_adapter
    return get_messaging_adapter()


# ─── Public entrypoint ────────────────────────────────────────────────────────

async def run_bot(
    phone: str,
    raw_message: str,
    client_id: str | None = None,
    db=None,
) -> dict:
    """
    Runs the full RAG pipeline and returns the final state.
    Call this from the inbound webhook handler.
    """
    initial: BotState = {
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
