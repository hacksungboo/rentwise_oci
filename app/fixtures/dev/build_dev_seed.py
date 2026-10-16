"""임시 개발 seed 생성기 (B 작성, C가 정식 seed로 교체 예정).

명세 §8.2 회수 지연 사례가 그대로 성립하도록 만든 합성 데이터다.
실행: python app/fixtures/dev/build_dev_seed.py  →  app/fixtures/v1/seed.json
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
DAY0 = datetime(2026, 10, 16, tzinfo=KST)
OUT = Path(__file__).resolve().parents[1] / "v1" / "seed.json"


def at(day: int, hh: int, mm: int = 0) -> datetime:
    return DAY0 + timedelta(days=day, hours=hh, minutes=mm)


def iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


# ---------------------------------------------------------------- 장소·거래처
LOCATIONS = [
    ("L-W", "성수 중앙창고", "WAREHOUSE", "서울 성동구 성수이로 77", 37.5446, 127.0557),
    ("L-H", "한빛상사", "CUSTOMER", "서울 중구 세종대로 110", 37.5663, 126.9779),
    ("L-S", "새봄디자인", "CUSTOMER", "서울 마포구 양화로 45", 37.5563, 126.9236),
    ("L-D", "다온회계법인", "CUSTOMER", "서울 강남구 테헤란로 152", 37.5004, 127.0365),
    ("L-M", "미래교육센터", "CUSTOMER", "서울 송파구 올림픽로 300", 37.5133, 127.1028),
    ("L-B", "바른법무사무소", "CUSTOMER", "서울 서초구 서초대로 219", 37.4920, 127.0076),
    ("L-J", "정우건축사무소", "CUSTOMER", "서울 용산구 한강대로 92", 37.5298, 126.9648),
]
CUSTOMERS = [  # id, name, location, preferred employee
    ("C-H", "한빛상사", "L-H", "E1"),
    ("C-S", "새봄디자인", "L-S", "E1"),
    ("C-D", "다온회계법인", "L-D", "E2"),
    ("C-M", "미래교육센터", "L-M", "E2"),
    ("C-B", "바른법무사무소", "L-B", "E3"),
    ("C-J", "정우건축사무소", "L-J", "E3"),
]

# 방향별 이동시간(분). 창고↔한빛·새봄 20분은 명세 §8.2 산술 그대로.
BASE = {
    ("L-W", "L-H"): 20, ("L-W", "L-S"): 20, ("L-W", "L-D"): 20, ("L-W", "L-M"): 25,
    ("L-W", "L-B"): 20, ("L-W", "L-J"): 20, ("L-H", "L-S"): 25, ("L-H", "L-D"): 30,
    ("L-H", "L-M"): 35, ("L-H", "L-B"): 30, ("L-H", "L-J"): 15, ("L-S", "L-D"): 35,
    ("L-S", "L-M"): 45, ("L-S", "L-B"): 35, ("L-S", "L-J"): 25, ("L-D", "L-M"): 20,
    ("L-D", "L-B"): 15, ("L-D", "L-J"): 25, ("L-M", "L-B"): 25, ("L-M", "L-J"): 35,
    ("L-B", "L-J"): 20,
}
# 역방향은 교통 차이를 가정해 일부 +5분 (대칭 가정 금지)
ASYM = {("L-D", "L-W"), ("L-M", "L-W"), ("L-J", "L-H"), ("L-M", "L-D")}


def travel_rows():
    rows = []
    ids = [l[0] for l in LOCATIONS]
    for a in ids:
        for b in ids:
            if a == b:
                continue
            m = BASE.get((a, b)) or BASE[(b, a)]
            if (a, b) in ASYM:
                m += 5
            rows.append({"from_id": a, "to_id": b, "minutes": m,
                         "source": "SYNTHETIC_FIXED", "version": "travel-v1"})
    return rows


TRAVEL = {(r["from_id"], r["to_id"]): r["minutes"] for r in travel_rows()}

ITEMS = [
    {"id": "PR-A", "category": "PRINTER", "model_name": "복합기 DEMO-A",
     "service_minutes_by_kind": {"DELIVERY": 15, "PICKUP": 10, "AS": 30, "TRANSFER": 10},
     "prep_minutes": 30, "direct_transfer_allowed": True},
    {"id": "NB-A", "category": "LAPTOP", "model_name": "노트북 DEMO-14",
     "service_minutes_by_kind": {"DELIVERY": 10, "PICKUP": 10, "AS": 20, "TRANSFER": 10},
     "prep_minutes": 20, "direct_transfer_allowed": True},
    {"id": "WP-A", "category": "WATER_PURIFIER", "model_name": "정수기 DEMO-W",
     "service_minutes_by_kind": {"DELIVERY": 30, "PICKUP": 20, "AS": 40, "TRANSFER": 20},
     "prep_minutes": 40, "direct_transfer_allowed": False},
]

# id, item, state, location
ASSETS = [
    ("P01", "PR-A", "AT_CUSTOMER", "L-H"), ("P02", "PR-A", "READY_WAREHOUSE", "L-W"),
    ("P03", "PR-A", "AT_CUSTOMER", "L-D"), ("P04", "PR-A", "READY_WAREHOUSE", "L-W"),
    ("N01", "NB-A", "AT_CUSTOMER", "L-M"), ("N02", "NB-A", "READY_WAREHOUSE", "L-W"),
    ("N03", "NB-A", "READY_WAREHOUSE", "L-W"), ("N04", "NB-A", "AT_CUSTOMER", "L-J"),
    ("W01", "WP-A", "AT_CUSTOMER", "L-B"), ("W02", "WP-A", "AT_CUSTOMER", "L-S"),
    ("W03", "WP-A", "READY_WAREHOUSE", "L-W"), ("W04", "WP-A", "REPAIR", "L-W"),
]

EMPLOYEES = [
    {"id": "E1", "name": "김현우", "active": True},
    {"id": "E2", "name": "이서연", "active": True},
    {"id": "E3", "name": "박준호", "active": True},
]
ALL_SKILLS = [{"task_kind": k, "item_category": c}
              for k in ("DELIVERY", "PICKUP", "AS", "TRANSFER")
              for c in ("PRINTER", "LAPTOP", "WATER_PURIFIER")]
BREAKS = {"E1": (13, 0, 14, 0), "E2": (12, 30, 13, 30), "E3": (13, 0, 14, 0)}

# ---------------------------------------------------------------- 기존 업무 12건 (+ 내부 PREP)
# id, kind, asset, item, from, to, employee, day, window(hh,mm,hh,mm), due(day,hh,mm), rental_end
JOBS = [
    ("J-PICK1", "PICKUP", "P01", "PR-A", "L-H", "L-W", "E1", 0, (10, 0, 10, 30), (0, 12, 0)),
    ("J-DEL1", "DELIVERY", "P01", "PR-A", "L-W", "L-S", "E1", 0, (12, 0, 12, 15), (0, 12, 15)),
    ("J-AS1", "AS", "W01", "WP-A", "L-B", "L-B", "E3", 0, (10, 0, 11, 0), (0, 11, 0)),
    ("J-DEL2", "DELIVERY", "N02", "NB-A", "L-W", "L-D", "E2", 0, (11, 0, 11, 30), (0, 11, 30)),
    ("J-PICK2", "PICKUP", "N04", "NB-A", "L-J", "L-W", "E3", 0, (15, 30, 16, 0), (0, 17, 0)),
    ("J-DEL3", "DELIVERY", "W03", "WP-A", "L-W", "L-M", "E2", 1, (10, 0, 11, 0), (1, 11, 0)),
    ("J-AS2", "AS", "P03", "PR-A", "L-D", "L-D", "E1", 1, (14, 0, 15, 0), (1, 15, 0)),
    ("J-TR1", "TRANSFER", "N01", "NB-A", "L-M", "L-H", "E3", 2, (11, 0, 12, 0), (2, 12, 0)),
    ("J-PICK3", "PICKUP", "W02", "WP-A", "L-S", "L-W", "E1", 3, (10, 0, 11, 0), (3, 12, 0)),
    ("J-DEL4", "DELIVERY", "P04", "PR-A", "L-W", "L-J", "E2", 3, (14, 0, 14, 30), (3, 14, 30)),
    ("J-AS3", "AS", "W01", "WP-A", "L-B", "L-B", "E3", 4, (15, 0, 16, 0), (4, 16, 0)),
    ("J-PICK4", "PICKUP", "P03", "PR-A", "L-D", "L-W", "E2", 5, (10, 0, 11, 0), (5, 12, 0)),
]
ITEM_BY_ID = {i["id"]: i for i in ITEMS}


def build():
    plan_items, jobs, deps = [], [], []
    for (jid, kind, asset, item, frm, to, emp, day, win, due) in JOBS:
        svc = ITEM_BY_ID[item]["service_minutes_by_kind"][kind]
        w0 = at(day, win[0], win[1])
        w1 = at(day, win[2], win[3])
        # 직원은 창고에서 출발해 현장 → (회수/이동이면 목적지) → 창고 복귀
        site = frm if kind in ("PICKUP", "TRANSFER", "AS") else to
        depart = w0 - timedelta(minutes=TRAVEL[("L-W", site)])
        segs = [{"kind": "TRAVEL", "from_id": "L-W", "to_id": site,
                 "start_at": iso(depart), "end_at": iso(w0)}]
        s_end = w0 + timedelta(minutes=svc)
        segs.append({"kind": "SERVICE", "from_id": site, "to_id": site,
                     "start_at": iso(w0), "end_at": iso(s_end)})
        cur, t = site, s_end
        if kind == "TRANSFER":
            arr = t + timedelta(minutes=TRAVEL[(site, to)])
            segs.append({"kind": "TRAVEL", "from_id": site, "to_id": to,
                         "start_at": iso(t), "end_at": iso(arr)})
            done = arr + timedelta(minutes=svc)
            segs.append({"kind": "SERVICE", "from_id": to, "to_id": to,
                         "start_at": iso(arr), "end_at": iso(done)})
            cur, t = to, done
        back = t + timedelta(minutes=TRAVEL[(cur, "L-W")])
        segs.append({"kind": "TRAVEL", "from_id": cur, "to_id": "L-W",
                     "start_at": iso(t), "end_at": iso(back)})
        jobs.append({
            "id": jid, "request_id": None, "kind": kind, "operation": "CREATE",
            "asset_ids": [asset], "item_id": item, "quantity": 1,
            "from_id": frm, "to_id": to, "window_start": iso(w0), "window_end": iso(w1),
            "due_at": iso(at(*due)), "rental_end_at": None, "priority": "HIGH" if kind == "AS" else "NORMAL",
            "status": "ASSIGNED", "revision": 1,
        })
        plan_items.append({
            "id": f"PI-{jid}", "plan_id": "PL-007", "job_id": jid, "employee_id": emp,
            "asset_ids": [asset], "start_at": iso(depart), "end_at": iso(back),
            "segments": segs, "reason_codes": [],
        })
        if kind == "PICKUP":  # 회수 후 창고 준비 PREP
            prep_id = jid.replace("PICK", "PREP")
            prep_min = ITEM_BY_ID[item]["prep_minutes"]
            p_end = back + timedelta(minutes=prep_min)
            jobs.append({
                "id": prep_id, "request_id": None, "kind": "PREP", "operation": "CREATE",
                "asset_ids": [asset], "item_id": item, "quantity": 1, "from_id": "L-W", "to_id": "L-W",
                "window_start": iso(back), "window_end": iso(p_end), "due_at": iso(p_end),
                "rental_end_at": None, "priority": "NORMAL", "status": "ASSIGNED", "revision": 1,
            })
            plan_items.append({
                "id": f"PI-{prep_id}", "plan_id": "PL-007", "job_id": prep_id, "employee_id": None,
                "asset_ids": [asset], "start_at": iso(back), "end_at": iso(p_end),
                "segments": [{"kind": "PREP", "from_id": "L-W", "to_id": "L-W",
                              "start_at": iso(back), "end_at": iso(p_end)}],
                "reason_codes": [],
            })
            deps.append({"id": f"D-{jid}", "predecessor_job_id": jid, "successor_job_id": prep_id,
                         "minimum_gap_minutes": 0, "reason": "RETURN_TO_PREP"})
    # P01: 회수 → 준비 → 새봄 납품 (핵심 의존성)
    deps.append({"id": "D-PREP1-DEL1", "predecessor_job_id": "J-PREP1", "successor_job_id": "J-DEL1",
                 "minimum_gap_minutes": 0, "reason": "ASSET_REUSE"})
    return jobs, plan_items, deps


def main():
    jobs, plan_items, deps = build()
    pi = {p["job_id"]: p for p in plan_items}

    rentals = [
        {"id": "R-H", "asset_id": "P01", "customer_id": "C-H", "actual_start": iso(at(-1, 12)),
         "actual_end": None, "expected_return_at": iso(at(0, 10, 10)), "status": "ACTIVE"},
        {"id": "R-S2", "asset_id": "P01", "customer_id": "C-S", "actual_start": None,
         "actual_end": None, "expected_return_at": None, "status": "PLANNED"},
        {"id": "R-D", "asset_id": "P03", "customer_id": "C-D", "actual_start": iso(at(-10, 10)),
         "actual_end": None, "expected_return_at": iso(at(5, 10)), "status": "ACTIVE"},
        {"id": "R-M", "asset_id": "N01", "customer_id": "C-M", "actual_start": iso(at(-5, 10)),
         "actual_end": None, "expected_return_at": iso(at(2, 11)), "status": "ACTIVE"},
        {"id": "R-J", "asset_id": "N04", "customer_id": "C-J", "actual_start": iso(at(-7, 10)),
         "actual_end": None, "expected_return_at": iso(at(0, 15, 30)), "status": "ACTIVE"},
        {"id": "R-B", "asset_id": "W01", "customer_id": "C-B", "actual_start": iso(at(-30, 10)),
         "actual_end": None, "expected_return_at": None, "status": "ACTIVE"},
        {"id": "R-S1", "asset_id": "W02", "customer_id": "C-S", "actual_start": iso(at(-20, 10)),
         "actual_end": None, "expected_return_at": iso(at(3, 10)), "status": "ACTIVE"},
    ]
    reservations = [
        # P01 한빛 대여: 회수→준비 완료(11:00)까지 점유
        {"id": "RS-H", "asset_id": "P01", "rental_id": "R-H", "start_at": iso(at(-1, 11)),
         "end_at": pi["J-PREP1"]["end_at"], "release_job_id": "J-PREP1"},
        # P01 새봄 대여: 출고 11:40부터 무기한
        {"id": "RS-S2", "asset_id": "P01", "rental_id": "R-S2", "start_at": pi["J-DEL1"]["start_at"],
         "end_at": None, "release_job_id": None},
        {"id": "RS-D", "asset_id": "P03", "rental_id": "R-D", "start_at": iso(at(-10, 9)),
         "end_at": pi["J-PREP4"]["end_at"], "release_job_id": "J-PREP4"},
        {"id": "RS-M", "asset_id": "N01", "rental_id": "R-M", "start_at": iso(at(-5, 9)),
         "end_at": None, "release_job_id": None},
        {"id": "RS-J", "asset_id": "N04", "rental_id": "R-J", "start_at": iso(at(-7, 9)),
         "end_at": pi["J-PREP2"]["end_at"], "release_job_id": "J-PREP2"},
        {"id": "RS-B", "asset_id": "W01", "rental_id": "R-B", "start_at": iso(at(-30, 9)),
         "end_at": None, "release_job_id": None},
        {"id": "RS-S1", "asset_id": "W02", "rental_id": "R-S1", "start_at": iso(at(-20, 9)),
         "end_at": pi["J-PREP3"]["end_at"], "release_job_id": "J-PREP3"},
        {"id": "RS-N02", "asset_id": "N02", "rental_id": None, "start_at": pi["J-DEL2"]["start_at"],
         "end_at": None, "release_job_id": None},
        {"id": "RS-W03", "asset_id": "W03", "rental_id": None, "start_at": pi["J-DEL3"]["start_at"],
         "end_at": None, "release_job_id": None},
        {"id": "RS-P04", "asset_id": "P04", "rental_id": None, "start_at": pi["J-DEL4"]["start_at"],
         "end_at": None, "release_job_id": None},
    ]
    for r in reservations:
        r.update({"plan_id": "PL-007", "status": "ACTIVE", "review_required": False})

    shifts = []
    for e in EMPLOYEES:
        b = BREAKS[e["id"]]
        for d in range(7):
            shifts.append({
                "id": f"SH-{e['id']}-{d}", "employee_id": e["id"],
                "start_at": iso(at(d, 9)), "end_at": iso(at(d, 18)),
                "start_location_id": "L-W", "end_location_id": "L-W",
                "break_windows": [{"start_at": iso(at(d, b[0], b[1])), "end_at": iso(at(d, b[2], b[3]))}],
            })
    for e in EMPLOYEES:
        e["skills"] = ALL_SKILLS

    seed = {
        "manifest": {
            "dataset_version": "rental-dev-v1",
            "source_type": "SYNTHETIC",
            "author": "B (임시 개발 seed, C가 정식 seed로 교체)",
            "reviewer": None,
            "clock_anchor": iso(at(0, 9)),
            "timezone": "Asia/Seoul",
            "assumptions": [
                "실제 업체 자료 아님. 주소·좌표는 시연용",
                "이동시간은 고정 합성 행렬(travel-v1), 실제 도로/교통 아님",
                "창고 준비는 직원 자원을 쓰지 않는 자동 경과 구간",
                "E2 휴식은 12:30~13:30으로 개별 설정 (명세 §8.2)",
            ],
        },
        "workspace": {"id": "DEMO", "state_revision": 7, "current_plan_id": "PL-007",
                      "dataset_version": "rental-dev-v1"},
        "locations": [dict(zip(("id", "name", "kind", "address", "lat", "lon"), l)) for l in LOCATIONS],
        "customers": [
            {"id": c[0], "name": c[1], "location_id": c[2], "preferred_employee_id": c[3],
             "visit_windows": [{"start_at": iso(at(d, 9)), "end_at": iso(at(d, 18))} for d in range(7)]}
            for c in CUSTOMERS
        ],
        "items": ITEMS,
        "assets": [
            {"id": a[0], "item_id": a[1], "physical_state": a[2], "location_id": a[3],
             "custody_employee_id": None, "last_event_at": iso(at(-1, 18)), "revision": 1}
            for a in ASSETS
        ],
        "rentals": rentals,
        "reservations": reservations,
        "employees": EMPLOYEES,
        "shifts": shifts,
        "travel_times": travel_rows(),
        "jobs": jobs,
        "dependencies": deps,
        "plan": {"id": "PL-007", "revision": 1, "base_plan_id": None, "base_state_revision": 6,
                 "request_id": None, "interpretation_revision": None, "status": "CONFIRMED",
                 "solver_version": "seed", "policy_version": "policy-v1", "travel_version": "travel-v1",
                 "input_hash": None, "created_at": iso(at(-1, 18)), "confirmed_by": "seed",
                 "confirmed_at": iso(at(-1, 18))},
        "plan_items": plan_items,
        "scenarios": [
            {"case_id": "DEV-DELAY-01", "source_customer_id": "C-H", "received_at": iso(at(0, 9)),
             "request_text": "안녕하세요 한빛상사입니다. 오늘 프린터 회수를 오후 2시로 미뤄 주실 수 있을까요?"},
            {"case_id": "DEV-DELIVERY-01", "source_customer_id": "C-B", "received_at": iso(at(0, 9)),
             "request_text": "바른법무사무소입니다. 내일 오전에 노트북 1대 추가로 납품 부탁드립니다."},
        ],
    }
    body = json.dumps(seed, ensure_ascii=False, indent=2, sort_keys=False)
    seed["manifest"]["sha256"] = hashlib.sha256(body.encode()).hexdigest()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(jobs)} jobs, {len(plan_items)} plan items)")


if __name__ == "__main__":
    main()
