"""HTTP API /api/v1 (명세 §7). 메인 시연 동선 우선."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import insert, select, text

from rentwise.api.auth import User, current_user, login, logout, require_admin
from rentwise.api.errors import ApiError, trace_id_var
from rentwise.config import settings
from rentwise.db import tables as T
from rentwise.db.database import get_db_engine, load_seed
from rentwise.engine_registry import get_engine
from rentwise.services import operations as ops_svc
from rentwise.services.cloud import cloud_info
from rentwise.services import plans as plan_svc
from rentwise.services import requests as req_svc
from rentwise.services.plans import canonical_hash
from rentwise.timeutil import now

router = APIRouter(prefix="/api/v1")


def tx(fn: Callable):
    with get_db_engine().begin() as conn:
        return fn(conn)


def ro(fn: Callable):
    with get_db_engine().connect() as conn:
        return fn(conn)


def idempotent(scope: str, key: Optional[str], body: Any, fn: Callable):
    """같은 키+같은 body → 원래 응답, 같은 키+다른 body → 409. 키 없으면 그냥 실행."""
    if not key:
        return tx(fn)
    h = canonical_hash(body)

    def run(conn):
        row = conn.execute(select(T.idempotency).where((T.idempotency.c.scope == scope)
                                                       & (T.idempotency.c.idem_key == key))).first()
        if row:
            if row.payload_hash != h:
                raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "같은 Idempotency-Key로 다른 요청을 보냈습니다.")
            return json.loads(row.response_json)
        out = fn(conn)
        conn.execute(insert(T.idempotency).values(scope=scope, idem_key=key, payload_hash=h, status_code=200,
                                                  response_json=json.dumps(out, ensure_ascii=False, default=str),
                                                  created_at=now()))
        return out
    return tx(run)


# --------------------------------------------------------------------------- health
@router.get("/health/live")
def live():
    return {"status": "ok"}


@router.get("/health/ready")
def ready(response: Response):
    t0 = time.monotonic()
    try:
        def q(c):
            c.execute(text("SELECT 1 FROM dual" if c.dialect.name == "oracle" else "SELECT 1"))
            v = c.execute(select(T.schema_version.c.version)).scalar()
            return c.dialect.name, v
        dialect, ver = ro(q)
        return {"status": "ready", "db": dialect, "schema_version": ver,
                "latency_ms": int((time.monotonic() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        response.status_code = 503
        return {"status": "unavailable", "error": type(e).__name__}


@router.get("/version")
def version():
    def q(c):
        db = c.dialect.name
        banner = None
        if db == "oracle":
            banner = c.execute(text("SELECT banner_full FROM v$version")).scalar()
        return db, banner
    try:
        db, banner = ro(q)
    except Exception:  # noqa: BLE001
        db, banner = None, None
    c = cloud_info()
    return {"service": "rentwise-api", "build_sha": settings.build_sha, "image_tag": settings.image_tag,
            "engine_mode": get_engine().mode, "db": db, "db_banner": banner, "server": settings.server_label,
            "bundle_version": "rental.bundle.v1",
            "cloud": {k: c.get(k) for k in ("provider", "region", "display_name")}}


@router.get("/system")
def system(_: User = Depends(current_user)):
    """시연용 실행 환경 정보: OCI 메타데이터 + DB + 배포 버전"""
    def q(c):
        if c.dialect.name != "oracle":
            return {"dialect": c.dialect.name}
        row = c.execute(text("SELECT banner_full, sys_context('USERENV','CON_NAME'), "
                             "sys_context('USERENV','SERVER_HOST') FROM v$version")).first()
        return {"dialect": "oracle", "banner": row[0], "pdb": row[1], "server_host": row[2]}
    try:
        db = ro(q)
    except Exception as e:  # noqa: BLE001
        db = {"error": type(e).__name__}
    return {"cloud": cloud_info(), "db": db,
            "build": {"sha": settings.build_sha, "image_tag": settings.image_tag, "engine_mode": get_engine().mode,
                      "server_label": settings.server_label}}


# --------------------------------------------------------------------------- sessions
class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/sessions")
def post_session(body: LoginBody, response: Response):
    return {"user": login(body.username, body.password, response).public()}


@router.get("/sessions/current")
def get_session(user: User = Depends(current_user)):
    return {"user": user.public()}


@router.delete("/sessions/current")
def delete_session(response: Response):
    logout(response)
    return {"ok": True}


# --------------------------------------------------------------------------- 조회
@router.get("/operations")
def operations(date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), _: User = Depends(current_user)):
    return ro(lambda c: ops_svc.operations_view(c, date))


@router.get("/reference")
def reference(_: User = Depends(current_user)):
    return ro(ops_svc.reference_view)


@router.get("/assets/{asset_id}")
def asset(asset_id: str, _: User = Depends(current_user)):
    v = ro(lambda c: ops_svc.asset_view(c, asset_id))
    if v is None:
        raise ApiError(404, "NOT_FOUND", "장비를 찾을 수 없습니다.")
    return v


# --------------------------------------------------------------------------- 요청·해석
class RequestBody(BaseModel):
    source_customer_id: Optional[str] = None
    received_at: Optional[str] = None
    text: str = Field(max_length=2000)
    external_key: Optional[str] = None


@router.get("/requests")
def list_requests(_: User = Depends(current_user)):
    return {"items": ro(req_svc.list_requests)}


@router.post("/requests", status_code=201)
def create_request(body: RequestBody, user: User = Depends(require_admin),
                   idem: Optional[str] = Header(None, alias="Idempotency-Key")):
    received = body.received_at or ops_svc.clock_anchor()
    return idempotent(f"{user.username}:POST:/requests", idem, body.model_dump(),
                      lambda c: req_svc.create_request(c, body.source_customer_id, received, body.text,
                                                       body.external_key, user.username))


@router.get("/requests/{request_id}")
def get_request(request_id: str, _: User = Depends(current_user)):
    return ro(lambda c: req_svc.request_view(c, request_id))


class RevisionBody(BaseModel):
    expected_request_revision: int


@router.post("/requests/{request_id}/interpret")
def interpret(request_id: str, body: RevisionBody, _: User = Depends(require_admin)):
    return tx(lambda c: req_svc.interpret(c, request_id, body.expected_request_revision))


class InterpretationBody(BaseModel):
    expected_request_revision: int
    payload: dict
    acknowledged_paths: list[str] = []


@router.put("/requests/{request_id}/interpretation")
def put_interpretation(request_id: str, body: InterpretationBody, user: User = Depends(require_admin)):
    return tx(lambda c: req_svc.save_interpretation(c, request_id, body.expected_request_revision, body.payload,
                                                    body.acknowledged_paths, user.username))


# --------------------------------------------------------------------------- 계획
class PlanBody(BaseModel):
    request_id: str
    interpretation_revision: int
    base_state_revision: int
    overrides: list[dict] = []


@router.post("/plans", status_code=201)
def create_plan(body: PlanBody, user: User = Depends(require_admin)):
    return tx(lambda c: plan_svc.create_plan(c, body.request_id, body.interpretation_revision,
                                             body.base_state_revision, body.overrides, user.username))


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, _: User = Depends(current_user)):
    return ro(lambda c: plan_svc.plan_view(c, plan_id))


class ConfirmBody(BaseModel):
    expected_plan_revision: int
    base_state_revision: int


@router.post("/plans/{plan_id}/confirm")
def confirm(plan_id: str, body: ConfirmBody, user: User = Depends(require_admin),
            idem: Optional[str] = Header(None, alias="Idempotency-Key")):
    return idempotent(f"{user.username}:POST:/plans/{plan_id}/confirm", idem, body.model_dump(),
                      lambda c: plan_svc.confirm(c, plan_id, body.expected_plan_revision, body.base_state_revision,
                                                 user.username, trace_id_var.get()))


class HoldBody(BaseModel):
    expected_plan_revision: int
    reason: str = ""


@router.post("/plans/{plan_id}/hold")
def hold(plan_id: str, body: HoldBody, user: User = Depends(require_admin)):
    return tx(lambda c: plan_svc.hold(c, plan_id, body.expected_plan_revision, body.reason, user.username))


# --------------------------------------------------------------------------- 데모 초기화 (C 측정용)
@router.post("/admin/reset")
def reset(_: User = Depends(require_admin)):
    seed = json.loads(settings.seed_path.read_text(encoding="utf-8"))
    tx(lambda c: load_seed(c, seed))
    return {"ok": True, "dataset_version": seed["manifest"]["dataset_version"],
            "seed_sha256": seed["manifest"].get("sha256")}


@router.get("/admin/ai")
def ai_usage(_: User = Depends(require_admin)):
    """AI 해석 호출 기록·비용 (시연 증거용). 원문·키는 포함하지 않는다."""
    from rentwise.services.ai_ledger import summary
    return {"engine_mode": settings.engine_mode, "model_id": settings.openai_model, **summary()}
