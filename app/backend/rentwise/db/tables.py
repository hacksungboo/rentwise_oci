"""DB 스키마 (SQLAlchemy Core, ORM 미사용).

운영 Oracle Free / 로컬·테스트 SQLite 공통. 시각은 UTC 기준 TIMESTAMP(API에서 Asia/Seoul 오프셋 부여),
배열·객체는 CLOB(JSON 문자열), ID는 VARCHAR2(64). Oracle 예약어(start, text, order, user 등)는 컬럼명으로 쓰지 않는다.
명세 §4.1 엔티티 중 메인 시연 동선에 필요한 것부터 구현. ExecutionEvent·AiUsage 는 다음 단계.
"""
from __future__ import annotations

from sqlalchemy.dialects import oracle
from sqlalchemy import (
    Boolean, Numeric, Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table, Text, UniqueConstraint,
)

metadata = MetaData()
ID = lambda: String(64)  # noqa: E731
# Oracle 의 기본 DateTime 매핑은 초 단위 DATE 라서 TIMESTAMP 로 지정
TS = lambda: DateTime(timezone=False).with_variant(oracle.TIMESTAMP(), "oracle")  # noqa: E731  UTC 기준

schema_version = Table(
    "rw_schema_version", metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", TS(), nullable=False),
    Column("note", String(200)),
)

workspace_state = Table(
    "rw_workspace_state", metadata,
    Column("id", ID(), primary_key=True),
    Column("state_revision", Integer, nullable=False),
    Column("current_plan_id", ID()),
    Column("dataset_version", String(64), nullable=False),
)

locations = Table(
    "rw_locations", metadata,
    Column("id", ID(), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("kind", String(20), nullable=False),
    Column("address", String(400)),
    Column("lat", Float),
    Column("lon", Float),
)

customers = Table(
    "rw_customers", metadata,
    Column("id", ID(), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("location_id", ID(), ForeignKey("rw_locations.id"), nullable=False),
    Column("preferred_employee_id", ID()),
    Column("visit_windows_json", Text, nullable=False),
)

items = Table(
    "rw_items", metadata,
    Column("id", ID(), primary_key=True),
    Column("category", String(40), nullable=False),
    Column("model_name", String(200), nullable=False),
    Column("service_minutes_json", Text, nullable=False),
    Column("prep_minutes", Integer, nullable=False),
    Column("direct_transfer_allowed", Boolean, nullable=False),
)

assets = Table(
    "rw_assets", metadata,
    Column("id", ID(), primary_key=True),
    Column("item_id", ID(), ForeignKey("rw_items.id"), nullable=False),
    Column("physical_state", String(30), nullable=False),
    Column("location_id", ID(), ForeignKey("rw_locations.id")),
    Column("custody_employee_id", ID()),
    Column("last_event_at", TS()),
    Column("revision", Integer, nullable=False),
)

rentals = Table(
    "rw_rentals", metadata,
    Column("id", ID(), primary_key=True),
    Column("asset_id", ID(), ForeignKey("rw_assets.id"), nullable=False),
    Column("customer_id", ID(), ForeignKey("rw_customers.id"), nullable=False),
    Column("actual_start", TS()),
    Column("actual_end", TS()),
    Column("expected_return_at", TS()),
    Column("status", String(20), nullable=False),
)

reservations = Table(
    "rw_reservations", metadata,
    Column("id", ID(), primary_key=True),
    Column("asset_id", ID(), ForeignKey("rw_assets.id"), nullable=False),
    Column("rental_id", ID()),
    Column("start_at", TS(), nullable=False),
    Column("end_at", TS()),
    Column("release_job_id", ID()),
    Column("plan_id", ID()),
    Column("status", String(20), nullable=False),
    Column("review_required", Boolean, nullable=False, default=False),
)

employees = Table(
    "rw_employees", metadata,
    Column("id", ID(), primary_key=True),
    Column("name", String(100), nullable=False),
    Column("skills_json", Text, nullable=False),
    Column("active", Boolean, nullable=False),
)

shifts = Table(
    "rw_shifts", metadata,
    Column("id", ID(), primary_key=True),
    Column("employee_id", ID(), ForeignKey("rw_employees.id"), nullable=False),
    Column("start_at", TS(), nullable=False),
    Column("end_at", TS(), nullable=False),
    Column("start_location_id", ID(), nullable=False),
    Column("end_location_id", ID(), nullable=False),
    Column("break_windows_json", Text, nullable=False),
)

travel_times = Table(
    "rw_travel_times", metadata,
    Column("from_id", ID(), primary_key=True),
    Column("to_id", ID(), primary_key=True),
    Column("minutes", Integer, nullable=False),
    Column("source", String(40), nullable=False),
    Column("version", String(40), nullable=False),
)

requests = Table(
    "rw_requests", metadata,
    Column("id", ID(), primary_key=True),
    Column("external_key", String(128), unique=True),
    Column("source_customer_id", ID(), ForeignKey("rw_customers.id")),
    Column("received_at", TS(), nullable=False),
    Column("request_text", Text, nullable=False),
    Column("status", String(20), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("created_by", String(64)),
)

interpretations = Table(
    "rw_interpretations", metadata,
    Column("id", ID(), primary_key=True),
    Column("request_id", ID(), ForeignKey("rw_requests.id"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("origin", String(10), nullable=False),  # AI / MOCK / HUMAN
    Column("model_id", String(100)),
    Column("schema_version", String(40), nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("call_json", Text),
    Column("acknowledged_json", Text),
    Column("reviewed_by", String(64)),
    Column("reviewed_at", TS()),
    Column("created_at", TS(), nullable=False),
    UniqueConstraint("request_id", "revision", name="uq_interp_rev"),
)

jobs = Table(
    "rw_jobs", metadata,
    Column("id", ID(), primary_key=True),
    Column("request_id", ID()),
    Column("kind", String(20), nullable=False),
    Column("operation", String(20), nullable=False),
    Column("asset_ids_json", Text, nullable=False),
    Column("item_id", ID()),
    Column("quantity", Integer, nullable=False),
    Column("from_id", ID()),
    Column("to_id", ID()),
    Column("window_start", TS()),
    Column("window_end", TS()),
    Column("due_at", TS()),
    Column("rental_end_at", TS()),
    Column("priority", String(20), nullable=False),
    Column("status", String(20), nullable=False),
    Column("revision", Integer, nullable=False),
)

dependencies = Table(
    "rw_dependencies", metadata,
    Column("id", ID(), primary_key=True),
    Column("predecessor_job_id", ID(), nullable=False),
    Column("successor_job_id", ID(), nullable=False),
    Column("minimum_gap_minutes", Integer, nullable=False),
    Column("reason", String(60)),
)

plans = Table(
    "rw_plans", metadata,
    Column("id", ID(), primary_key=True),
    Column("revision", Integer, nullable=False),
    Column("base_plan_id", ID()),
    Column("base_state_revision", Integer, nullable=False),
    Column("request_id", ID()),
    Column("interpretation_revision", Integer),
    Column("status", String(20), nullable=False),
    Column("solver_status", String(30)),
    Column("solver_version", String(60)),
    Column("engine_mode", String(10)),
    Column("policy_version", String(40)),
    Column("travel_version", String(40)),
    Column("input_hash", String(80)),
    Column("result_json", Text),
    Column("operations_json", Text),
    Column("created_at", TS(), nullable=False),
    Column("confirmed_by", String(64)),
    Column("confirmed_at", TS()),
)

plan_items = Table(
    "rw_plan_items", metadata,
    Column("id", ID(), primary_key=True),
    Column("plan_id", ID(), ForeignKey("rw_plans.id"), nullable=False),
    Column("job_id", ID(), nullable=False),
    Column("employee_id", ID()),
    Column("asset_ids_json", Text, nullable=False),
    Column("start_at", TS(), nullable=False),
    Column("end_at", TS(), nullable=False),
    Column("segments_json", Text, nullable=False),
    Column("reason_codes_json", Text, nullable=False),
)

idempotency = Table(
    "rw_idempotency", metadata,
    Column("scope", String(200), primary_key=True),
    Column("idem_key", String(128), primary_key=True),
    Column("payload_hash", String(80), nullable=False),
    Column("status_code", Integer, nullable=False),
    Column("response_json", Text, nullable=False),
    Column("created_at", TS(), nullable=False),
)

audit_log = Table(
    "rw_audit_log", metadata,
    Column("id", ID(), primary_key=True),
    Column("actor", String(64), nullable=False),
    Column("action", String(60), nullable=False),
    Column("entity_id", ID()),
    Column("old_revision", Integer),
    Column("new_revision", Integer),
    Column("occurred_at", TS(), nullable=False),
    Column("trace_id", String(64)),
)

# AI 비용 장부 (시연 초기화로 지우지 않음). 원문·연락처·키는 저장하지 않는다.
ai_budget = Table(
    "rw_ai_budget", metadata,
    Column("id", String(20), primary_key=True),          # "AI" 한 행: 잠금·한도
    Column("limit_usd", Numeric(12, 6), nullable=False),
    Column("updated_at", TS(), nullable=False),
)

ai_ledger = Table(
    "rw_ai_ledger", metadata,
    Column("id", ID(), primary_key=True),                # reservation_id
    Column("attempt_key", String(200), nullable=False, unique=True),
    Column("status", String(20), nullable=False),        # RESERVED / SETTLED / UNKNOWN
    Column("reserved_usd", Numeric(12, 6), nullable=False),
    Column("settled_usd", Numeric(12, 6)),
    Column("input_tokens", Integer),
    Column("cached_input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("price_version", String(60)),
    Column("reason", String(60)),
    Column("created_at", TS(), nullable=False),
    Column("updated_at", TS(), nullable=False),
)

# AI 해석 호출 기록 (성공·실패 모두). 요청 처리가 롤백돼도 남도록 별도 트랜잭션으로 쓴다.
ai_calls = Table(
    "rw_ai_calls", metadata,
    Column("id", ID(), primary_key=True),
    Column("request_id", ID()),
    Column("engine_mode", String(10), nullable=False),
    Column("model_id", String(100)),
    Column("prompt_version", String(60)),
    Column("status", String(10), nullable=False),        # OK / ERROR
    Column("error_code", String(60)),
    Column("attempts", Integer),
    Column("input_tokens", Integer),
    Column("cached_input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("latency_ms", Integer),
    Column("provider_call_id", String(120)),
    Column("created_at", TS(), nullable=False),
)

SCHEMA_VERSION = 1
