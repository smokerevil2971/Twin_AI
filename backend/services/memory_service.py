"""
Long-Term Conversation Memory Service

Uses the existing `conversations` table (with a new `embedding` vector column)
to provide semantic search over a user's past chat history.

Two public functions:
  - embed_and_save(conv, db)        : compute + store embedding for a saved Conversation row
  - search_memory(client_id, vec, db) : find top-K past exchanges relevant to a new query
"""
import asyncio
import logging
import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings

logger = logging.getLogger(__name__)


# ─── Embedding helpers (reuse existing logic from rag_bot) ────────────────────

def _embed_gemini(text_input: str) -> list:
    import google.generativeai as genai
    genai.configure(api_key=settings.gemini_api_key)
    result = genai.embed_content(
        model=settings.embedding_model,
        content=text_input,
        task_type="retrieval_document",  # "document" type for storing, not querying
    )
    return result["embedding"]


def _embed_nim(text_input: str) -> list:
    import httpx
    url = f"{settings.nim_base_url}/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.nim_embed_api_key or settings.nim_llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.embedding_model,  # P1.2 fix: was hardcoded — must match rag_bot.py and knowledge_service.py
        "input": [text_input],
        "input_type": "passage",
        "encoding_format": "float",
        "truncate": "END",
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, headers=headers, json=payload)
        if not resp.is_success:
            raise ValueError(f"NIM embed {resp.status_code}: {resp.text[:200]}")
    return resp.json()["data"][0]["embedding"]


async def _get_embedding(text_input: str) -> list:
    """Compute embedding off the event loop (sync SDK calls).
    P1.5 fix: asyncio.get_event_loop() deprecated in Python 3.10+, removed in 3.12.
    Use asyncio.to_thread() — the correct Python 3.9+ replacement.
    """
    try:
        if settings.is_nim:
            return await asyncio.to_thread(_embed_nim, text_input)
        else:
            return await asyncio.to_thread(_embed_gemini, text_input)
    except Exception as e:
        logger.warning(f"[MEMORY] embedding failed: {e}")
        return []


# ─── Public API ───────────────────────────────────────────────────────────────

async def embed_and_save(conversation_id: uuid.UUID, user_message: str, db: AsyncSession) -> None:
    """
    Compute the embedding for the user message and persist it on the
    already-saved Conversation row. Called from output_node after db.commit().

    Runs as a best-effort background operation — failures are logged,
    never raised, so they cannot break the main webhook flow.
    """
    try:
        embedding = await _get_embedding(user_message)
        if not embedding:
            return

        # pgvector expects a list formatted as a string '[0.1, 0.2, ...]'
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
        await db.execute(
            text(
                "UPDATE conversations SET embedding = CAST(:vec AS vector) "
                "WHERE id = :cid"
            ),
            {"vec": vec_str, "cid": str(conversation_id)},
        )
        await db.commit()
        logger.info(f"[MEMORY] embedding saved for conversation {conversation_id}")
    except Exception as e:
        logger.warning(f"[MEMORY] embed_and_save failed (non-fatal): {e}")


async def search_memory(
    client_id: Optional[str],
    query_embedding: list,
    db: AsyncSession,
    top_k: int = 3,
) -> list[dict]:
    """
    Search the conversations table for past exchanges semantically similar
    to the current query. Filtered to the same client (by client_id).

    Returns a list of dicts: [{"user_message": ..., "bot_response": ...}, ...]
    Only returns rows where embedding IS NOT NULL and response IS NOT NULL.
    """
    if not client_id or not query_embedding:
        return []

    try:
        vec_str = "[" + ",".join(str(v) for v in query_embedding) + "]"
        result = await db.execute(
            text(
                "SELECT message, response "
                "FROM conversations "
                "WHERE client_id = :cid "
                "  AND embedding IS NOT NULL "
                "  AND response IS NOT NULL "
                "ORDER BY embedding <=> CAST(:vec AS vector) "
                "LIMIT :top_k"
            ),
            {"cid": client_id, "vec": vec_str, "top_k": top_k},
        )
        rows = result.fetchall()
        memories = [{"user_message": r[0], "bot_response": r[1]} for r in rows]
        logger.info(f"[MEMORY] found {len(memories)} relevant past exchanges for client {client_id}")
        return memories
    except Exception as e:
        logger.warning(f"[MEMORY] search_memory failed (non-fatal): {e}")
        return []
