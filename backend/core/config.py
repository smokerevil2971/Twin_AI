from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_env: str = "development"
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # ChromaDB
    chroma_host: str = "chromadb"
    chroma_port: int = 8000

    # ── AI Provider Switch ──────────────────────────────────────────────────────
    # "nim" → NVIDIA NIM     "gemini" → Google Gemini
    llm_provider: str = "nim"

    # ── NVIDIA NIM ──────────────────────────────────────────────────────────────
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nim_llm_api_key: str = ""
    nim_embed_api_key: str = ""
    nim_multimodal_api_key: str = ""
    nim_ocr_api_key: str = ""
    nim_rerank_api_key: str = ""

    # ── Gemini ──────────────────────────────────────────────────────────────────
    gemini_api_key: str = ""

    # ── Shared model names (set in .env, differ per provider) ──────────────────
    # NIM defaults:
    #   llm_model       = "meta/llama-4-maverick-17b-128e-instruct"
    #   embedding_model = "nvidia/llama-3_2-nemoretriever-300m-embed-v1"
    #   multimodal_model= "microsoft/phi-4-multimodal-instruct"
    #   rerank_model    = "nvidia/rerank-qa-mistral-4b"
    # Gemini defaults:
    #   llm_model       = "models/gemini-2.0-flash"
    #   embedding_model = "models/gemini-embedding-001"
    #   multimodal_model= "models/gemini-2.0-flash"
    llm_model: str = "meta/llama-4-maverick-17b-128e-instruct"
    embedding_model: str = "nvidia/llama-3_2-nemoretriever-300m-embed-v1"
    multimodal_model: str = "microsoft/phi-4-multimodal-instruct"
    rerank_model: str = "nvidia/rerank-qa-mistral-4b"

    # OpenAI (legacy / optional)
    openai_api_key: str = ""

    # Gupshup
    gupshup_mode: str = "mock"  # "mock" | "real"
    gupshup_api_key: str = ""
    gupshup_app_name: str = ""
    gupshup_sender_number: str = ""
    gupshup_webhook_secret: str = ""

    # Messaging provider selector
    messaging_provider: str = "gupshup"   # "gupshup" | "twilio"

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = ""
    twilio_skip_sig_validation: str = "true"

    # Owner
    owner_phone: str = ""

    # Broadcast
    broadcast_cooldown_hours: int = 1
    broadcast_cooldown_enabled: bool = True
    flagged_digest_hours: int = 2

    # SendGrid
    sendgrid_api_key: str = ""
    alert_email_from: str = ""
    owner_alert_email: str = ""

    # Sentry
    sentry_dsn: str = ""

    # CORS
    allowed_origins: str = "http://localhost:3000,http://localhost:5173"

    # Catalogue URL
    catalogue_url: str = ""

    # Uploads
    upload_dir: str = "/app/uploads"
    max_upload_size_mb: int = 20

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    @property
    def is_nim(self) -> bool:
        return self.llm_provider.lower() == "nim"

    @property
    def is_gemini(self) -> bool:
        return self.llm_provider.lower() == "gemini"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
