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

    # OpenAI (optional fallback)
    openai_api_key: str = ""

    # Gemini (active provider)
    gemini_api_key: str = ""
    llm_provider: str = "gemini"              # "openai" | "gemini"
    llm_model: str = "models/gemini-2.0-flash-lite"  # used for response generation
    embedding_model: str = "models/gemini-embedding-001"  # Gemini embedding model

    # Gupshup
    gupshup_mode: str = "mock"  # "mock" | "real"
    gupshup_api_key: str = ""
    gupshup_app_name: str = ""
    gupshup_sender_number: str = ""
    gupshup_webhook_secret: str = ""

    # SendGrid
    sendgrid_api_key: str = ""
    alert_email_from: str = ""
    owner_alert_email: str = ""

    # Sentry
    sentry_dsn: str = ""

    # CORS
    allowed_origins: str = "http://localhost:3000,http://localhost:5173"

    # Uploads
    upload_dir: str = "/app/uploads"
    max_upload_size_mb: int = 20

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
