from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from rentwise.api.errors import ApiError, api_error_handler, envelope, new_trace_id, trace_id_var, \
    unhandled_handler, validation_handler
from rentwise.api.routes import router
from rentwise.config import settings
from rentwise.db.database import ensure_seeded, init_schema, wait_for_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("rentwise")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.db_wait_seconds:
        wait_for_db(settings.db_wait_seconds)
    init_schema()
    if settings.auto_seed and ensure_seeded():
        log.info("빈 DB에 seed 적재: %s", settings.seed_path)
    from rentwise.services.ai_ledger import sync_limit
    sync_limit()
    if settings.engine_mode == "real":
        log.info("ai: model=%s key=%s budget_usd=%s", settings.openai_model,
                 "set" if os.environ.get("OPENAI_API_KEY", "").strip() else "MISSING", settings.ai_budget_usd)
    log.info("engine_mode=%s db=%s", settings.engine_mode, settings.database_url.split("@")[-1])
    yield


app = FastAPI(title="rentwise API", version="0.1.0", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_handler)
app.add_exception_handler(Exception, unhandled_handler)
app.include_router(router)


@app.middleware("http")
async def trace_and_origin(request: Request, call_next):
    trace_id_var.set(request.headers.get("X-Trace-Id") or new_trace_id())
    # 변경 요청은 같은 출처만 허용 (쿠키 세션 + SameSite=Lax 보완)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
            if urlparse(origin).netloc != host and origin not in settings.allowed_origins:
                return JSONResponse(status_code=403, content=envelope("BAD_ORIGIN", "허용되지 않은 출처입니다."))
    resp = await call_next(request)
    resp.headers["X-Trace-Id"] = trace_id_var.get()
    return resp
