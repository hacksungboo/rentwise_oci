from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None,
                 retryable: bool = False):
        self.status, self.code, self.message = status, code, message
        self.details, self.retryable = details or {}, retryable


def envelope(code: str, message: str, details: dict | None = None, retryable: bool = False) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}, "retryable": retryable},
            "trace_id": trace_id_var.get()}


async def api_error_handler(_: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content=envelope(exc.code, exc.message, exc.details, exc.retryable))


async def validation_handler(_: Request, exc: RequestValidationError):
    errs = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()][:20]
    return JSONResponse(status_code=422, content=envelope("VALIDATION_ERROR", "입력 형식이 올바르지 않습니다.",
                                                          {"errors": errs}))


async def unhandled_handler(_: Request, exc: Exception):
    import logging
    logging.getLogger("rentwise").exception("unhandled: %s", exc)
    return JSONResponse(status_code=500, content=envelope("INTERNAL_ERROR", "서버 오류가 발생했습니다.",
                                                          retryable=True))


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]
