import logging
import sys
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text

from fastapi.staticfiles import StaticFiles
import os

from core.config import settings
from core.middleware import logging_middleware, RequestIDFilter
from routes.auth import router as auth_router
from routes.clients import router as clients_router
from routes.broadcasts import router as broadcasts_router
from routes.webhooks import router as webhooks_router
from routes.knowledge_base import router as knowledge_router
from routes.products import router as products_router

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.app_env == "development" else logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s — %(message)s",
)
root_logger = logging.getLogger()
req_filter = RequestIDFilter()
for handler in root_logger.handlers:
    handler.addFilter(req_filter)
logger = logging.getLogger(__name__)

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

# ─── Sentry ───────────────────────────────────────────────────────────────────
if settings.sentry_dsn:
    logger.info("🔧 Starting Sentry SDK initialization")
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        environment=settings.app_env,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
        ],
    )

# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Devraj Traders — System",
    version="2.0.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url=None,
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
# HIGH-05 fix: Restrict to explicit method and header allowlists.
# Using allow_methods=["*"] + allow_headers=["*"] with allow_credentials=True
# allows any origin (if misconfigured) to make credentialed requests with any
# HTTP verb — including DELETE on admin endpoints.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Accept"],
)

# ─── Request Logging ──────────────────────────────────────────────────────────
app.middleware("http")(logging_middleware)

# ─── Global Error Handlers ────────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "data": None,
            "error": {"message": "Validation error", "detail": exc.errors()},
        },
    )

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "success": False,
            "data": None,
            "error": {"message": f"Route {request.url.path} not found"},
        },
    )

@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "data": None,
            "error": {"message": "Internal server error"},
        },
    )

# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(clients_router)
app.include_router(broadcasts_router)
app.include_router(webhooks_router)
app.include_router(knowledge_router)
app.include_router(products_router)

# ─── Static Media Files (/media/filename) ─────────────────────────────────────
# Images downloaded from Twilio (with auth) are cached here and served publicly
# so they can be used as MediaUrl in outbound WhatsApp messages via ngrok.
UPLOADS_DIR = settings.media_cache_dir
os.makedirs(UPLOADS_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=UPLOADS_DIR), name="media")

# ─── Startup Checks ───────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_checks():
    """
    TC-028: Verify database connectivity at startup.
    Exits immediately with a clear error log if DATABASE_URL is wrong,
    rather than silently failing on the first request.

    TC-019: Warn loudly if OWNER_PHONE is unset so operators know
    WhatsApp owner commands (ADD, REMOVE, BROADCAST, etc.) are disabled.
    """
    from core.database import engine

    # TC-028 — verify DB
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("✅ Database connection verified.")
    except Exception as e:
        logger.critical(
            f"❌ Database connection FAILED at startup — check DATABASE_URL. "
            f"Error: {e}"
        )
        sys.exit(1)

    # 4.5: .env Validation on Startup
    missing_meta = []
    if not settings.meta_phone_number_id:
        missing_meta.append("META_PHONE_NUMBER_ID")
    if not getattr(settings, "meta_access_token", None):
        missing_meta.append("META_ACCESS_TOKEN")
    if not settings.meta_webhook_verify_token:
        missing_meta.append("META_WEBHOOK_VERIFY_TOKEN")
    if missing_meta:
        logger.warning(f"⚠️  Missing CRITICAL Meta credentials in .env: {', '.join(missing_meta)}")

    # HIGH-02 fix: Loudly flag when META_APP_SECRET is unset.
    # Without it, meta_waba_adapter.verify_webhook_signature() always returns True,
    # meaning ANY request to POST /webhooks/whatsapp is accepted without HMAC validation.
    # Combined with CRIT-01 (now fixed), this was a complete authentication bypass.
    if settings.messaging_provider == "meta" and not settings.meta_app_secret:
        logger.critical(
            "❌ SECURITY: META_APP_SECRET is not set in .env. "
            "Webhook HMAC signature validation is DISABLED — anyone can send fake "
            "WhatsApp messages to your bot. Set META_APP_SECRET immediately!"
        )

    # TC-019 — warn if OWNER_PHONE not configured
    if not settings.owner_phone:
        logger.warning(
            "⚠️  OWNER_PHONE is not set in .env — "
            "WhatsApp owner commands (ADD, REMOVE, BROADCAST, SCHEDULE, STATUS, "
            "HELP, and CSV import) are DISABLED. "
            "All WhatsApp messages will be routed to the RAG bot."
        )
    else:
        logger.info(f"✅ Owner phone configured: {settings.owner_phone}")

# ─── Health Check ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health():
    # 4.4 Enhanced /health Check
    from core.database import engine
    from core.redis_client import get_redis
    from services.knowledge_service import get_chroma_client

    db_status = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    redis_status = "ok"
    try:
        r = get_redis()
        await r.ping()
    except Exception:
        redis_status = "error"

    chroma_status = "ok"
    try:
        client = get_chroma_client()
        client.heartbeat()
    except Exception:
        chroma_status = "error"

    return {
        "status": "ok" if db_status == "ok" and redis_status == "ok" and chroma_status == "ok" else "degraded",
        "db": db_status,
        "redis": redis_status,
        "chroma": chroma_status,
        "version": "2.0.0",
        "env": settings.app_env
    }

