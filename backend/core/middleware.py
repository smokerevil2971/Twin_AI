import time
import logging
import uuid
import contextvars
from fastapi import Request

logger = logging.getLogger("twinai.access")

request_id_var = contextvars.ContextVar("request_id", default="-")

class RequestIDFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_var.get()
        return True

async def logging_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    token = request_id_var.set(request_id)
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        f"{request.method} {request.url.path} → {response.status_code} "
        f"[{duration_ms}ms]"
    )
    response.headers["X-Request-ID"] = request_id
    request_id_var.reset(token)
    return response
