"""
Knowledge Base ingestion service — Phase 3.1

Pipeline:
  file bytes → extract text → chunk → embed (NIM or Gemini) → store (ChromaDB) → record (Postgres)
"""

import asyncio
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Any

import fitz  # PyMuPDF
from PIL import Image
import pytesseract
import io

import chromadb
from langchain.text_splitter import RecursiveCharacterTextSplitter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from fastapi import HTTPException

from core.config import settings
from models.models import KnowledgeBase

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".md"}
MAX_FILE_SIZE_BYTES = settings.max_upload_size_mb * 1024 * 1024



# ─── Text extraction ──────────────────────────────────────────────────────────


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract raw text from PDF, image, or plain text file.

    For PDFs: first tries native text extraction (fast, works for digital PDFs).
    If the PDF is scanned/image-based and returns no text, falls back to
    rendering each page as an image and running pytesseract OCR on it.
    """
    ext = "." + filename.rsplit(".", 1)[-1].lower()

    if ext == ".pdf":
        text_parts = []
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            for page in doc:
                text_parts.append(page.get_text())
        text = "\n".join(text_parts)

        # Fallback: scanned / image-based PDF — render each page and OCR it
        if not text.strip():
            logger.info(
                f"[KB] '{filename}' has no selectable text — attempting OCR on pages"
            )
            ocr_parts = []
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                for page_num, page in enumerate(doc):
                    # Render page at 2x resolution for better OCR accuracy
                    mat = fitz.Matrix(2.0, 2.0)
                    pix = page.get_pixmap(matrix=mat)
                    img_bytes = pix.tobytes("png")
                    image = Image.open(io.BytesIO(img_bytes))
                    page_text = pytesseract.image_to_string(image)
                    if page_text.strip():
                        ocr_parts.append(page_text)
                    logger.info(f"[KB] OCR page {page_num + 1}: {len(page_text)} chars")
            text = "\n".join(ocr_parts)

    elif ext in {".png", ".jpg", ".jpeg", ".webp"}:
        image = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(image)

    elif ext in {".txt", ".md"}:
        text = file_bytes.decode("utf-8", errors="replace")

    else:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    if not text.strip():
        raise HTTPException(
            422,
            "No text could be extracted from the file. "
            "If this is a scanned PDF, ensure the scan quality is clear. "
            "You can also try uploading it as individual page images (.jpg/.png).",
        )

    logger.info(f"[KB] Extracted {len(text)} chars from {filename}")
    return text


# ─── Semantic chunking ────────────────────────────────────────────────────────


def chunk_text(text: str) -> list[str]:
    """Split text into chunks — size and overlap configurable via KB_CHUNK_SIZE/KB_CHUNK_OVERLAP."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.kb_chunk_size,
        chunk_overlap=settings.kb_chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_text(text)
    logger.info(f"[KB] Split into {len(chunks)} chunks")
    return chunks


# ─── ChromaDB connection ──────────────────────────────────────────────────────

# TC-012 / Minor M5 fix: Cache the ChromaDB HttpClient as a singleton so we
# don't open a new TCP connection on every query call.
# Note: chromadb.HttpClient is a callable factory in some chromadb versions,
# so we use Optional[Any] to avoid a TypeError on annotation evaluation.
_chroma_client: Optional[Any] = None


def get_chroma_client() -> chromadb.HttpClient:
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )
    return _chroma_client


def get_chroma_collection() -> chromadb.Collection:
    """Returns the single shared ChromaDB collection.

    TC-012 fix: Raises HTTPException(503) if ChromaDB is unreachable so the
    caller gets a clean error instead of a raw 500.
    """
    try:
        client = get_chroma_client()
        return client.get_or_create_collection(
            name="knowledge_base",
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        logger.error(f"[KB] ChromaDB connection failed: {e}")
        raise HTTPException(
            503,
            "Knowledge base service is temporarily unavailable. Please try again shortly.",
        )


def query_knowledge_base(
    query_embedding: list[float],
    n_results: int = 15,
) -> dict:
    """
    Query ChromaDB for top-k chunks most similar to the query embedding.
    Only returns chunks where is_active == 'true'.

    TC-012 fix: Returns empty results gracefully if ChromaDB is unreachable
    (the RAG bot will fall back to its no_context path rather than crashing).
    """
    try:
        collection = get_chroma_collection()
        count = collection.count()
        if count == 0:
            return {"documents": [], "distances": []}

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, count),
            where={"is_active": "true"},
            include=["documents", "distances"],
        )
        docs = results["documents"][0] if results["documents"] else []
        dists = results["distances"][0] if results["distances"] else []
        return {"documents": docs, "distances": dists}
    except HTTPException:
        raise  # re-raise clean 503 from get_chroma_collection
    except Exception as e:
        logger.error(f"[KB] ChromaDB query failed: {e}")
        return {"documents": [], "distances": []}


# ─── Embeddings (dual-provider) ───────────────────────────────────────────────


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings using the configured provider.
    LLM_PROVIDER=nim  → NVIDIA NIM nemoretriever (OpenAI-compatible)
    LLM_PROVIDER=gemini → Google Gemini embedding-001
    """
    if settings.is_nim:
        return _embed_texts_nim(texts)
    else:
        return _embed_texts_gemini(texts)


def _embed_texts_nim(texts: list[str]) -> list[list[float]]:
    """
    Embed via NVIDIA NIM using direct HTTP (bypasses OpenAI SDK quirks).
    Uses the LLM API key — NIM keys are universal across all models.
    """
    import httpx, json

    url = f"{settings.nim_base_url}/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.nim_embed_api_key or settings.nim_llm_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    embeddings = []
    batch_size = 50
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        payload = {
            "model": "nvidia/llama-3.2-nemoretriever-300m-embed-v1",
            "input": batch,
            "input_type": "passage",
            "encoding_format": "float",
            "truncate": "END",
        }
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, headers=headers, json=payload)
            if not resp.is_success:
                logger.error(
                    f"[KB][NIM] Embed error {resp.status_code}: {resp.text[:200]}"
                )
                resp.raise_for_status()
            data = resp.json()
        embeddings.extend([item["embedding"] for item in data["data"]])
    logger.info(f"[KB][NIM] Generated {len(embeddings)} embeddings")
    return embeddings


def _embed_texts_gemini(texts: list[str]) -> list[list[float]]:
    """Embed via Google Gemini embedding-001."""
    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)
    embeddings = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        result = genai.embed_content(
            model=settings.embedding_model,
            content=batch,
            task_type="retrieval_document",
        )
        embeddings.extend(result["embedding"])
    logger.info(
        f"[KB][Gemini] Generated {len(embeddings)} embeddings via {settings.embedding_model}"
    )
    return embeddings


# ─── Core ingestion ───────────────────────────────────────────────────────────


async def ingest_document(
    db: AsyncSession,
    file_bytes: bytes,
    filename: str,
    category: str,
    valid_from: Optional[datetime] = None,
    valid_until: Optional[datetime] = None,
) -> dict:
    """
    Full ingestion pipeline:
    1. Extract text
    2. Chunk text
    3. Generate embeddings (NIM or Gemini)
    4. Store in ChromaDB
    5. Save KnowledgeBase record in Postgres
    """
    # Validate file size
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(413, f"File exceeds {settings.max_upload_size_mb}MB limit.")

    # Validate / default offers dates
    if category == "offers":
        from datetime import date

        if not valid_from:
            valid_from = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if not valid_until:
            today = date.today()
            valid_until = datetime(today.year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    # Extract text — CPU-bound (PyMuPDF + pytesseract OCR).
    # Run in thread pool to avoid blocking the async event loop.
    try:
        text = await asyncio.to_thread(extract_text, file_bytes, filename)
    except HTTPException:
        raise  # re-raise clean 400/422 from extract_text
    except Exception as e:
        logger.error(f"[KB] Text extraction failed: {e}")
        raise HTTPException(422, f"Could not extract text from file: {str(e)}")

    # Chunk (fast, in-process — no threading needed)
    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(422, "File produced no usable text chunks.")

    # Embed — synchronous HTTP calls to NIM/Gemini.
    # Run in thread pool to avoid blocking the async event loop.
    try:
        embeddings = await asyncio.to_thread(embed_texts, chunks)
    except Exception as e:
        logger.error(f"[KB] Embedding failed: {e}")
        raise HTTPException(502, f"Embedding service error: {str(e)}")

    # Store in ChromaDB
    collection = get_chroma_collection()
    doc_id = uuid.uuid4()
    chroma_ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
    metadata_list = [
        {
            "doc_id": str(doc_id),
            "category": category,
            "filename": filename,
            "valid_from": valid_from.isoformat() if valid_from else "",
            "valid_until": valid_until.isoformat() if valid_until else "",
            "is_active": "true",
            "chunk_index": i,
        }
        for i in range(len(chunks))
    ]

    collection.add(
        ids=chroma_ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadata_list,
    )
    logger.info(f"[KB] Indexed {len(chunks)} chunks into knowledge_base collection")

    # Save Postgres record
    kb_record = KnowledgeBase(
        id=doc_id,
        filename=filename,
        category=category,
        chroma_ids=chroma_ids,
        valid_from=valid_from,
        valid_until=valid_until,
        is_active=True,
    )
    db.add(kb_record)
    await db.commit()
    await db.refresh(kb_record)

    return {
        "id": str(kb_record.id),
        "filename": kb_record.filename,
        "category": kb_record.category,
        "chunks_indexed": len(chunks),
        "valid_from": kb_record.valid_from.isoformat()
        if kb_record.valid_from
        else None,
        "valid_until": kb_record.valid_until.isoformat()
        if kb_record.valid_until
        else None,
        "is_active": kb_record.is_active,
        "created_at": kb_record.created_at.isoformat(),
        "status": "indexed",
    }


# ─── List documents ───────────────────────────────────────────────────────────


async def list_documents(
    db: AsyncSession,
    category: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    q = select(KnowledgeBase)
    if category:
        q = q.where(KnowledgeBase.category == category)

    total = (
        await db.execute(select(func.count()).select_from(q.subquery()))
    ).scalar_one()
    rows = (
        (
            await db.execute(
                q.order_by(KnowledgeBase.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    return {
        "documents": [_kb_dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


# ─── Delete document ──────────────────────────────────────────────────────────


async def delete_document(
    db: AsyncSession,
    doc_id: uuid.UUID,
) -> dict:
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == doc_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "Document not found.")

    # Remove from ChromaDB
    try:
        collection = get_chroma_collection()
        collection.delete(ids=record.chroma_ids)
        logger.info(f"[KB] Deleted {len(record.chroma_ids)} vectors for doc {doc_id}")
    except Exception as e:
        logger.warning(f"[KB] ChromaDB delete warning: {e}")

    # Mark inactive in Postgres
    await db.execute(
        update(KnowledgeBase).where(KnowledgeBase.id == doc_id).values(is_active=False)
    )
    await db.commit()

    return {"id": str(doc_id), "status": "deleted"}


# ─── Helper ───────────────────────────────────────────────────────────────────


def _kb_dict(r: KnowledgeBase) -> dict:
    return {
        "id": str(r.id),
        "filename": r.filename,
        "category": r.category,
        "chunks_count": len(r.chroma_ids) if r.chroma_ids else 0,
        "valid_from": r.valid_from.isoformat() if r.valid_from else None,
        "valid_until": r.valid_until.isoformat() if r.valid_until else None,
        "is_active": r.is_active,
        "created_at": r.created_at.isoformat(),
    }
