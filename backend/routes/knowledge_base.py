"""
Knowledge Base routes — Phase 3.1
  POST   /knowledge-base/upload    — ingest PDF/image/text file
  GET    /knowledge-base           — list indexed documents
  DELETE /knowledge-base/{id}      — remove from ChromaDB + mark inactive
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, Query

from core.database import get_db
from core.security import get_current_user
from core.responses import success_response
from services import knowledge_service

router = APIRouter(prefix="/knowledge-base", tags=["Knowledge Base"])

VALID_CATEGORIES = {"products", "offers", "documents", "broadcasts"}


# ─── POST /knowledge-base/upload ─────────────────────────────────────────────

@router.post("/upload", status_code=200)
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form(...),
    valid_from: Optional[str] = Form(None),
    valid_until: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Upload a document for RAG indexing.
    - Supported: PDF, PNG, JPG, JPEG, WEBP, TXT, MD
    - Max size: 20MB
    - category: products / offers / documents / broadcasts
    - Offers require valid_from and valid_until (ISO 8601 format)
    """
    if category not in VALID_CATEGORIES:
        from fastapi import HTTPException
        raise HTTPException(400, f"category must be one of: {', '.join(VALID_CATEGORIES)}")

    # Parse optional dates
    vf = datetime.fromisoformat(valid_from) if valid_from else None
    vu = datetime.fromisoformat(valid_until) if valid_until else None

    file_bytes = await file.read()

    result = await knowledge_service.ingest_document(
        db=db,
        file_bytes=file_bytes,
        filename=file.filename,
        category=category,
        valid_from=vf,
        valid_until=vu,
    )

    return success_response(result)


# ─── GET /knowledge-base ──────────────────────────────────────────────────────

@router.get("")
async def list_documents(
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """List all indexed documents for this tenant. Filter by category."""
    result = await knowledge_service.list_documents(
        db=db,
        category=category,
        page=page,
        page_size=page_size,
    )
    return success_response(result)


# ─── DELETE /knowledge-base (clear ALL) ──────────────────────────────────────

@router.delete("", status_code=200)
async def clear_all_documents(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    ⚠️  Destructive — wipes the entire knowledge base.
    Drops and recreates the ChromaDB collection (all vectors gone)
    and hard-deletes every KnowledgeBase record from Postgres.
    Use before loading a fresh knowledge base.
    """
    result = await knowledge_service.clear_all_documents(db=db)
    return success_response(result)


# ─── DELETE /knowledge-base/{id} ─────────────────────────────────────────────

@router.delete("/{doc_id}", status_code=200)
async def delete_document(
    doc_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Delete document vectors from ChromaDB and mark as inactive in Postgres."""
    result = await knowledge_service.delete_document(
        db=db,
        doc_id=doc_id,
    )
    return success_response(result)
