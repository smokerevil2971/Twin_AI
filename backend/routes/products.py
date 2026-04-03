"""
Products & Offers Routes

Prefix  /products  → product CRUD + bulk upload
Prefix  /offers    → offer  CRUD + bulk upload

All endpoints require a valid owner JWT (get_current_user).

Bulk upload flow
────────────────
1.  POST /products/upload?preview=true   → parse only, no DB write (column check)
2.  POST /products/upload                → parse + insert → {imported, skipped, errors}
3.  GET  /products                       → paginated list
4.  POST /products                       → create single product (JSON body)
5.  DELETE /products/{id}               → deactivate product

Same pattern for /offers.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from core.responses import success_response
from models.schemas import ProductCreate, ProductUpdate, OfferCreate, OfferUpdate
from services.products_offers_service import (
    parse_products_file,
    parse_offers_file,
    bulk_import_products,
    bulk_import_offers,
    list_products,
    list_offers,
    create_product,
    create_offer,
    deactivate_product,
    deactivate_offer,
    _product_dict,
    _offer_dict,
)

router = APIRouter(tags=["products & offers"])

_ALLOWED_EXTS = {".csv", ".xlsx", ".xls"}
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB hard cap


def _validate_file(file: UploadFile) -> None:
    ext = ("." + file.filename.rsplit(".", 1)[-1].lower()) if "." in file.filename else ""
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(400, f"Only CSV and XLSX files are accepted. Got: {file.filename}")


# ═══════════════════════════════════════════════════════════════════════════════
#  PRODUCTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/products/upload", status_code=201)
async def upload_products(
    file: UploadFile = File(...),
    preview: bool = Query(
        False,
        description="If true, parse the file and return column info WITHOUT writing to DB.",
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    **Bulk import products from a CSV or XLSX file.**

    Expected columns (case-insensitive, flexible naming):
    - `name` / `product` / `product name` ← **required**
    - `description` / `desc` / `details`
    - `price` / `rate` / `mrp` / `cost`
    - `active` / `is_active` / `status` (default: true)

    Set `?preview=true` to do a dry-run — returns detected headers and row count
    without writing anything to the database.

    Products imported here are **automatically available** in the WhatsApp
    interactive menu the next time a customer taps "🛍️ Products".
    """
    _validate_file(file)
    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise HTTPException(413, "File exceeds 10 MB limit.")

    parsed = parse_products_file(content, file.filename)

    if preview:
        return success_response({
            "mode": "preview",
            "filename": file.filename,
            "headers_detected": parsed["headers"],
            "column_mapping": parsed["column_mapping"],
            "unrecognised_columns": parsed["unrecognised_columns"],
            "row_count": len(parsed["rows"]),
            "sample_rows": parsed["rows"][:3],
        })

    if not parsed["rows"]:
        raise HTTPException(422, "No data rows found in the uploaded file.")

    required_check = [r for r in parsed["rows"] if r.get("name")]
    if not required_check:
        raise HTTPException(
            422,
            "Could not detect a 'name' column. "
            "Rename your column header to 'name', 'product', or 'product name'."
        )

    result = await bulk_import_products(db, parsed["rows"])
    return success_response(result, status_code=201)


@router.get("/products")
async def get_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    active_only: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all products with pagination. Use `active_only=true` to filter."""
    data = await list_products(db, page=page, page_size=page_size, active_only=active_only)
    return success_response(data)


@router.post("/products", status_code=201)
async def add_product(
    body: ProductCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a single product via JSON body."""
    product = await create_product(db, body.model_dump())
    return success_response(_product_dict(product), status_code=201)


@router.delete("/products/{product_id}", status_code=204)
async def remove_product(
    product_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a product (soft delete — it disappears from the WhatsApp menu)."""
    ok = await deactivate_product(db, product_id)
    if not ok:
        raise HTTPException(404, f"Product {product_id} not found.")


# ═══════════════════════════════════════════════════════════════════════════════
#  OFFERS
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/offers/upload", status_code=201)
async def upload_offers(
    file: UploadFile = File(...),
    preview: bool = Query(
        False,
        description="If true, parse the file and return column info WITHOUT writing to DB.",
    ),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    **Bulk import offers from a CSV or XLSX file.**

    Expected columns (case-insensitive, flexible naming):
    - `title` / `offer` / `offer title` / `name` ← **required**
    - `description` / `desc`
    - `valid_from` / `start date` / `from`  (format: YYYY-MM-DD or DD/MM/YYYY)
    - `valid_until` / `end date` / `expiry` (format: YYYY-MM-DD or DD/MM/YYYY)
    - `active` / `is_active` (default: true)

    Imported offers appear automatically in the WhatsApp "💰 Offers & Deals" menu.
    """
    _validate_file(file)
    content = await file.read()
    if len(content) > _MAX_BYTES:
        raise HTTPException(413, "File exceeds 10 MB limit.")

    parsed = parse_offers_file(content, file.filename)

    if preview:
        return success_response({
            "mode": "preview",
            "filename": file.filename,
            "headers_detected": parsed["headers"],
            "column_mapping": parsed["column_mapping"],
            "unrecognised_columns": parsed["unrecognised_columns"],
            "row_count": len(parsed["rows"]),
            "sample_rows": parsed["rows"][:3],
        })

    if not parsed["rows"]:
        raise HTTPException(422, "No data rows found in the uploaded file.")

    required_check = [r for r in parsed["rows"] if r.get("title")]
    if not required_check:
        raise HTTPException(
            422,
            "Could not detect a 'title' column. "
            "Rename your column header to 'title', 'offer', or 'offer title'."
        )

    result = await bulk_import_offers(db, parsed["rows"])
    return success_response(result, status_code=201)


@router.get("/offers")
async def get_offers(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    active_only: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all offers with pagination. Use `active_only=true` to filter."""
    data = await list_offers(db, page=page, page_size=page_size, active_only=active_only)
    return success_response(data)


@router.post("/offers", status_code=201)
async def add_offer(
    body: OfferCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a single offer via JSON body."""
    offer = await create_offer(db, body.model_dump())
    return success_response(_offer_dict(offer), status_code=201)


@router.delete("/offers/{offer_id}", status_code=204)
async def remove_offer(
    offer_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate an offer (soft delete — it disappears from the WhatsApp menu)."""
    ok = await deactivate_offer(db, offer_id)
    if not ok:
        raise HTTPException(404, f"Offer {offer_id} not found.")
