from typing import Any
from fastapi.responses import JSONResponse
import uuid


def success_response(data: Any = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": True,
            "data": data,
            "error": None,
            "request_id": str(uuid.uuid4()),
        },
    )


def error_response(message: str, status_code: int = 400, detail: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "error": {"message": message, "detail": detail},
            "request_id": str(uuid.uuid4()),
        },
    )
