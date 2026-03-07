"""
Client service — handles CSV/XLSX parsing, phone validation,
bulk insert with deduplication, and CRUD operations.
"""
import io
import re
import uuid
from typing import Optional
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from models.models import Client


# ─── Phone validation ─────────────────────────────────────────────────────────

_PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")


def normalise_phone(raw: str) -> str | None:
    """Strip spaces/dashes, add +91 if bare 10-digit Indian number."""
    cleaned = re.sub(r"[\s\-().]+", "", str(raw).strip())
    if re.match(r"^[6-9]\d{9}$", cleaned):          # bare Indian mobile
        cleaned = "+91" + cleaned
    elif re.match(r"^91[6-9]\d{9}$", cleaned):       # 91XXXXXXXXXX
        cleaned = "+" + cleaned
    return cleaned if _PHONE_RE.match(cleaned) else None


# ─── Column auto-detection ────────────────────────────────────────────────────

_ALIAS = {
    "name":  {"name", "client name", "customer name", "full name", "contact name"},
    "phone": {"phone", "phone number", "mobile", "mobile number", "whatsapp", "contact"},
    "email": {"email", "email address", "mail"},
}


def detect_column_mapping(columns: list[str]) -> dict[str, str | None]:
    """Returns {'name': col_name, 'phone': col_name, 'email': col_name | None}."""
    lower_map = {c.lower().strip(): c for c in columns}
    result: dict[str, str | None] = {"name": None, "phone": None, "email": None}
    for field, aliases in _ALIAS.items():
        for alias in aliases:
            if alias in lower_map:
                result[field] = lower_map[alias]
                break
    return result


# ─── File parsing ─────────────────────────────────────────────────────────────

def parse_upload_file(content: bytes, filename: str) -> pd.DataFrame:
    """Parse CSV or XLSX into a DataFrame. Raises ValueError on unsupported type."""
    fname = filename.lower()
    if fname.endswith(".csv"):
        return pd.read_csv(io.BytesIO(content), dtype=str).fillna("")
    elif fname.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content), dtype=str).fillna("")
    raise ValueError(f"Unsupported file type: {filename}. Use .csv or .xlsx only.")


# ─── Preview (column mapping only, no DB write) ───────────────────────────────

def get_upload_preview(content: bytes, filename: str) -> dict:
    """Return column mapping preview without writing to DB."""
    df = parse_upload_file(content, filename)
    mapping = detect_column_mapping(list(df.columns))
    return {
        "detected_columns": list(df.columns),
        "mapping": mapping,
        "row_count": len(df),
        "mapping_complete": mapping["name"] is not None and mapping["phone"] is not None,
    }


# ─── Bulk import ──────────────────────────────────────────────────────────────

async def import_clients(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    content: bytes,
    filename: str,
    column_mapping: dict[str, str],  # {"name": "col", "phone": "col", "email": "col|None"}
    set_opted_in: bool = False,
) -> dict:
    """
    Parse file, validate rows, bulk insert valid clients.
    Returns summary: imported, skipped_duplicates, skipped_invalid, skipped_records.
    """
    df = parse_upload_file(content, filename)

    # Apply column mapping
    name_col = column_mapping.get("name")
    phone_col = column_mapping.get("phone")
    email_col = column_mapping.get("email")

    if not name_col or not phone_col:
        raise ValueError("Column mapping must include at least 'name' and 'phone'.")

    skipped_invalid: list[dict] = []
    skipped_duplicates: list[dict] = []
    valid_rows: list[dict] = []
    seen_in_file: set[str] = set()

    for idx, row in df.iterrows():
        raw_phone = row.get(phone_col, "")
        phone = normalise_phone(raw_phone)
        name = str(row.get(name_col, "")).strip()
        email = str(row.get(email_col, "")).strip() if email_col else None

        if not phone:
            skipped_invalid.append({"row": idx + 2, "phone": raw_phone, "reason": "invalid phone"})
            continue
        if not name:
            skipped_invalid.append({"row": idx + 2, "phone": phone, "reason": "missing name"})
            continue
        if phone in seen_in_file:
            skipped_duplicates.append({"row": idx + 2, "phone": phone, "reason": "duplicate in file"})
            continue

        seen_in_file.add(phone)
        valid_rows.append({
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "name": name,
            "phone": phone,
            "email": email or None,
            "opted_in": set_opted_in,
        })

    if not valid_rows:
        return {
            "imported": 0,
            "skipped_duplicates": len(skipped_duplicates),
            "skipped_invalid": len(skipped_invalid),
            "skipped_records": skipped_invalid + skipped_duplicates,
        }

    # Bulk upsert — skip rows with existing (tenant_id, phone) — PostgreSQL ON CONFLICT DO NOTHING
    stmt = (
        pg_insert(Client)
        .values(valid_rows)
        .on_conflict_do_nothing(constraint="uq_tenant_phone")
    )
    result = await db.execute(stmt)
    await db.commit()

    inserted = result.rowcount
    db_duplicates = len(valid_rows) - inserted
    if db_duplicates > 0:
        for row in valid_rows[inserted:]:
            skipped_duplicates.append({"phone": row["phone"], "reason": "already exists in database"})

    return {
        "imported": inserted,
        "skipped_duplicates": len(skipped_duplicates),
        "skipped_invalid": len(skipped_invalid),
        "skipped_records": skipped_invalid + skipped_duplicates,
    }


# ─── CRUD helpers ─────────────────────────────────────────────────────────────

async def list_clients(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    page: int = 1,
    page_size: int = 25,
    opted_in: Optional[bool] = None,
    search: Optional[str] = None,
) -> dict:
    q = select(Client).where(
        Client.tenant_id == tenant_id,
        Client.is_deleted == False,
    )
    if opted_in is not None:
        q = q.where(Client.opted_in == opted_in)
    if search:
        term = f"%{search}%"
        q = q.where(or_(Client.name.ilike(term), Client.phone.ilike(term)))

    total_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(total_q)).scalar_one()

    q = q.order_by(Client.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    return {
        "clients": [_client_dict(c) for c in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


async def get_client_or_404(db: AsyncSession, tenant_id: uuid.UUID, client_id: uuid.UUID) -> Client:
    from fastapi import HTTPException
    result = await db.execute(
        select(Client).where(
            Client.id == client_id,
            Client.tenant_id == tenant_id,
            Client.is_deleted == False,
        )
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


async def update_client(db: AsyncSession, client: Client, fields: dict) -> Client:
    for key, value in fields.items():
        if hasattr(client, key) and value is not None:
            setattr(client, key, value)
    await db.commit()
    await db.refresh(client)
    return client


async def soft_delete_client(db: AsyncSession, client: Client) -> None:
    client.is_deleted = True
    await db.commit()


async def bulk_opt_in(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Set opted_in=True for all non-deleted clients of this tenant. Returns count updated."""
    from sqlalchemy import update
    result = await db.execute(
        update(Client)
        .where(Client.tenant_id == tenant_id, Client.is_deleted == False)
        .values(opted_in=True)
    )
    await db.commit()
    return result.rowcount


def _client_dict(c: Client) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "phone": c.phone,
        "email": c.email,
        "opted_in": c.opted_in,
        "language": c.language,
        "created_at": c.created_at.isoformat(),
    }
