import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

# ─── Auth ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    business_name: str
    email: str
    password: str

class UpdateMeRequest(BaseModel):
    business_name: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

# ─── Clients ─────────────────────────────────────────────────────────────────

class ColumnMapping(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None

class ImportConfirmRequest(BaseModel):
    column_mapping: ColumnMapping
    set_opted_in: bool = False
    opt_in_confirmed: bool = False   # operator must tick consent checkbox

class UpdateClientRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    opted_in: Optional[bool] = None
    language: Optional[str] = None

class BulkOptInRequest(BaseModel):
    confirmed: bool  # operator must explicitly set True

# ─── Broadcasts ──────────────────────────────────────────────────────────────

class CreateBroadcastRequest(BaseModel):
    name: str
    message_template: str
    channel: str = "whatsapp"
    language: str = "en"
    scheduled_at: Optional[datetime] = None
    target_client_ids: Optional[list[uuid.UUID]] = None
    # ─── Media fields (optional) ──────────────────────────────────────────────
    media_url: Optional[str] = None          # publicly accessible URL (image or PDF)
    media_type: Optional[str] = None         # 'image' | 'document'
    media_filename: Optional[str] = None     # friendly filename shown on document
