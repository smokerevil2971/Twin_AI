import uuid
from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
import io, csv

from core.database import get_db
from core.security import get_tenant_id
from core.responses import success_response
from core.config import settings
from services.client_service import (
    get_upload_preview,
    import_clients,
    list_clients,
    get_client_or_404,
    update_client,
    soft_delete_client,
    bulk_opt_in,
)

router = APIRouter(prefix="/clients", tags=["clients"])

_ALLOWED_EXTS = {".csv", ".xlsx", ".xls"}
_MAX_BYTES = settings.max_upload_size_mb * 1024 * 1024


def _validate_upload(file: UploadFile) -> None:
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(400, f"Only .csv and .xlsx files are accepted. Got: {file.filename}")


# ─── Preview endpoint (no DB write) ──────────────────────────────────────────

@router.post("/upload/preview")
async def preview_upload(
    file: UploadFile = File(...),
    tenant_id: str = Depends(get_tenant_id),
):
    """Returns detected columns and suggested mapping. No data written to DB."""
    _validate_upload(file)
    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise HTTPException(413, f"File exceeds {settings.max_upload_size_mb}MB limit")
    preview = get_upload_preview(content, file.filename)
    return success_response(preview)


# ─── Confirm import (with column mapping confirmed by operator) ───────────────

class ColumnMapping(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None


class ImportConfirmRequest(BaseModel):
    column_mapping: ColumnMapping
    set_opted_in: bool = False
    opt_in_confirmed: bool = False   # operator must tick consent checkbox


@router.post("/upload", status_code=201)
async def upload_clients(
    file: UploadFile = File(...),
    name_col: str = Query(..., alias="name_col"),
    phone_col: str = Query(..., alias="phone_col"),
    email_col: Optional[str] = Query(None, alias="email_col"),
    set_opted_in: bool = Query(False),
    opt_in_confirmed: bool = Query(False),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Import clients from CSV/XLSX.
    - Validates phone numbers; normalises Indian 10-digit numbers to +91 format.
    - Skips duplicates (existing phone in same tenant).
    - Returns import summary + skipped records for download.
    - opt_in_confirmed must be True to set opted_in=True (compliance gate).
    """
    _validate_upload(file)
    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise HTTPException(413, f"File exceeds {settings.max_upload_size_mb}MB limit")

    if set_opted_in and not opt_in_confirmed:
        raise HTTPException(
            400,
            "opt_in_confirmed must be true when set_opted_in is true. "
            "Owner must confirm all clients have given WhatsApp consent."
        )

    mapping = {"name": name_col, "phone": phone_col, "email": email_col}
    summary = await import_clients(
        db=db,
        tenant_id=uuid.UUID(tenant_id),
        content=content,
        filename=file.filename,
        column_mapping=mapping,
        set_opted_in=set_opted_in and opt_in_confirmed,
    )
    return success_response(summary, status_code=201)


# ─── Download skipped records as CSV ─────────────────────────────────────────

@router.post("/upload/skipped-export")
async def export_skipped(
    skipped: list[dict],
    tenant_id: str = Depends(get_tenant_id),
):
    """Accepts the skipped_records list from an import response and returns it as CSV."""
    output = io.StringIO()
    if skipped:
        writer = csv.DictWriter(output, fieldnames=skipped[0].keys())
        writer.writeheader()
        writer.writerows(skipped)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=skipped_clients.csv"},
    )


# ─── List clients ─────────────────────────────────────────────────────────────

@router.get("")
async def get_clients(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    opted_in: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, min_length=1),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    data = await list_clients(
        db=db,
        tenant_id=uuid.UUID(tenant_id),
        page=page,
        page_size=page_size,
        opted_in=opted_in,
        search=search,
    )
    return success_response(data)


# ─── Update client ────────────────────────────────────────────────────────────

class UpdateClientRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    opted_in: Optional[bool] = None
    language: Optional[str] = None


@router.patch("/{client_id}")
async def patch_client(
    client_id: uuid.UUID,
    body: UpdateClientRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    client = await get_client_or_404(db, uuid.UUID(tenant_id), client_id)
    updated = await update_client(db, client, body.model_dump(exclude_none=True))
    from services.client_service import _client_dict
    return success_response(_client_dict(updated))


# ─── Soft delete ──────────────────────────────────────────────────────────────

@router.delete("/{client_id}", status_code=204)
async def delete_client(
    client_id: uuid.UUID,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    client = await get_client_or_404(db, uuid.UUID(tenant_id), client_id)
    await soft_delete_client(db, client)


# ─── Bulk opt-in ──────────────────────────────────────────────────────────────

class BulkOptInRequest(BaseModel):
    confirmed: bool  # operator must explicitly set True


@router.post("/bulk-opt-in")
async def bulk_opt_in_route(
    body: BulkOptInRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Sets opted_in=True for ALL non-deleted clients of this tenant.
    Owner must confirm (confirmed=True) that all clients have given WhatsApp consent.
    This is a compliance gate — enforced here AND at Celery broadcast task level.
    """
    if not body.confirmed:
        raise HTTPException(
            400,
            "confirmed must be true. Owner must confirm all clients have given WhatsApp consent."
        )
    count = await bulk_opt_in(db, uuid.UUID(tenant_id))
    return success_response({"opted_in_count": count})
