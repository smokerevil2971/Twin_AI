"""
Client service — CSV/XLSX parsing, phone validation,
bulk insert with deduplication, and CRUD operations.
Multi-tenancy removed — single owner system.
"""
import csv
import io
import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from models.models import Client

_PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")


def normalise_phone(raw: str) -> str | None:
    cleaned = re.sub(r"[\s\-().]+", "", str(raw).strip())
    if re.match(r"^[6-9]\d{9}$", cleaned):
        cleaned = "+91" + cleaned
    elif re.match(r"^91[6-9]\d{9}$", cleaned):
        cleaned = "+" + cleaned
    return cleaned if _PHONE_RE.match(cleaned) else None


_ALIAS = {
    "name":  {"name", "client name", "customer name", "full name", "contact name"},
    "phone": {"phone", "phone number", "mobile", "mobile number", "whatsapp", "contact"},
    "email": {"email", "email address", "mail"},
}


def detect_column_mapping(columns: list[str]) -> dict[str, str | None]:
    lower_map = {c.lower().strip(): c for c in columns}
    result: dict[str, str | None] = {"name": None, "phone": None, "email": None}
    for field, aliases in _ALIAS.items():
        for alias in aliases:
            if alias in lower_map:
                result[field] = lower_map[alias]
                break
    return result


def parse_upload_file(content: bytes, filename: str) -> list[dict]:
    """
    Parse a CSV or XLSX file into a list of row-dicts.
    Replaces pandas to eliminate the heavy pandas dependency.
    All string values; missing cells default to empty string.
    """
    fname = filename.lower()
    if fname.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")  # handle BOM
        reader = csv.DictReader(io.StringIO(text))
        return [{k: (v or "") for k, v in row.items()} for row in reader]
    elif fname.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
        except ImportError:
            raise ValueError("openpyxl is required to read .xlsx files.")
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
        result = []
        for row in rows[1:]:
            result.append({headers[i]: str(v) if v is not None else "" for i, v in enumerate(row)})
        wb.close()
        return result
    raise ValueError(f"Unsupported file type: {filename}. Use .csv or .xlsx only.")


def get_upload_preview(content: bytes, filename: str) -> dict:
    rows = parse_upload_file(content, filename)
    columns = list(rows[0].keys()) if rows else []
    mapping = detect_column_mapping(columns)
    return {
        "detected_columns": columns,
        "mapping": mapping,
        "row_count": len(rows),
        "mapping_complete": mapping["name"] is not None and mapping["phone"] is not None,
    }


async def import_clients(
    db: AsyncSession,
    content: bytes,
    filename: str,
    column_mapping: dict[str, str],
    set_opted_in: bool = False,
) -> dict:
    rows = parse_upload_file(content, filename)

    name_col = column_mapping.get("name")
    phone_col = column_mapping.get("phone")
    email_col = column_mapping.get("email")

    # TC-007 fix: Validate that the mapped column names actually exist in the file.
    file_cols = list(rows[0].keys()) if rows else []
    missing_cols = [v for v in [name_col, phone_col] if v and v not in file_cols]
    if missing_cols:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Column(s) not found in uploaded file: {missing_cols}. "
                f"Available columns are: {file_cols}. "
                f"Please check your column mapping and try again."
            )
        )

    if not name_col or not phone_col:
        raise ValueError("Column mapping must include at least 'name' and 'phone'.")

    skipped_invalid: list[dict] = []
    skipped_duplicates: list[dict] = []
    valid_rows: list[dict] = []
    seen_in_file: set[str] = set()

    for idx, row in enumerate(rows):
        raw_phone = row.get(phone_col, "")
        phone = normalise_phone(raw_phone)
        name = str(row.get(name_col, "")).strip()
        email = str(row.get(email_col, "")).strip() if email_col else None

        row_num = idx + 2  # 1-based + header row
        if not phone:
            skipped_invalid.append({"row": row_num, "phone": raw_phone, "reason": "invalid phone"})
            continue
        if not name:
            skipped_invalid.append({"row": row_num, "phone": phone, "reason": "missing name"})
            continue
        if phone in seen_in_file:
            skipped_duplicates.append({"row": row_num, "phone": phone, "reason": "duplicate in file"})
            continue

        seen_in_file.add(phone)
        now = datetime.now(timezone.utc)
        valid_rows.append({
            "id": uuid.uuid4(),
            "name": name,
            "phone": phone,
            "email": email or None,
            "opted_in": set_opted_in,
            "language": "en",
            "is_deleted": False,
            "created_at": now,
            "updated_at": now,
        })

    if not valid_rows:
        return {
            "imported": 0,
            "skipped_duplicates": len(skipped_duplicates),
            "skipped_invalid": len(skipped_invalid),
            "skipped_records": skipped_invalid + skipped_duplicates,
        }

    stmt = (
        pg_insert(Client)
        .values(valid_rows)
        .on_conflict_do_nothing(constraint="uq_client_phone")
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


async def list_clients(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 25,
    opted_in: Optional[bool] = None,
    search: Optional[str] = None,
) -> dict:
    q = select(Client).where(Client.is_deleted == False)
    if opted_in is not None:
        q = q.where(Client.opted_in == opted_in)
    if search:
        term = f"%{search}%"
        q = q.where(or_(Client.name.ilike(term), Client.phone.ilike(term)))

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(
            q.order_by(Client.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return {
        "clients": [_client_dict(c) for c in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


async def get_client_or_404(db: AsyncSession, client_id: uuid.UUID) -> Client:
    from fastapi import HTTPException
    result = await db.execute(
        select(Client).where(
            Client.id == client_id,
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


async def bulk_opt_in(db: AsyncSession) -> int:
    result = await db.execute(
        update(Client)
        .where(Client.is_deleted == False)
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
