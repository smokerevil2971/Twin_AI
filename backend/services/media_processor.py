"""
Media processor for WhatsApp attachments.
Handles: images (Gemini Vision), PDFs (PyMuPDF text), audio (Gemini audio).
Returns a text description/transcript to feed into the RAG pipeline.
"""
import base64
import logging
import httpx
import fitz  # PyMuPDF - already in requirements as pymupdf

import google.generativeai as genai

from core.config import settings

logger = logging.getLogger(__name__)

# MIME types we support
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
PDF_TYPES   = {"application/pdf"}
AUDIO_TYPES = {"audio/ogg", "audio/mpeg", "audio/mp4", "audio/amr", "audio/ogg; codecs=opus"}

UNSUPPORTED_MSG = (
    "I can only process images, PDF documents, and voice notes. "
    "Please send your query as text or one of these supported formats."
)

# Sentinel returned when Gemini quota is exceeded — webhook will reply directly
RATE_LIMITED_MSG = (
    "I'm temporarily busy processing requests. Please try again in a few minutes! ⏳"
)


async def download_media(url: str, account_sid: str, auth_token: str) -> bytes:
    """Download Twilio media with Basic auth. Follows redirects (Twilio CDN uses them for audio)."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, auth=(account_sid, auth_token))
        resp.raise_for_status()
        return resp.content


async def process_media(
    media_url: str,
    content_type: str,
    caption: str = "",
) -> str:
    """
    Download and process a WhatsApp media attachment.
    Returns a text string suitable for feeding into the RAG pipeline,
    or UNSUPPORTED_MSG if the type is not handled.

    Args:
        media_url: Twilio media URL (requires auth to download)
        content_type: MIME type of the media
        caption: Optional text caption sent alongside the media
    """
    mime_base = content_type.split(";")[0].strip().lower()

    if mime_base in IMAGE_TYPES:
        result = await _process_image(media_url, content_type, caption)
    elif mime_base in PDF_TYPES:
        result = await _process_pdf(media_url)
    elif mime_base in AUDIO_TYPES or "audio" in mime_base:
        result = await _process_audio(media_url, content_type)
    else:
        logger.warning(f"[MEDIA] Unsupported content type: {content_type}")
        return UNSUPPORTED_MSG

    return result


# ─── Handlers ────────────────────────────────────────────────────────────────

async def _process_image(media_url: str, content_type: str, caption: str) -> str:
    """Use Gemini Vision to describe the image in context of a solar business."""
    logger.info(f"[MEDIA] Processing image: {content_type}")
    try:
        raw = await download_media(
            media_url,
            settings.twilio_account_sid,
            settings.twilio_auth_token,
        )
        b64 = base64.b64encode(raw).decode()
        mime_base = content_type.split(";")[0].strip()

        genai.configure(api_key=settings.gemini_api_key)
        # Strip 'models/' prefix — genai SDK adds it automatically
        model_name = settings.llm_model.removeprefix("models/")
        model = genai.GenerativeModel(model_name)

        caption_hint = f' The client added this caption: "{caption}".' if caption else ""
        prompt = (
            "You are a solar energy product expert assistant. "
            "The client has sent an image via WhatsApp." + caption_hint + " "
            "Describe what you see in 1-2 sentences and extract any relevant question or context "
            "that would help you answer a question about solar products. "
            "If it's a solar panel, inverter, or installation, note the specifics. "
            "If it's a document (invoice, quote), summarize the key figures."
        )

        resp = model.generate_content([
            prompt,
            {"mime_type": mime_base, "data": b64},
        ])
        description = (resp.text or "").strip()
        logger.info(f"[MEDIA] Image described: {description[:80]}")

        # Combine description with caption for RAG
        if caption:
            return f"{caption}\n[Attached image: {description}]"
        return f"[Client sent an image: {description}]"

    except Exception as e:
        logger.error(f"[MEDIA] Image processing failed: {e}")
        return caption or "[Client sent an image but it could not be processed]"


async def _process_pdf(media_url: str) -> str:
    """Extract text from PDF using PyMuPDF."""
    logger.info("[MEDIA] Processing PDF document")
    try:
        raw = await download_media(
            media_url,
            settings.twilio_account_sid,
            settings.twilio_auth_token,
        )
        doc = fitz.open(stream=raw, filetype="pdf")
        pages_text = []
        for page in doc:
            pages_text.append(page.get_text())
        full_text = "\n".join(pages_text).strip()
        doc.close()

        if not full_text:
            return "[Client sent a PDF but it contained no readable text (may be a scanned image)]"

        # Trim to 3000 chars to avoid context overflow
        trimmed = full_text[:3000]
        if len(full_text) > 3000:
            trimmed += "\n[... document truncated ...]"

        logger.info(f"[MEDIA] PDF extracted {len(full_text)} chars")
        return f"[Client sent a PDF document with the following content:]\n{trimmed}"

    except Exception as e:
        logger.error(f"[MEDIA] PDF processing failed: {e}")
        return "[Client sent a PDF but it could not be read]"


async def _process_audio(media_url: str, content_type: str) -> str:
    """Transcribe voice note using Gemini audio understanding."""
    logger.info(f"[MEDIA] Processing audio: {content_type}")
    try:
        raw = await download_media(
            media_url,
            settings.twilio_account_sid,
            settings.twilio_auth_token,
        )
        logger.info(f"[MEDIA] Audio downloaded: {len(raw)} bytes")
        b64 = base64.b64encode(raw).decode()

        # Normalize MIME type — Gemini accepts audio/ogg
        mime_base = content_type.split(";")[0].strip()
        if "ogg" in mime_base:
            mime_base = "audio/ogg"
        elif "mpeg" in mime_base or "mp3" in mime_base:
            mime_base = "audio/mpeg"

        genai.configure(api_key=settings.gemini_api_key)
        # Strip 'models/' prefix — genai SDK adds it automatically
        model_name = settings.llm_model.removeprefix("models/")
        model = genai.GenerativeModel(model_name)

        resp = model.generate_content([
            "Please transcribe this voice note exactly as spoken. "
            "Output only the transcription text, nothing else.",
            {"mime_type": mime_base, "data": b64},
        ])
        transcript = (resp.text or "").strip()
        logger.info(f"[MEDIA] Voice transcribed: {transcript[:80]}")

        if not transcript:
            return "[Client sent a voice note but it could not be transcribed]"

        return transcript  # treat transcript as the message text directly

    except Exception as e:
        err_str = str(e)
        logger.error(f"[MEDIA] Audio processing failed: {err_str}")
        # Detect Gemini quota / rate limit errors specifically (avoid matching on '404 ...generateContent')
        is_rate_limit = (
            "429" in err_str
            or "quota exceeded" in err_str.lower()
            or "resource_exhausted" in err_str.lower()
            or "rate_limit_exceeded" in err_str.lower()
        )
        if is_rate_limit:
            logger.warning("[MEDIA] Gemini quota hit during audio processing")
            return RATE_LIMITED_MSG
        return "[Client sent a voice note but it could not be processed]"
