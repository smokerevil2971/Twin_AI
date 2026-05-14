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
import asyncio
import uuid
import httpx
from datetime import datetime, timezone
from typing import Any, TypedDict, Optional

from langgraph.graph import StateGraph, START, END

from core.config import settings
from core.redis_client import increment_rate
from services.knowledge_service import embed_texts, query_knowledge_base
from services.messaging_adapter import get_messaging_adapter

from core.logging import logger


# ─── Injection guard blocklist ────────────────────────────────────────────────
# TC-023 fix: Removed broad single-word blocks ("code", "hack", "program") that
# were triggering on legitimate solar queries like "error code E07" or
# "how to program my inverter". Replaced with precise multi-word phrases.
BLOCKED_TOPICS = [
    "politics",
    "news",
    "cricket",
    "weather",
    "write code",
    "write a program",
    "write a script",
    "hacking",
    "how to hack",
    "jailbreak",
    "tell me a joke",
    "joke",
    "poem",
    "write a poem",
    "recipe",
    "medicine",
    "doctor",
    "diagnosis",
    "stock market",
    "investment advice",
    "crypto",
    "bitcoin",
]

# ─── Prompt injection detection patterns (Layer 2b) ───────────────────────────
# Compiled once at module load for performance.

_INJECTION_PATTERNS_RAW = [
    r"ignore (previous|above|all) instructions",
    r"you are now",
    r"pretend (you are|to be)",
    r"act as (a |an )?(?!customer)",
    r"forget (everything|your instructions|all)",
    r"system prompt",
    r"new persona",
    r"disregard (your|all|previous)",
    r"developer mode",
    r"DAN mode",
    r"do anything now",
    r"bypass (your |all )?(restrictions|guidelines|filters)",
    r"reveal (your|the) (system|instructions|prompt)",
    r"override (your|all) (instructions|programming)",
]

INJECTION_RE = re.compile(
    "|".join(_INJECTION_PATTERNS_RAW), flags=re.IGNORECASE
)

# ─── Hindi Unicode range ──────────────────────────────────────────────────────
HINDI_RE = re.compile(r"[\u0900-\u097F]")

# ─── Fallback messages ────────────────────────────────────────────────────────
# Support phone is loaded from config so it never needs to be hardcoded.
_SUPPORT_PHONE = settings.support_phone or settings.owner_phone
_CALL_CTA_EN = f" → Call {_SUPPORT_PHONE}" if _SUPPORT_PHONE else ""
_CALL_CTA_HI = f" → कॉल करें {_SUPPORT_PHONE}" if _SUPPORT_PHONE else ""

FALLBACK_MSGS = {
    "en": (
        "I don't have that information right now. 🙏\n\n"
        "Would you like to:\n"
        f"1️⃣ Speak to our team directly{_CALL_CTA_EN}\n"
        "2️⃣ Receive our product catalogue → Reply CATALOGUE\n"
        "3️⃣ Ask something else about our products"
    ),
    "hi": (
        "मेरे पास अभी वह जानकारी नहीं है। 🙏\n\n"
        "क्या आप चाहेंगे:\n"
        f"1️⃣ हमारी टीम से सीधे बात करना{_CALL_CTA_HI}\n"
        "2️⃣ हमारा उत्पाद कैटलॉग प्राप्त करना → रिप्लाई करें CATALOGUE\n"
        "3️⃣ हमारे उत्पादों के बारे में कुछ और पूछना"
    ),
}

UNANSWERED_MSGS = {
    "en": (
        "I don't have that information right now. 🙏\n\nWould you like to:\n"
        f"1️⃣ Speak to our team directly{_CALL_CTA_EN}\n"
        "2️⃣ Receive our product catalogue → Reply CATALOGUE"
    ),
    "hi": (
        "मेरे पास अभी वह जानकारी नहीं है। 🙏\n\nक्या आप चाहेंगे:\n"
        f"1️⃣ हमारी टीम से सीधे बात करना{_CALL_CTA_HI}\n"
        "2️⃣ हमारा उत्पाद कैटलॉग प्राप्त करना → रिप्लाई करें CATALOGUE"
    ),
}

RATE_LIMIT_MSGS = {
    "en": (
        f"You're on a roll! 😄 We limit messages to keep response quality high.\n"
        f"Please try again in a little while{', or call us directly at ' + _SUPPORT_PHONE if _SUPPORT_PHONE else '.'}"
    ),
    "hi": (
        f"आप बहुत तेज हैं! 😄 हमने प्रतिक्रिया की गुणवत्ता बनाए रखने के लिए संदेशों को सीमित किया है।\n"
        f"कृपया थोड़ी देर में पुनः प्रयास करें{', या सीधे हमें ' + _SUPPORT_PHONE + ' पर कॉल करें।' if _SUPPORT_PHONE else '।'}"
    ),
}


# ─── State ────────────────────────────────────────────────────────────────────


class BotState(TypedDict):
    client_id: Optional[str]
    phone: str
    raw_message: str
    clean_message: str
    language: str
    chat_history: list
    long_term_memory: list  # NEW — relevant past exchanges from DB
    query_embedding: list
    retrieved_chunks: list
    retrieved_distances: list
    response: str
    confidence_score: float
    flagged: bool
    fallback_reason: str  # "" | "rate_limit" | "injection" | "no_context"
    done: bool
    enquiry_intent: bool
    is_menu_request: bool  # NEW — bypass confidence flags
    # LOW-06 fix: context_check_node sets this key but it wasn't declared in
    # BotState. LangGraph silently ignores undeclared keys in some versions,
    # and static type checkers would report TypedDict assignment errors.
    has_image_context: bool
    _db: Any  # AsyncSession — passed through graph, not modified


# ─── Nodes ────────────────────────────────────────────────────────────────────


def sanitise_node(state: BotState) -> dict:
    """Strip HTML, script tags, collapse whitespace, truncate to 1000 chars."""
    text = state["raw_message"]
    text = re.sub(
        r"<script[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^\w\s,.?!।\-'\"@\u0900-\u097F]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:settings.bot_message_max_length]
    logger.info(f"[BOT] sanitised message: {text[:80]}")
    return {"clean_message": text, "language": "en"}


async def rate_limit_node(state: BotState) -> dict:
    """Allow max 20 msgs per client per hour via Redis counter.

    TC-024 fix: If Redis is unavailable, degrade gracefully — skip rate limiting
    rather than crashing the entire webhook with a ConnectionError.
    A warning is logged so operators can detect the outage.
    """
    client_key = state.get("client_id") or state["phone"]
    key = f"rate:{client_key}"
    try:
        count = await increment_rate(key, window_seconds=3600)
        logger.info(f"[BOT] rate check → {key} = {count}")
        if count > settings.bot_rate_limit_per_hour:
            return {"done": True, "fallback_reason": "rate_limit"}
    except Exception as e:
        logger.warning(
            f"[BOT] Redis unavailable — rate limiting skipped for {key}: {e}"
        )
    return {"done": False}


def order_intent_node(state: BotState) -> dict:
    """Detect explicit 'ORDER' command to trigger owner alert."""
    msg = state["clean_message"].strip().upper()
    if msg == "ORDER":
        logger.info("[BOT] order intent detected!")
        return {"done": True, "fallback_reason": "order_intent"}
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
    """Reject out-of-scope queries using keyword blocklist AND injection regex."""
    msg = state["clean_message"].lower()

    # 2a: topic blocklist
    for topic in BLOCKED_TOPICS:
        if topic in msg:
            logger.info(f"[BOT] injection guard → blocked topic: {topic}")
            return {"done": True, "fallback_reason": "injection"}

    # 2b: prompt injection detection
    if INJECTION_RE.search(msg):
        logger.warning(f"[BOT] injection guard → prompt attack detected: {msg[:80]!r}")
        return {"done": True, "fallback_reason": "injection"}

    return {}


async def embed_node(state: BotState) -> dict:
    """Embed the query using the configured provider (NIM or Gemini).

    NOTE: Both _embed_nim and _embed_gemini are synchronous (httpx.Client /
    google-generativeai SDK). We run them in the default thread-pool executor
    so they do NOT block the async event loop.
    """
    provider = "nim" if settings.is_nim else "gemini"
    logger.info(f"[BOT][EMBED] Starting embedding via {provider} for: {state['clean_message'][:60]}")
    try:
        if settings.is_nim:
            # P1.5 fix: asyncio.get_event_loop() deprecated in Python 3.10+, removed in 3.12.
            # asyncio.to_thread() is the correct Python 3.9+ replacement.
            embedding = await asyncio.to_thread(_embed_nim, state["clean_message"])
        else:
            embedding = await asyncio.to_thread(_embed_gemini, state["clean_message"])
        logger.info(f"[BOT][EMBED] OK — vector dim={len(embedding)}")
        return {"query_embedding": embedding}
    except Exception as e:
        logger.error(f"[BOT][EMBED] FAILED via {provider}: {type(e).__name__}: {e}", exc_info=True)
        return {"query_embedding": [], "done": True, "fallback_reason": "no_context"}


async def memory_retrieve_node(state: BotState) -> dict:
    """Search past conversations semantically using the current query embedding.

    Uses the existing `conversations` table with the new `embedding` column.
    Falls back gracefully (empty list) if DB is unavailable or no history exists.
    This node runs after embed_node so query_embedding is already available.
    """
    from services.memory_service import search_memory

    db = state.get("_db")
    client_id = state.get("client_id")
    embedding = state.get("query_embedding", [])

    if not embedding or state.get("done"):
        return {"long_term_memory": []}

    memories = await search_memory(
        client_id=client_id,
        query_embedding=embedding,
        db=db,
        top_k=settings.memory_top_k,
    )
    return {"long_term_memory": memories}


def _embed_nim(text: str) -> list:
    """Single-query NIM embedding via direct HTTP."""
    import httpx

    url = f"{settings.nim_base_url}/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.nim_embed_api_key or settings.nim_llm_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": settings.embedding_model,
        "input": [text],
        "input_type": "query",
        "encoding_format": "float",
        "truncate": "END",
    }
    with httpx.Client(timeout=settings.embed_timeout_seconds) as client:
        resp = client.post(url, headers=headers, json=payload)
        if not resp.is_success:
            raise ValueError(f"NIM embed {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
    return data["data"][0]["embedding"]


def _embed_gemini(text: str) -> list:
    """Single-query Gemini embedding."""
    import google.generativeai as genai


    result = genai.embed_content(
        model=settings.embedding_model,
        content=text,
        task_type="retrieval_query",
    )
    return result["embedding"]


async def retrieve_node(state: BotState) -> dict:
    """
    Query ChromaDB for top-K relevant chunks.

    MED-02 fix: The previous implementation was a plain `def` that called
    `query_knowledge_base()` (a blocking HTTP call to the ChromaDB service)
    directly on the async event loop. This stalled ALL concurrent requests
    for the entire duration of the ChromaDB round-trip (typically 50-300ms).

    Fix: Run the blocking call inside asyncio's default executor (thread pool)
    so the event loop stays free to handle other in-flight requests.
    """
    if not state.get("query_embedding"):
        return {"retrieved_chunks": [], "retrieved_distances": []}
    # P1.5 fix: replaced deprecated asyncio.get_event_loop().run_in_executor() with asyncio.to_thread()
    results = await asyncio.to_thread(
        query_knowledge_base,
        state["query_embedding"],
        settings.rag_top_k_results,
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
        async with httpx.AsyncClient(timeout=settings.rerank_timeout_seconds) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        rankings = data.get("rankings", [])
        if not rankings:
            return {}

        # Reorder chunks and distances by reranker score (highest first)
        sorted_rankings = sorted(
            rankings, key=lambda x: x.get("logit", 0), reverse=True
        )
        reranked_chunks = []
        reranked_distances = []
        for rank in sorted_rankings:
            idx = rank.get("index", 0)
            if idx < len(chunks):
                reranked_chunks.append(chunks[idx])
                reranked_distances.append(
                    distances[idx] if idx < len(distances) else 1.0
                )

        logger.info(f"[BOT][NIM] reranked {len(reranked_chunks)} chunks")
        return {
            "retrieved_chunks": reranked_chunks,
            "retrieved_distances": reranked_distances,
        }

    except Exception as e:
        logger.warning(f"[BOT] rerank skipped (non-fatal): {e}")
        return {}  # pipeline continues with original retrieval order


def context_check_node(state: BotState) -> dict:
    """Check if retrieved context is useful.
    ChromaDB cosine distance is on a 0-2 scale.
    Threshold 1.2 = anything up to 60% cosine distance passes.
    Images bypass KB check — the image description IS the context.
    """
    message = state.get("clean_message", "")
    has_image = "[Attached image:" in message or "Attached image" in message

    if has_image:
        # Image description is embedded in the message — always proceed to generate
        logger.info("[BOT] context check → image message, bypassing KB requirement")
        return {"has_image_context": True}

    dists = state.get("retrieved_distances", [])
    chunks = state.get("retrieved_chunks", [])
    if not chunks or not dists or min(dists) > settings.rag_distance_threshold:
        logger.info(f"[BOT] context check → no useful context (dists={dists[:3]})")
        return {"done": True, "fallback_reason": "no_context"}
    return {}


async def generate_node(state: BotState) -> dict:
    """Generate a grounded response using the configured provider (NIM or Gemini).

    NOTE: Both _generate_nim and _generate_gemini are synchronous. We run them
    in the thread-pool executor so they do NOT block the async event loop.
    """
    lang_label = "Hindi" if state["language"] == "hi" else "English"
    chunks = state.get("retrieved_chunks", [])
    has_image_context = state.get("has_image_context", False)

    history_text = ""
    for msg in state.get("chat_history", []):
        role = "Customer" if msg["role"] == "user" else "Assistant"
        history_text += f"{role} said: {msg['content']}\n"

    history_prompt = (
        f"Previous conversation history with this customer:\n{history_text}\n"
        if history_text
        else ""
    )

    # Long-term memory: relevant past exchanges retrieved from database
    memory_text = ""
    for mem in state.get("long_term_memory", []):
        memory_text += f"Customer asked: {mem['user_message']}\nYou answered: {mem['bot_response']}\n\n"
    memory_prompt = (
        f"Relevant past conversations with this customer (from previous sessions):\n{memory_text}"
        if memory_text
        else ""
    )

    if chunks:
        # Normal RAG: answer from KB context
        context = "\n\n".join(chunks)
        prompt = (
            f"You are a friendly customer service assistant for {settings.business_name}.\n"
            f"Business Description: {settings.business_description}\n\n"
            f"Answer ONLY based on the context provided below. "
            f"Do NOT make up information not in the context.\n"
            f"When quoting prices, ALWAYS include the Unit of measurement, Minimum Order Quantity (MOQ), and GST details if they are present in the context.\n"
            f"If you provide pricing or product details, politely append: 'Interested in placing an order? Reply *ORDER* and we'll connect you.'\n"
            f"Formatting CRITICAL: If you list multiple products, features, or items, you MUST use bullet points and line breaks. Avoid long comma-separated sentences. Structure your response to be easy to read.\n"
            f"Respond in {lang_label}. Be concise.\n\n"
            f"Context:\n{context}\n\n"
            f"{memory_prompt}"
            f"{history_prompt}"
            f"Current customer question: {state['clean_message']}\n\n"
            f"Answer:"
        )
    elif has_image_context:
        # Image query: the image description is embedded in the message itself
        prompt = (
            f"You are a friendly customer service assistant for {settings.business_name}.\n"
            f"Business Description: {settings.business_description}\n\n"
            f"A customer has sent an image with a question. "
            f"The image has been analysed and the description is included in the message below.\n"
            f"Answer the customer's question based on the image description and your product expertise.\n"
            f"Formatting CRITICAL: If you list multiple products, features, or items, you MUST use bullet points and line breaks. Avoid long comma-separated sentences. Structure your response to be easy to read.\n"
            f"Respond in {lang_label}. Be helpful, friendly and concise.\n\n"
            f"{memory_prompt}"
            f"{history_prompt}"
            f"Current customer message with image: {state['clean_message']}\n\n"
            f"Answer:"
        )
    else:
        return {"done": True, "fallback_reason": "no_context"}

    provider = "nim" if settings.is_nim else "gemini"
    logger.info(f"[BOT][GENERATE] Starting generation via {provider}")
    try:
        if settings.is_nim:
            # P1.5 fix: asyncio.to_thread() replaces deprecated get_event_loop().run_in_executor()
            response_text = await asyncio.to_thread(_generate_nim, prompt)
        else:
            response_text = await asyncio.to_thread(_generate_gemini, prompt)
        logger.info(f"[BOT][GENERATE] OK — response {len(response_text)} chars via {provider}")

        # Layer 4: record token usage (accurate with tiktoken)
        try:
            from services.guardrails.ops_guard import record_tokens
            import tiktoken
            # cl100k_base is a good proxy for most modern LLMs (Llama 3, Gemini)
            enc = tiktoken.get_encoding("cl100k_base")
            _approx_tokens = len(enc.encode(prompt)) + len(enc.encode(response_text))
            await record_tokens(state["phone"], _approx_tokens)
        except Exception as _te:
            logger.debug(f"[GUARDRAIL][OPS] token record failed: {_te}")

        return {"response": response_text}
    except Exception as e:
        logger.error(f"[BOT][GENERATE] FAILED via {provider}: {type(e).__name__}: {e}", exc_info=True)
        return {"fallback_reason": "no_context", "done": True}


def _generate_nim(prompt: str) -> str:
    """Generate via NVIDIA NIM (OpenAI-compatible chat completions)."""
    from openai import OpenAI

    client = OpenAI(base_url=settings.nim_base_url, api_key=settings.nim_llm_api_key)
    resp = client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
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
    
    flagged = confidence < settings.rag_confidence_threshold
    
    # Bypass flagging if this is a deterministic menu selection
    if state.get("is_menu_request"):
        flagged = False
        
    logger.info(f"[BOT] confidence={confidence}, flagged={flagged} (menu_request={state.get('is_menu_request', False)})")
    return {"confidence_score": confidence, "flagged": flagged}


async def fallback_node(state: BotState) -> dict:
    """Handle fallback: rate-limit gets a static message.
    No-context gets a NIM/Gemini-powered general answer instead of a generic reply.

    NOTE: LLM calls are synchronous — run them in executor to avoid blocking.
    """
    lang = state.get("language", "en")
    reason = state.get("fallback_reason", "")

    if reason == "rate_limit":
        msg = RATE_LIMIT_MSGS.get(lang, RATE_LIMIT_MSGS["en"])
        return {"response": msg, "confidence_score": 0.0, "flagged": False}

    if reason == "order_intent":
        try:
            adapter = _get_adapter()
            if settings.owner_phone:
                history = state.get("chat_history", [])
                last_inquiry = "Unknown"
                # Find the most recent message sent by the user before 'ORDER'
                for msg_dict in reversed(history):
                    if msg_dict.get("role") == "user":
                        last_inquiry = msg_dict.get("content", "Unknown")
                        break

                client_name = ""
                db = state.get("_db")
                client_id_str = state.get("client_id")
                if db and client_id_str:
                    import uuid
                    from sqlalchemy import select
                    from models.models import Client
                    try:
                        result = await db.execute(select(Client).where(Client.id == uuid.UUID(client_id_str)))
                        client_record = result.scalar_one_or_none()
                        if client_record and client_record.name:
                            client_name = client_record.name
                    except Exception as db_e:
                        logger.warning(f"[BOT] Failed to get client details for order alert: {db_e}")

                name_str = f"Name: {client_name}\n" if client_name else ""

                owner_msg = (
                    f"🚨 *NEW ORDER LEAD* 🚨\n"
                    f"{name_str}"
                    f"Phone: {state.get('phone')}\n\n"
                    f'📝 *Last inquiry:* "{last_inquiry}"\n\n'
                    f"Client responded to the order prompt! Please contact them."
                )
                await adapter.send_message(
                    phone=settings.owner_phone, message=owner_msg
                )
                logger.info(
                    f"[BOT] Alerted owner about new order lead from {state.get('phone')} (Name: {client_name})."
                )
        except Exception as e:
            logger.error(f"[BOT] Failed to alert owner about order lead: {e}")

        return {
            "response": "Great! Our team has been notified and will contact you shortly to confirm your order details. 📞",
            "confidence_score": 1.0,
            "flagged": False,
            "enquiry_intent": True,
        }

    if reason == "no_context":
        # Try to answer from general knowledge instead of a static message
        lang_label = "Hindi" if lang == "hi" else "English"
        # LOW-03 fix: Was hardcoded to "Devraj Traders". Using settings.business_name
        # ensures the bot identifies itself correctly after any rename in .env.
        prompt = (
            f"You are a friendly WhatsApp customer service assistant for {settings.business_name}.\n"
            f"Business Description: {settings.business_description}\n\n"
            f"Answer the customer's question as helpfully as possible based on your general knowledge.\n"
            f"If you don't know the specific answer, invite them to contact us for details.\n"
            f"Formatting CRITICAL: If you list multiple products, features, or items, you MUST use bullet points and line breaks. Avoid long comma-separated sentences.\n"
            f"Respond in {lang_label}. Be concise. Do NOT start with 'Great question!'.\n\n"
            f"Customer question: {state.get('clean_message', '')}\n\n"
            f"Answer:"
        )
        # P1.5 fix: asyncio.to_thread() replaces deprecated get_event_loop().run_in_executor()
        try:
            if settings.is_nim:
                msg = await asyncio.to_thread(_generate_nim, prompt)
            else:
                msg = await asyncio.to_thread(_generate_gemini, prompt)
            if msg:
                logger.info("[BOT] fallback answered via general knowledge")
                return {"response": msg, "confidence_score": 0.3, "flagged": True}
        except Exception as e:
            logger.warning(f"[BOT] fallback LLM call failed: {e}")

        # Ultimate fallback: static message
        msg = UNANSWERED_MSGS.get(lang, UNANSWERED_MSGS["en"])
        return {"response": msg, "confidence_score": 0.0, "flagged": True}

    msg = FALLBACK_MSGS.get(lang, FALLBACK_MSGS["en"])
    return {"response": msg, "confidence_score": 0.0, "flagged": False}

async def output_node(state: BotState) -> dict:
    """Send response via messaging adapter and log Conversation to Postgres.

    Layer 3 (Output Guard) is applied here: the response is sanitized/truncated
    before being sent.  Guardrail failures are non-fatal — the original response
    is used as a safe fallback.
    """
    response = state.get("response", FALLBACK_MSGS["en"])

    # ── Layer 3: Output Guardrail ─────────────────────────────────────────────
    try:
        from services.guardrails.output_guard import check_output
        out_result = check_output(response, context={"phone": state["phone"]})
        if out_result.blocked:
            logger.warning(
                f"[GUARDRAIL][OUTPUT] Response blocked (reason={out_result.reason}) "
                f"for {state['phone']} — using fallback"
            )
        response = out_result.response
    except Exception as _oe:
        logger.warning(f"[GUARDRAIL][OUTPUT] Output guard failed (non-fatal): {_oe}")

    logger.info(f"[BOT][OUTPUT] Sending response to {state['phone']} | fallback_reason={state.get('fallback_reason','')} | len={len(response)}")
    logger.debug(f"[BOT][OUTPUT] Response preview: {response[:120]}")

    adapter = _get_adapter()
    try:
        result = await adapter.send_message(phone=state["phone"], message=response)
        logger.info(f"[BOT][OUTPUT] send_message OK → {result}")

        from core.redis_client import add_conversation_history

        await add_conversation_history(state["phone"], state["raw_message"], response)
    except Exception as e:
        logger.error(f"[BOT][OUTPUT] send_message FAILED for {state['phone']}: {type(e).__name__}: {e}", exc_info=True)

    # Always log the conversation in an isolated fresh session so that any
    # aborted transaction on the caller's shared session doesn't pollute this
    # INSERT (the root cause of InFailedSQLTransactionError — DB-FIX-001).
    from core.database import get_db_context as _get_db_context
    from models.models import Conversation

    async def _log_conversation(fresh_db) -> None:
        """Write the Conversation row and schedule an embedding task."""
        try:
            conv = Conversation(
                client_id=uuid.UUID(state["client_id"]) if state.get("client_id") else None,
                direction="inbound",
                message=state["raw_message"],
                response=response,
                language=state.get("language", "en"),
                confidence_score=state.get("confidence_score"),
                flagged=state.get("flagged", False),
                enquiry_intent=state.get("enquiry_intent", False),
            )
            fresh_db.add(conv)
            await fresh_db.commit()
            logger.info(f"[BOT] conversation logged (flagged={conv.flagged})")

            if state.get("client_id") and state.get("query_embedding"):
                try:
                    from services.memory_service import embed_and_save
                    from core.database import get_db_context as _get_db_context

                    _conv_id = conv.id
                    _raw_msg = state["raw_message"]

                    async def _embed_task():
                        try:
                            async with _get_db_context() as fresh_db:
                                await embed_and_save(_conv_id, _raw_msg, fresh_db)
                        except Exception as _e:
                            logger.warning(f"[BOT] embed_and_save background task failed: {_e}")

                    asyncio.create_task(_embed_task())
                except Exception as e:
                    logger.warning(f"[BOT] embed_and_save task creation failed: {e}")
        except Exception as db_exc:
            logger.error(f"[BOT][OUTPUT] DB logging failed: {type(db_exc).__name__}: {db_exc}", exc_info=True)

    try:
        async with _get_db_context() as fresh_db:
            await _log_conversation(fresh_db)
    except Exception as sess_exc:
        logger.error(f"[BOT][OUTPUT] Could not open DB session for logging: {sess_exc}", exc_info=True)

    return {}


# ─── Conditional edge helpers ─────────────────────────────────────────────────


def should_fallback_after_rate(state: BotState) -> str:
    return "fallback" if state.get("done") else "order_intent"


def should_fallback_after_order_intent(state: BotState) -> str:
    return "fallback" if state.get("done") else "detect_language"


def should_fallback_after_injection(state: BotState) -> str:
    return "fallback" if state.get("done") else "embed"


def should_fallback_after_context(state: BotState) -> str:
    return "fallback" if state.get("done") else "generate"


def should_fallback_after_embed(state: BotState) -> str:
    return "fallback" if state.get("done") else "memory_retrieve"


def should_fallback_after_generate(state: BotState) -> str:
    return "fallback" if state.get("done") else "confidence_check"


# ─── Build graph ──────────────────────────────────────────────────────────────


def build_rag_graph():
    g = StateGraph(BotState)

    g.add_node("sanitise", sanitise_node)
    g.add_node("rate_limit", rate_limit_node)
    g.add_node("order_intent", order_intent_node)
    g.add_node("detect_language", detect_language_node)
    g.add_node("injection_guard", injection_guard_node)
    g.add_node("embed", embed_node)
    g.add_node("memory_retrieve", memory_retrieve_node)  # NEW — long-term memory
    g.add_node("retrieve", retrieve_node)
    g.add_node("rerank", rerank_node)
    g.add_node("context_check", context_check_node)
    g.add_node("generate", generate_node)
    g.add_node("confidence_check", confidence_check_node)
    g.add_node("fallback", fallback_node)
    g.add_node("output", output_node)

    g.add_edge(START, "sanitise")
    g.add_edge("sanitise", "rate_limit")
    g.add_conditional_edges("rate_limit", should_fallback_after_rate)
    g.add_conditional_edges("order_intent", should_fallback_after_order_intent)
    g.add_edge("detect_language", "injection_guard")
    g.add_conditional_edges("injection_guard", should_fallback_after_injection)
    g.add_conditional_edges(
        "embed", should_fallback_after_embed
    )  # embed → memory_retrieve
    g.add_edge("memory_retrieve", "retrieve")  # memory_retrieve → retrieve
    g.add_edge("retrieve", "rerank")  # retrieve → rerank → context_check
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
    from services.messaging_adapter import get_messaging_adapter

    return get_messaging_adapter()


# ─── Public entrypoint ────────────────────────────────────────────────────────


async def run_bot(
    phone: str,
    raw_message: str,
    client_id: str | None = None,
    db=None,
    is_menu_request: bool = False,
) -> dict:
    """
    Runs the full RAG pipeline and returns the final state.
    Call this from the inbound webhook handler.
    """
    from core.redis_client import get_conversation_history

    history = await get_conversation_history(phone)

    initial: BotState = {
        "client_id": client_id,
        "phone": phone,
        "raw_message": raw_message,
        "clean_message": "",
        "language": "en",
        "chat_history": history,
        "long_term_memory": [],  # populated by memory_retrieve_node
        "query_embedding": [],
        "retrieved_chunks": [],
        "retrieved_distances": [],
        "response": "",
        "confidence_score": 0.0,
        "flagged": False,
        "fallback_reason": "",
        "done": False,
        "enquiry_intent": False,
        "is_menu_request": is_menu_request,
        "_db": db,
    }
    final_state = await _rag_graph.ainvoke(initial)
    return final_state
