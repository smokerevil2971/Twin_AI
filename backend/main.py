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
from core.middleware import logging_middleware
from routes.auth import router as auth_router
from routes.clients import router as clients_router
from routes.broadcasts import router as broadcasts_router
from routes.webhooks import router as webhooks_router
from routes.knowledge_base import router as knowledge_router

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.app_env == "development" else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Twin AI — Two-Bot System",
    version="2.0.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url=None,
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    return {"status": "ok", "version": "2.0.0", "env": settings.app_env}

