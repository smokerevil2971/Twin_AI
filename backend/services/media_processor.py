"""
Media processor for WhatsApp attachments — dual-provider (NIM or Gemini).
Handles: images (Vision), PDFs (PyMuPDF text), audio (transcription).
Returns a text description/transcript to feed into the RAG pipeline.

Provider switch: set LLM_PROVIDER=nim or LLM_PROVIDER=gemini in .env
- NIM  → microsoft/phi-4-multimodal-instruct (images + audio)
- Gemini → gemini-2.0-flash  (images + audio)
"""
import base64
import logging
import httpx
import fitz  # PyMuPDF

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
    Returns a text string suitable for feeding into the RAG pipeline.
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
    """Describe image using NIM phi-4-multimodal or Gemini Vision."""
    logger.info(f"[MEDIA] Processing image: {content_type} via {settings.llm_provider}")
    try:
        raw = await download_media(
            media_url,
            settings.twilio_account_sid,
            settings.twilio_auth_token,
        )
        b64 = base64.b64encode(raw).decode()
        mime_base = content_type.split(";")[0].strip()

        caption_hint = f' The client added this caption: "{caption}".' if caption else ""
        prompt = (
            "You are a solar energy product expert assistant. "
            "The client has sent an image via WhatsApp." + caption_hint + " "
            "Describe what you see in 1-2 sentences and extract any relevant question or context "
            "that would help you answer a question about solar products. "
            "If it's a solar panel, inverter, or installation, note the specifics. "
            "If it's a document (invoice, quote), summarize the key figures."
        )

        if settings.is_nim:
            description = _vision_nim(prompt, b64, mime_base)
        else:
            description = _vision_gemini(prompt, b64, mime_base)

        description = description.strip()
        logger.info(f"[MEDIA] Image described: {description[:80]}")

        if caption:
            return f"{caption}\n[Attached image: {description}]"
        return f"[Client sent an image: {description}]"

    except Exception as e:
        logger.error(f"[MEDIA] Image processing failed: {e}")
        return caption or "[Client sent an image but it could not be processed]"


def _vision_nim(prompt: str, b64: str, mime_type: str) -> str:
    """Image description via NIM phi-4-multimodal (OpenAI vision format)."""
    from openai import OpenAI
    client = OpenAI(base_url=settings.nim_base_url, api_key=settings.nim_multimodal_api_key)
    resp = client.chat.completions.create(
        model=settings.multimodal_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                },
            ],
        }],
        max_tokens=256,
        temperature=0.1,
    )
    return resp.choices[0].message.content or ""


def _vision_gemini(prompt: str, b64: str, mime_type: str) -> str:
    """Image description via Gemini Vision."""
    import google.generativeai as genai
    genai.configure(api_key=settings.gemini_api_key)
    model_name = settings.multimodal_model.removeprefix("models/")
    model = genai.GenerativeModel(model_name)
    resp = model.generate_content([
        prompt,
        {"mime_type": mime_type, "data": b64},
    ])
    return resp.text or ""


async def _process_pdf(media_url: str) -> str:
    """Extract text from PDF using PyMuPDF (provider-independent)."""
    logger.info("[MEDIA] Processing PDF document")
    try:
        raw = await download_media(
            media_url,
            settings.twilio_account_sid,
            settings.twilio_auth_token,
        )
        doc = fitz.open(stream=raw, filetype="pdf")
        pages_text = [page.get_text() for page in doc]
        full_text = "\n".join(pages_text).strip()
        doc.close()

        if not full_text:
            return "[Client sent a PDF but it contained no readable text (may be a scanned image)]"

        trimmed = full_text[:3000]
        if len(full_text) > 3000:
            trimmed += "\n[... document truncated ...]"

        logger.info(f"[MEDIA] PDF extracted {len(full_text)} chars")
        return f"[Client sent a PDF document with the following content:]\n{trimmed}"

    except Exception as e:
        logger.error(f"[MEDIA] PDF processing failed: {e}")
        return "[Client sent a PDF but it could not be read]"


async def _process_audio(media_url: str, content_type: str) -> str:
    """Transcribe voice note using NIM phi-4-multimodal or Gemini audio."""
    logger.info(f"[MEDIA] Processing audio: {content_type} via {settings.llm_provider}")
    try:
        raw = await download_media(
            media_url,
            settings.twilio_account_sid,
            settings.twilio_auth_token,
        )
        logger.info(f"[MEDIA] Audio downloaded: {len(raw)} bytes")
        b64 = base64.b64encode(raw).decode()

        # Normalize MIME type
        mime_base = content_type.split(";")[0].strip()
        if "ogg" in mime_base:
            mime_base = "audio/ogg"
        elif "mpeg" in mime_base or "mp3" in mime_base:
            mime_base = "audio/mpeg"

        if settings.is_nim:
            transcript = _audio_nim(b64, mime_base)
        else:
            transcript = _audio_gemini(b64, mime_base)

        transcript = transcript.strip()
        logger.info(f"[MEDIA] Voice transcribed: {transcript[:80]}")

        if not transcript:
            return "[Client sent a voice note but it could not be transcribed]"

        return transcript

    except Exception as e:
        err_str = str(e)
        logger.error(f"[MEDIA] Audio processing failed: {err_str}")
        is_rate_limit = (
            "429" in err_str
            or "quota exceeded" in err_str.lower()
            or "resource_exhausted" in err_str.lower()
            or "rate_limit_exceeded" in err_str.lower()
        )
        if is_rate_limit:
            logger.warning("[MEDIA] Provider quota hit during audio processing")
            return RATE_LIMITED_MSG
        return "[Client sent a voice note but it could not be processed]"


def _audio_nim(b64: str, mime_type: str) -> str:
    """Audio transcription via NIM phi-4-multimodal."""
    from openai import OpenAI
    client = OpenAI(base_url=settings.nim_base_url, api_key=settings.nim_multimodal_api_key)
    resp = client.chat.completions.create(
        model=settings.multimodal_model,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Please transcribe this voice note exactly as spoken. Output only the transcription text, nothing else.",
                },
                {
                    "type": "audio_url",
                    "audio_url": {"url": f"data:{mime_type};base64,{b64}"},
                },
            ],
        }],
        max_tokens=512,
        temperature=0.0,
    )
    return resp.choices[0].message.content or ""


def _audio_gemini(b64: str, mime_type: str) -> str:
    """Audio transcription via Gemini."""
    import google.generativeai as genai
    genai.configure(api_key=settings.gemini_api_key)
    model_name = settings.multimodal_model.removeprefix("models/")
    model = genai.GenerativeModel(model_name)
    resp = model.generate_content([
        "Please transcribe this voice note exactly as spoken. "
        "Output only the transcription text, nothing else.",
        {"mime_type": mime_type, "data": b64},
    ])
    return resp.text or ""
