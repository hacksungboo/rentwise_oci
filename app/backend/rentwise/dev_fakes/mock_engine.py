"""개발용 mock EnginePort (B 소유, dev 전용).

A의 실제 해석·배정 엔진이 연결되기 전, 서비스 배포와 화면 연동을 시험하기 위한 대역이다.
- interpret: 키워드 기반 고정 응답. 회수 지연 시연 문장은 명세 §5.1 예시 그대로 반환
- solve: 회수 일정 변경(RESCHEDULE PICKUP)만 계산하고, 나머지는 NEEDS_REVIEW
- validate: 직원 시간 겹침만 검사하는 최소 검사기
- availability: 물리 상태 집계 + 예약 기반 가용 분리

ENGINE_MODE=real 로 바꾸면 rentwise.engine 의 A 구현이 주입된다. 함수 서명은 contracts.EnginePort 와 동일.
"""
from __future__ import annotations

import copy
import time
from collections import defaultdict
from typing import Any

from rentwise.contracts.types import (
    AvailabilityInput, AvailabilityResult, AvailabilityWindow, CallMetadata, ConditionalAsset,
    Evidence, ImpactEdge, InterpretationInput, InterpretationResult, Intent, NeedsConfirmation,
    Operation, PhysicalCount, PlanItem, ReservationChange, SearchStats, Segment, SolverInput,
    SolverResult, Unresolved, ValidationResult, Violation,
)
from rentwise.timeutil import iso, overlaps, parse, plus

KIND_WORDS = [("회수", "PICKUP"), ("수거", "PICKUP"), ("반납", "PICKUP"), ("납품", "DELIVERY"),
              ("배송", "DELIVERY"), ("설치", "DELIVERY"), ("고장", "AS"), ("A/S", "AS"), ("AS", "AS"),
              ("점검", "AS"), ("이동", "TRANSFER"), ("옮겨", "TRANSFER")]
ITEM_WORDS = [("프린터", "PR-A"), ("복합기", "PR-A"), ("노트북", "NB-A"), ("정수기", "WP-A")]


class MockEngine:
    mode = "mock"
    solver_version = "mock-solver-0.1"

    # ------------------------------------------------------------------ interpret
    def interpret(self, inp: InterpretationInput) -> InterpretationResult:
        t0 = time.monotonic()
        text = inp.text
        kind, kind_q = "DELIVERY", None
        for w, k in KIND_WORDS:
            if w in text:
                kind, kind_q = k, w
                break
        item_id, item_q = None, None
        for w, i in ITEM_WORDS:
            if w in text:
                item_id, item_q = i, w
                break
        evidence = []
        if kind_q:
            evidence.append(Evidence(path="kind", quote=kind_q))
        if item_q:
            evidence.append(Evidence(path="item_id", quote=item_q))

        day = parse(inp.received_at).astimezone(parse(inp.received_at).tzinfo).date().isoformat()
        is_delay_demo = kind == "PICKUP" and ("2시" in text or "14시" in text or "14:00" in text)
        confirms: list[NeedsConfirmation] = []
        if is_delay_demo:
            quote = next((q for q in ("오후 2시", "2시", "14시", "14:00") if q in text), "2시")
            evidence.append(Evidence(path="window_start", quote=quote))
            target = self._find_job(inp.existing_jobs, "PICKUP", inp.source_customer_id)
            op = Operation(
                operation="RESCHEDULE", kind="PICKUP", target_job_id=target, item_id=item_id or "PR-A",
                asset_ids=[], quantity=1, source_customer_id=inp.source_customer_id,
                destination_customer_id=None, window_start=f"{day}T14:00:00+09:00", window_end=None,
                due_at=None, rental_end_at=None, priority_hint="NORMAL", evidence=evidence,
            )
            confirms.append(NeedsConfirmation(
                path="operations.0.window_end", reason="MISSING",
                question="14:00 시작, 현장 회수 10분(14:10 종료)으로 확인합니까?"))
            confirms.append(NeedsConfirmation(
                path="operations.0.due_at", reason="MISSING",
                question="창고 입고 완료 기한을 확인해 주세요. 기존 기한 12:00은 새 회수 시각보다 이릅니다."))
            if target is None:
                confirms.append(NeedsConfirmation(path="operations.0.target_job_id", reason="AMBIGUOUS",
                                                  question="변경할 기존 회수 업무를 선택해 주세요."))
        else:
            op = Operation(
                operation="CREATE", kind=kind, target_job_id=None, item_id=item_id, asset_ids=[],
                quantity=1 if "1대" in text or "한 대" in text else None,
                source_customer_id=inp.source_customer_id if kind != "DELIVERY" else None,
                destination_customer_id=inp.source_customer_id if kind == "DELIVERY" else None,
                window_start=None, window_end=None, due_at=None, rental_end_at=None,
                priority_hint="URGENT" if "급" in text else "UNKNOWN", evidence=evidence,
            )
            confirms.append(NeedsConfirmation(path="operations.0.window_start", reason="MISSING",
                                              question="방문 시작 시각을 입력해 주세요."))
            if op.quantity is None:
                confirms.append(NeedsConfirmation(path="operations.0.quantity", reason="MISSING",
                                                  question="수량을 확인해 주세요."))
        intent = Intent(operations=[op], needs_confirmation=confirms)
        return InterpretationResult(
            status="OK", payload=intent, error=None,
            call=CallMetadata(origin="MOCK", model_id=None, prompt_version="mock-v1", provider_call_id=None,
                              attempts=1, usage=None, latency_ms=int((time.monotonic() - t0) * 1000)),
        )

    @staticmethod
    def _find_job(jobs: list[dict[str, Any]], kind: str, customer_id: str | None) -> str | None:
        for j in jobs:
            if j.get("kind") == kind and (customer_id is None or j.get("customer_id") == customer_id):
                return j["id"]
        return None

    # ------------------------------------------------------------------ availability
    def availability(self, inp: AvailabilityInput) -> AvailabilityResult:
        snap = inp.snapshot
        f0, f1 = parse(inp.from_at), parse(inp.to_at)
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for a in snap["assets"]:
            if a["physical_state"] != "RETIRED":
                counts[(a["item_id"], a["physical_state"])] += 1
        res_by_asset: dict[str, list[dict]] = defaultdict(list)
        for r in snap["reservations"]:
            if r["status"] == "ACTIVE":
                res_by_asset[r["asset_id"]].append(r)
        windows = []
        for item in snap["items"]:
            ready, cond, unavail = [], [], []
            for a in snap["assets"]:
                if a["item_id"] != item["id"] or a["physical_state"] == "RETIRED":
                    continue
                hits = [r for r in res_by_asset[a["id"]]
                        if overlaps(parse(r["start_at"]), parse(r["end_at"]), f0, f1)]
                if a["physical_state"] == "READY_WAREHOUSE" and not hits:
                    ready.append(a["id"])
                elif hits and all(r.get("end_at") and r.get("release_job_id") for r in hits) \
                        and a["physical_state"] not in ("REPAIR", "UNAVAILABLE"):
                    last = max(hits, key=lambda r: r["end_at"])
                    if parse(last["end_at"]) < f1:
                        cond.append(ConditionalAsset(asset_id=a["id"], expected_ready_at=iso(parse(last["end_at"])),
                                                     dependency_job_ids=[last["release_job_id"]]))
                    else:
                        unavail.append(a["id"])
                else:
                    unavail.append(a["id"])
            windows.append(AvailabilityWindow(item_id=item["id"], from_at=inp.from_at, to_at=inp.to_at,
                                              ready_asset_ids=ready, conditional_assets=cond,
                                              unavailable_asset_ids=unavail))
        return AvailabilityResult(
            status="OK", base_state_revision=inp.base_state_revision,
            physical_counts=[PhysicalCount(item_id=k[0], physical_state=k[1], count=v) for k, v in sorted(counts.items())],
            windows=windows, missing_fields=[],
        )

    # ------------------------------------------------------------------ solve
    def solve(self, inp: SolverInput) -> SolverResult:
        t0 = time.monotonic()
        snap = inp.snapshot
        base_items = [PlanItem(**{k: v for k, v in p.items() if k in PlanItem.model_fields})
                      for p in snap["plan_items"]]

        def result(status, items, changes=(), affected=(), edges=(), unresolved=()):
            return SolverResult(
                status=status, candidate_items=list(items), reservation_changes=list(changes),
                affected_job_ids=list(affected), impact_edges=list(edges), violations=[],
                unresolved=list(unresolved), objective=[0, 0, 0, 0, 0],
                search_stats=SearchStats(elapsed_ms=int((time.monotonic() - t0) * 1000),
                                         candidates_examined=1, limit_reached=False),
                input_hash=inp.input_hash, solver_version=self.solver_version,
            )

        op = inp.operations[0] if inp.operations else None
        if not op or op.kind != "PICKUP" or op.operation != "RESCHEDULE" or not op.target_job_id \
                or not op.window_start:
            return result("NEEDS_REVIEW", base_items, unresolved=[Unresolved(
                job_id=op.target_job_id if op else None, code="MOCK_ENGINE_UNSUPPORTED",
                details={"message": "실제 배정 엔진(A) 연동 전에는 '회수 일정 변경' 사례만 계산합니다."})])

        by_job = {p.job_id: p for p in base_items}
        jobs = {j["id"]: j for j in snap["jobs"]}
        pick = jobs[op.target_job_id]
        item = next(i for i in snap["items"] if i["id"] == pick["item_id"])
        travel = {(t["from_id"], t["to_id"]): t["minutes"] for t in snap["travel_times"]}
        site, wh = pick["from_id"], pick["to_id"]
        svc, prep_min = item["service_minutes_by_kind"]["PICKUP"], item["prep_minutes"]

        start = op.window_start
        depart = plus(start, -travel[(wh, site)])
        svc_end = plus(start, svc)
        back = plus(svc_end, travel[(site, wh)])
        prep_end = plus(back, prep_min)

        # 원래 담당자 → 휴식/기존 일정과 겹치면 다른 직원
        old = by_job[pick["id"]]
        employee, reasons = old.employee_id, ["RETURN_DELAY"]
        conflict = self._employee_conflict(snap, base_items, employee, depart, back, skip_job=pick["id"])
        if conflict:
            for e in snap["employees"]:
                if e["id"] != employee and not self._employee_conflict(snap, base_items, e["id"], depart, back,
                                                                         skip_job=pick["id"]):
                    reasons.append("PREFERRED_EMPLOYEE_CONFLICT")
                    employee = e["id"]
                    break
        items = {p.job_id: copy.deepcopy(p) for p in base_items}
        asset = pick["asset_ids"][0]
        items[pick["id"]] = PlanItem(
            id=None, job_id=pick["id"], employee_id=employee, asset_ids=[asset], start_at=depart, end_at=back,
            segments=[Segment(kind="TRAVEL", from_id=wh, to_id=site, start_at=depart, end_at=start),
                      Segment(kind="SERVICE", from_id=site, to_id=site, start_at=start, end_at=svc_end),
                      Segment(kind="TRAVEL", from_id=site, to_id=wh, start_at=svc_end, end_at=back)],
            reason_codes=reasons)
        prep_id = pick["id"].replace("PICK", "PREP")
        if prep_id in items:
            items[prep_id] = PlanItem(
                id=None, job_id=prep_id, employee_id=None, asset_ids=[asset], start_at=back, end_at=prep_end,
                segments=[Segment(kind="PREP", from_id=wh, to_id=wh, start_at=back, end_at=prep_end)],
                reason_codes=["RETURN_DELAY"])

        changes, edges, affected = [], [], [pick["id"], prep_id]
        edges.append(ImpactEdge(from_job_id=pick["id"], to_job_id=prep_id, reason="RETURN_DELAY",
                                old_time=by_job[prep_id].end_at if prep_id in by_job else None, new_time=prep_end))
        rs_old = next((r for r in snap["reservations"] if r["asset_id"] == asset and r.get("release_job_id") == prep_id
                       and r["status"] == "ACTIVE"), None)
        if rs_old:
            changes.append(ReservationChange(action="REPLACE", old_id=rs_old["id"],
                                             reservation={**rs_old, "id": f"{rs_old['id']}-v2", "end_at": prep_end}))

        # 같은 개체를 쓰는 후속 납품: 준비 완료가 출발보다 늦으면 같은 모델 대체품
        for dep in snap["dependencies"]:
            if dep["predecessor_job_id"] != prep_id:
                continue
            nxt = by_job.get(dep["successor_job_id"])
            if not nxt or not nxt.start_at or parse(prep_end) <= parse(nxt.start_at):
                continue
            sub = self._substitute(snap, item["id"], nxt.start_at, exclude={asset})
            affected.append(nxt.job_id)
            if sub:
                p = copy.deepcopy(nxt)
                p.asset_ids, p.reason_codes = [sub], ["SAME_MODEL_SUBSTITUTE", "PREPARATION_DEPENDENCY"]
                items[nxt.job_id] = p
                edges.append(ImpactEdge(from_job_id=prep_id, to_job_id=nxt.job_id, reason="SAME_MODEL_SUBSTITUTE",
                                        old_time=nxt.start_at, new_time=nxt.start_at))
                rs_next = next((r for r in snap["reservations"] if r["asset_id"] == asset
                                and r["start_at"] and parse(r["start_at"]) == parse(nxt.start_at)), None)
                if rs_next:
                    changes.append(ReservationChange(action="REPLACE", old_id=rs_next["id"], reservation={
                        **rs_next, "id": f"{rs_next['id']}-{sub}", "asset_id": sub}))
            else:
                return result("NEEDS_REVIEW", list(items.values()), changes, affected, edges, [Unresolved(
                    job_id=nxt.job_id, code="SUBSTITUTE_SHORTAGE",
                    details={"message": "같은 모델 대체 장비가 없습니다.", "item_id": item["id"]})])
        return result("FEASIBLE", list(items.values()), changes, affected, edges)

    @staticmethod
    def _employee_conflict(snap, items, employee_id, start, end, skip_job=None) -> bool:
        s, e = parse(start), parse(end)
        for sh in snap["shifts"]:
            if sh["employee_id"] != employee_id:
                continue
            if parse(sh["start_at"]) <= s < parse(sh["end_at"]):
                if e > parse(sh["end_at"]):
                    return True
                for b in sh.get("break_windows", []):
                    if overlaps(s, e, parse(b["start_at"]), parse(b["end_at"])):
                        return True
                break
        else:
            return True  # 근무 없음
        for p in items:
            if p.employee_id == employee_id and p.job_id != skip_job and overlaps(s, e, parse(p.start_at), parse(p.end_at)):
                return True
        return False

    @staticmethod
    def _substitute(snap, item_id, at_iso, exclude) -> str | None:
        t = parse(at_iso)
        busy = {r["asset_id"] for r in snap["reservations"] if r["status"] == "ACTIVE"
                and overlaps(parse(r["start_at"]), parse(r["end_at"]), t, None)}
        for a in sorted(snap["assets"], key=lambda a: a["id"]):
            if a["item_id"] == item_id and a["physical_state"] == "READY_WAREHOUSE" \
                    and a["id"] not in busy and a["id"] not in exclude:
                return a["id"]
        return None

    # ------------------------------------------------------------------ validate
    def validate(self, snapshot, complete_candidate_plan: list[PlanItem]) -> ValidationResult:
        violations = []
        by_emp: dict[str, list[PlanItem]] = defaultdict(list)
        for p in complete_candidate_plan:
            if p.employee_id:
                by_emp[p.employee_id].append(p)
        for emp, ps in by_emp.items():
            ps.sort(key=lambda p: parse(p.start_at))
            for a, b in zip(ps, ps[1:]):
                if parse(b.start_at) < parse(a.end_at):
                    violations.append(Violation(code="EMPLOYEE_OVERLAP", job_ids=[a.job_id, b.job_id],
                                                employee_ids=[emp]))
        if not complete_candidate_plan:
            return ValidationResult(status="DATA_MISSING", violations=[], missing_fields=["plan_items"])
        return ValidationResult(status="INVALID" if violations else "VALID", violations=violations, missing_fields=[])
