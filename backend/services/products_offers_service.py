"""
Products & Offers Service — Bulk Import and CRUD helpers

Supports:
  - Parsing CSV / XLSX files into validated row dicts
  - Bulk-inserting products and offers into PostgreSQL
  - Listing products / offers with pagination
  - Soft-deactivating individual products / offers

CSV column matching is case-insensitive and whitespace-tolerant so owners
can use real spreadsheet headers like "Product Name" or "Price (INR)".
"""
import io
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Product, Offer

logger = logging.getLogger(__name__)


# ─── Column-name aliases ─────────────────────────────────────────────────────
# Maps recognised header variants → canonical key

_PRODUCT_ALIASES: dict[str, str] = {
    "name": "name",
    "product": "name",
    "product name": "name",
    "product_name": "name",
    "item": "name",
    "item name": "name",
    "description": "description",
    "desc": "description",
    "details": "description",
    "price": "price",
    "rate": "price",
    "mrp": "price",
    "price (inr)": "price",
    "price(inr)": "price",
    "cost": "price",
    "amount": "price",
    "image": "image_url",
    "image_url": "image_url",
    "image url": "image_url",
    "photo": "image_url",
    "picture": "image_url",
    "is_active": "is_active",
    "active": "is_active",
    "status": "is_active",
}

_OFFER_ALIASES: dict[str, str] = {
    "title": "title",
    "offer": "title",
    "offer title": "title",
    "offer_title": "title",
    "name": "title",
    "description": "description",
    "desc": "description",
    "details": "description",
    "valid_from": "valid_from",
    "start date": "valid_from",
    "start_date": "valid_from",
    "from": "valid_from",
    "valid_until": "valid_until",
    "end date": "valid_until",
    "end_date": "valid_until",
    "until": "valid_until",
    "expiry": "valid_until",
    "expires": "valid_until",
    "is_active": "is_active",
    "active": "is_active",
    "status": "is_active",
}


# ─── Internal helpers ────────────────────────────────────────────────────────

def _normalise_header(h: str) -> str:
    """Lowercase, strip, collapse internal whitespace."""
    return re.sub(r"\s+", " ", h.strip().lower())


def _map_headers(raw_headers: list[str], alias_map: dict[str, str]) -> dict[int, str]:
    """Return {col_index → canonical_key} for known columns."""
    mapping: dict[int, str] = {}
    for i, h in enumerate(raw_headers):
        canonical = alias_map.get(_normalise_header(h))
        if canonical:
            mapping[i] = canonical
    return mapping


def _parse_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    return s not in ("false", "0", "no", "inactive", "n", "")


def _parse_float(val: Any) -> Optional[float]:
    if val is None or str(val).strip() == "":
        return None
    cleaned = re.sub(r"[^\d.]", "", str(val))
    try:
        return float(cleaned)
    except ValueError:
        return None


_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d.%m.%Y"]


def _parse_date(val: Any) -> Optional[datetime]:
    if val is None or str(val).strip() == "":
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=timezone.utc) if val.tzinfo is None else val
    s = str(val).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _read_file(content: bytes, filename: str) -> list[list[Any]]:
    """
    Auto-detect CSV vs XLSX and return a list of rows (first row = headers).
    Each cell value is a raw Python type (str / int / float / datetime / None).
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in ("xlsx", "xls"):
        import openpyxl  # already in requirements.txt
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = [[cell.value for cell in row] for row in ws.iter_rows()]
        wb.close()
        return rows

    # Default: CSV (also handles .csv extension)
    import csv
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    return [row for row in reader]


# ─── Public: Parse ───────────────────────────────────────────────────────────

def parse_products_file(content: bytes, filename: str) -> dict:
    """
    Parse a CSV/XLSX of products.
    Returns:
      {
        "headers": [...detected headers...],
        "rows": [...list of normalised row dicts...],
        "column_mapping": {...},
        "unrecognised_columns": [...],
      }
    """
    raw_rows = _read_file(content, filename)
    if not raw_rows:
        return {"headers": [], "rows": [], "column_mapping": {}, "unrecognised_columns": []}

    raw_headers = [str(h) if h is not None else "" for h in raw_rows[0]]
    col_map = _map_headers(raw_headers, _PRODUCT_ALIASES)
    unrecognised = [raw_headers[i] for i in range(len(raw_headers)) if i not in col_map]

    rows = []
    for raw_row in raw_rows[1:]:
        # Skip completely empty rows
        if not any(c for c in raw_row if c is not None and str(c).strip()):
            continue
        row: dict[str, Any] = {}
        for i, canonical in col_map.items():
            val = raw_row[i] if i < len(raw_row) else None
            row[canonical] = val
        rows.append(row)

    return {
        "headers": raw_headers,
        "column_mapping": {raw_headers[i]: v for i, v in col_map.items()},
        "unrecognised_columns": unrecognised,
        "rows": rows,
    }


def parse_offers_file(content: bytes, filename: str) -> dict:
    """
    Parse a CSV/XLSX of offers.
    Returns same structure as parse_products_file.
    """
    raw_rows = _read_file(content, filename)
    if not raw_rows:
        return {"headers": [], "rows": [], "column_mapping": {}, "unrecognised_columns": []}

    raw_headers = [str(h) if h is not None else "" for h in raw_rows[0]]
    col_map = _map_headers(raw_headers, _OFFER_ALIASES)
    unrecognised = [raw_headers[i] for i in range(len(raw_headers)) if i not in col_map]

    rows = []
    for raw_row in raw_rows[1:]:
        if not any(c for c in raw_row if c is not None and str(c).strip()):
            continue
        row: dict[str, Any] = {}
        for i, canonical in col_map.items():
            val = raw_row[i] if i < len(raw_row) else None
            row[canonical] = val
        rows.append(row)

    return {
        "headers": raw_headers,
        "column_mapping": {raw_headers[i]: v for i, v in col_map.items()},
        "unrecognised_columns": unrecognised,
        "rows": rows,
    }


# ─── Public: Bulk Import ─────────────────────────────────────────────────────

async def bulk_import_products(
    db: AsyncSession,
    rows: list[dict],
) -> dict:
    """
    Validate and insert product rows.
    Returns: {imported, skipped, errors}
    """
    imported = 0
    skipped = 0
    updated = 0
    errors: list[dict] = []

    # Fetch existing active products
    result = await db.execute(select(Product).where(Product.is_active == True))
    existing_products = {p.name.lower(): p for p in result.scalars().all()}

    for idx, row in enumerate(rows, start=2):  # row 1 = header
        name = str(row.get("name") or "").strip()
        if not name:
            errors.append({"row": idx, "reason": "Missing product name", "data": row})
            skipped += 1
            continue

        price = _parse_float(row.get("price"))
        description = str(row.get("description") or "").strip() or None
        image_url = str(row.get("image_url") or "").strip() or None
        is_active_raw = row.get("is_active")
        is_active = _parse_bool(is_active_raw) if is_active_raw is not None else True

        existing = existing_products.get(name.lower())
        if existing:
            existing.price = price
            existing.description = description
            existing.image_url = image_url
            existing.is_active = is_active
            updated += 1
        else:
            product = Product(
                id=uuid.uuid4(),
                name=name,
                description=description,
                price=price,
                image_url=image_url,
                is_active=is_active,
            )
            db.add(product)
            existing_products[name.lower()] = product
            imported += 1

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error(f"[BULK] Product import commit failed: {exc}")
        raise

    logger.info(f"[BULK] Products imported={imported} updated={updated} skipped={skipped}")
    return {"imported": imported, "updated": updated, "skipped": skipped, "errors": errors}


async def bulk_import_offers(
    db: AsyncSession,
    rows: list[dict],
) -> dict:
    """
    Validate and insert offer rows.
    Returns: {imported, skipped, errors}
    """
    imported = 0
    skipped = 0
    updated = 0
    errors: list[dict] = []

    # Fetch existing active offers
    result = await db.execute(select(Offer).where(Offer.is_active == True))
    existing_offers = {o.title.lower(): o for o in result.scalars().all()}

    for idx, row in enumerate(rows, start=2):
        title = str(row.get("title") or "").strip()
        if not title:
            errors.append({"row": idx, "reason": "Missing offer title", "data": row})
            skipped += 1
            continue

        description = str(row.get("description") or "").strip() or None
        valid_from = _parse_date(row.get("valid_from"))
        valid_until = _parse_date(row.get("valid_until"))
        is_active_raw = row.get("is_active")
        is_active = _parse_bool(is_active_raw) if is_active_raw is not None else True

        existing = existing_offers.get(title.lower())
        if existing:
            existing.description = description
            existing.valid_from = valid_from
            existing.valid_until = valid_until
            existing.is_active = is_active
            updated += 1
        else:
            offer = Offer(
                id=uuid.uuid4(),
                title=title,
                description=description,
                valid_from=valid_from,
                valid_until=valid_until,
                is_active=is_active,
            )
            db.add(offer)
            existing_offers[title.lower()] = offer
            imported += 1

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error(f"[BULK] Offer import commit failed: {exc}")
        raise

    logger.info(f"[BULK] Offers imported={imported} updated={updated} skipped={skipped}")
    return {"imported": imported, "updated": updated, "skipped": skipped, "errors": errors}


# ─── Public: List ────────────────────────────────────────────────────────────

async def list_products(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    active_only: bool = False,
) -> dict:
    query = select(Product).order_by(Product.name)
    if active_only:
        query = query.where(Product.is_active == True)

    count_q = select(func.count()).select_from(
        query.with_only_columns(Product.id).subquery()
    )
    total = (await db.execute(count_q)).scalar_one()

    query = query.offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(query)).scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_product_dict(p) for p in items],
    }


async def list_offers(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    active_only: bool = False,
) -> dict:
    query = select(Offer).order_by(Offer.title)
    if active_only:
        query = query.where(Offer.is_active == True)

    count_q = select(func.count()).select_from(
        query.with_only_columns(Offer.id).subquery()
    )
    total = (await db.execute(count_q)).scalar_one()

    query = query.offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(query)).scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_offer_dict(o) for o in items],
    }


# ─── Public: Create single ───────────────────────────────────────────────────

async def create_product(db: AsyncSession, data: dict) -> Product:
    product = Product(id=uuid.uuid4(), **data)
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


async def create_offer(db: AsyncSession, data: dict) -> Offer:
    offer = Offer(id=uuid.uuid4(), **data)
    db.add(offer)
    await db.commit()
    await db.refresh(offer)
    return offer


# ─── Public: Deactivate ──────────────────────────────────────────────────────

async def deactivate_product(db: AsyncSession, product_id: uuid.UUID) -> bool:
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        return False
    product.is_active = False
    await db.commit()
    logger.info(f"[PRODUCTS] Deactivated product {product_id}")
    return True


async def deactivate_offer(db: AsyncSession, offer_id: uuid.UUID) -> bool:
    result = await db.execute(select(Offer).where(Offer.id == offer_id))
    offer = result.scalar_one_or_none()
    if not offer:
        return False
    offer.is_active = False
    await db.commit()
    logger.info(f"[OFFERS] Deactivated offer {offer_id}")
    return True


# ─── Private dict serialisers ─────────────────────────────────────────────────

def _product_dict(p: Product) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "price": p.price,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _offer_dict(o: Offer) -> dict:
    return {
        "id": str(o.id),
        "title": o.title,
        "description": o.description,
        "valid_from": o.valid_from.isoformat() if o.valid_from else None,
        "valid_until": o.valid_until.isoformat() if o.valid_until else None,
        "is_active": o.is_active,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }
