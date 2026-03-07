import time
import logging
import uuid
from fastapi import Request

logger = logging.getLogger("twinai.access")


async def logging_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        f"{request.method} {request.url.path} → {response.status_code} "
        f"[{duration_ms}ms] req_id={request_id}"
    )
    response.headers["X-Request-ID"] = request_id
    return response
