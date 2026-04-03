from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── App ─────────────────────────────────────────────────────────────────────
    app_env: str = "development"
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # ── Database ─────────────────────────────────────────────────────────────────
    database_url: str

    # ── Redis ────────────────────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # ── ChromaDB ─────────────────────────────────────────────────────────────────
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

    # ── Business / Brand Identity ────────────────────────────────────────────────
    # Used in welcome messages and filenames sent to customers
    business_name: str = "Devraj Traders"
    catalogue_filename: str = "Devraj_Traders_Product_Catalogue.pdf"
    timezone: str = "Asia/Kolkata"

    # ── Messaging Providers ──────────────────────────────────────────────────────
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

    # ── Owner ────────────────────────────────────────────────────────────────────
    owner_phone: str = ""
    # Support contact shown to clients in fallback RAG bot messages
    support_phone: str = ""

    # ── Broadcast ────────────────────────────────────────────────────────────────
    broadcast_cooldown_hours: int = 1
    broadcast_cooldown_enabled: bool = True
    flagged_digest_hours: int = 2

    # ── CORS ─────────────────────────────────────────────────────────────────────
    allowed_origins: str = "http://localhost:3000,http://localhost:5173"

    # ── Catalogue ────────────────────────────────────────────────────────────────
    catalogue_url: str = ""
    # Redis key used to store/retrieve the dynamic catalogue URL set by the owner.
    catalogue_redis_key: str = "catalogue_url"

    # ── Uploads ──────────────────────────────────────────────────────────────────
    upload_dir: str = "/app/uploads"
    max_upload_size_mb: int = 20

    # ── AI Generation Parameters ─────────────────────────────────────────────────
    # Main LLM (RAG bot responses)
    llm_max_tokens: int = 512
    llm_temperature: float = 0.7
    # Broadcast message personalisation
    personalise_max_tokens: int = 256
    personalise_temperature: float = 0.8
    # Media — vision (image analysis)
    vision_max_tokens: int = 256
    # Media — audio transcription
    audio_max_tokens: int = 512

    # ── RAG / Knowledge Base Parameters ──────────────────────────────────────────
    # Number of top ChromaDB chunks retrieved per query
    rag_top_k_results: int = 15
    # Cosine distance threshold — results above this are too far to be relevant
    rag_distance_threshold: float = 1.2
    # Confidence score below which the bot flags the query for owner review
    rag_confidence_threshold: float = 0.75
    # Number of past conversation turns retrieved from long-term memory
    memory_top_k: int = 3
    # Knowledge base document chunking
    kb_chunk_size: int = 512
    kb_chunk_overlap: int = 50
    # Maximum characters kept from an inbound user message before processing
    bot_message_max_length: int = 1000
    # Maximum characters extracted from a PDF in media processing
    media_pdf_max_chars: int = 3000

    # ── Rate Limits ───────────────────────────────────────────────────────────────
    # RAG bot — max messages a single client can send per hour
    bot_rate_limit_per_hour: int = 20
    # Broadcast — delay between each message send (~80 msg/sec at 0.013)
    broadcast_send_delay_seconds: float = 0.013
    # Broadcast — Celery retry settings
    broadcast_max_retries: int = 3
    broadcast_retry_delay_seconds: int = 60
    # Broadcast — minimum time in future a scheduled broadcast must be
    broadcast_min_lead_time_minutes: int = 5
    # Celery Beat — how often expired KB offers are deactivated (seconds)
    kb_expiry_check_interval_seconds: float = 86400.0
    # Flagged conversation digest — max items per digest message to owner
    digest_max_items: int = 20

    # ── HTTP Timeouts (seconds) ───────────────────────────────────────────────────
    # Gupshup / Twilio API calls
    http_timeout_seconds: float = 10.0
    # NIM/Gemini embedding API
    embed_timeout_seconds: int = 30
    # Media file downloads (images, PDFs, audio from WhatsApp)
    media_download_timeout_seconds: int = 30
    # NIM reranking API
    rerank_timeout_seconds: int = 15
    # Large file downloads via owner command (e.g. /import CSV)
    file_download_timeout_seconds: int = 60

    # ── Session / State TTLs ──────────────────────────────────────────────────────
    # How long per-user chat history is kept in Redis
    chat_history_ttl_seconds: int = 3600
    # How many conversation turns (user+bot pairs) to keep in Redis
    chat_history_max_turns: int = 3
    # How long the onboarding state machine waits for a reply before expiring
    onboard_state_ttl_seconds: int = 86400
    # How long the interactive menu state is kept per user in Redis
    menu_state_ttl_seconds: int = 1800   # 30 minutes
    # Max items shown per sub-menu page (WhatsApp list-picker hard limit = 10)
    menu_page_size: int = 10

    # ── Infrastructure ────────────────────────────────────────────────────────────
    # Temp directory for downloaded media files before processing
    media_cache_dir: str = "/tmp/twinai_media"
    # Minimum owner account password length
    min_password_length: int = 8

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    @property
    def is_nim(self) -> bool:
        return self.llm_provider.lower() == "nim"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
