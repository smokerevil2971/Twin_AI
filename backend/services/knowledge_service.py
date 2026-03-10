"""
Knowledge Base ingestion service — Phase 3.1

Pipeline:
  file bytes → extract text → chunk → embed (Gemini) → store (ChromaDB) → record (Postgres)
"""
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

import fitz                        # PyMuPDF
from PIL import Image
import pytesseract
import io

import chromadb
import google.generativeai as genai
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

CHUNK_SIZE = 512        # tokens (approx chars for splitter)
CHUNK_OVERLAP = 50


# ─── Text extraction ──────────────────────────────────────────────────────────

def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract raw text from PDF, image, or plain text file."""
    ext = "." + filename.rsplit(".", 1)[-1].lower()

    if ext == ".pdf":
        text_parts = []
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            for page in doc:
                text_parts.append(page.get_text())
        text = "\n".join(text_parts)

    elif ext in {".png", ".jpg", ".jpeg", ".webp"}:
        image = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(image)

    elif ext in {".txt", ".md"}:
        text = file_bytes.decode("utf-8", errors="replace")

    else:
        raise HTTPException(400, f"Unsupported file type: {ext}")

    if not text.strip():
        raise HTTPException(422, "No text could be extracted from the file.")

    logger.info(f"[KB] Extracted {len(text)} chars from {filename}")
    return text


# ─── Semantic chunking ────────────────────────────────────────────────────────

def chunk_text(text: str) -> list[str]:
    """Split text into ~512-char chunks with 50-char overlap."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_text(text)
    logger.info(f"[KB] Split into {len(chunks)} chunks")
    return chunks


# ─── ChromaDB connection ──────────────────────────────────────────────────────

def get_chroma_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
    )


def get_chroma_collection() -> chromadb.Collection:
    """Returns the single shared ChromaDB collection."""
    client = get_chroma_client()
    return client.get_or_create_collection(
        name="knowledge_base",
        metadata={"hnsw:space": "cosine"},
    )


def query_knowledge_base(
    query_embedding: list[float],
    n_results: int = 5,
) -> dict:
    """
    Query ChromaDB for top-k chunks most similar to the query embedding.
    Only returns chunks where is_active == 'true'.
    """
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


# ─── Embeddings ───────────────────────────────────────────────────────────────

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate Gemini embeddings using direct google-generativeai SDK."""
    genai.configure(api_key=settings.gemini_api_key)
    embeddings = []
    # Batch in groups of 100 (Gemini API limit per call)
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        result = genai.embed_content(
            model=settings.embedding_model,   # "models/embedding-001"
            content=batch,
            task_type="retrieval_document",
        )
        embeddings.extend(result["embedding"])
    logger.info(f"[KB] Generated {len(embeddings)} embeddings using {settings.embedding_model}")
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
    3. Generate Gemini embeddings
    4. Store in ChromaDB
    5. Save KnowledgeBase record in Postgres
    """
    # Validate file size
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(413, f"File exceeds {settings.max_upload_size_mb}MB limit.")

    # Validate offers have dates
    if category == "offers" and (not valid_from or not valid_until):
        raise HTTPException(422, "Offer documents require both valid_from and valid_until.")

    # Extract text
    text = extract_text(file_bytes, filename)

    # Chunk
    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(422, "File produced no usable text chunks.")

    # Embed via Gemini
    try:
        embeddings = embed_texts(chunks)
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
        "valid_from": kb_record.valid_from.isoformat() if kb_record.valid_from else None,
        "valid_until": kb_record.valid_until.isoformat() if kb_record.valid_until else None,
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

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(
            q.order_by(KnowledgeBase.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

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
        update(KnowledgeBase)
        .where(KnowledgeBase.id == doc_id)
        .values(is_active=False)
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
