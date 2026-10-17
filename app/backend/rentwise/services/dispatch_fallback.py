"""Operator-reviewed dispatch alternatives, never a real courier booking.

Internal employees are tried first. A calendar check distinguishes absent staff
from an invalid visit window. Every alternative still passes A's full validator.
"""
from copy import deepcopy
from datetime import timedelta
from time import monotonic

from sqlalchemy import insert, select

from rentwise.api.errors import ApiError
from rentwise.contracts.v2.normalize import normalize_operation
from rentwise.contracts.v2.serialization import solver_input_hash
from rentwise.db import tables as T
from rentwise.db.database import J
from rentwise.engine import quick, staff
from rentwise.services import v2_bridge
from rentwise.timeutil import KST, iso, parse, to_db

POLICY_VERSION = 'dispatch-fallback-v1'
MAX_STAGES = 14  # normal + quick + up to six future days (normal/quick)


def add_resources(snapshot, resources):
    snapshot = deepcopy(snapshot)
    for name in ('employees', 'shifts'):
        existing = {r['id']: r for r in snapshot[name]}
        for row in resources.get(name, []):
            if row['id'] in existing:
                if existing[row['id']] != row:
                    raise ApiError(409, 'QUICK_RESOURCE_CHANGED', '퀵 계획 자원 정보가 바뀌었습니다. 다시 계산해 주세요.')
            else:
                snapshot[name].append(deepcopy(row))
    return snapshot


def persist_resources(conn, resources):
    for e in resources.get('employees', []):
        if conn.execute(select(T.employees.c.id).where(T.employees.c.id == e['id'])).first() is None:
            conn.execute(insert(T.employees).values(id=e['id'], name=e['name'], active=e['active'], skills_json=J(e['skills'])))
    for s in resources.get('shifts', []):
        if conn.execute(select(T.shifts.c.id).where(T.shifts.c.id == s['id'])).first() is None:
            conn.execute(insert(T.shifts).values(id=s['id'], employee_id=s['employee_id'],
                start_at=to_db(s['start_at']), end_at=to_db(s['end_at']), start_location_id=s['start_location_id'],
                end_location_id=s['end_location_id'], break_windows_json=J(s['break_windows'])))


def _jobs(inp):
    jobs = {j['id']: j for j in inp['snapshot']['jobs']}
    jobs.update({o['job']['id']: o['job'] for o in inp['operations']})
    return jobs


def _quick_resources(snapshot, job):
    eid = quick.resource_id(job['id'])
    item = next(i for i in snapshot['items'] if i['id'] == job['item_id'])
    warehouse = next(l['id'] for l in snapshot['locations'] if l['kind'] == 'WAREHOUSE')
    day = parse(job['window_start']).astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    employee = dict(id=eid, name=f"퀵서비스 · 호출 필요 ({job['id']})", active=True,
                    skills=[dict(task_kind='DELIVERY', item_category=item['category'])])
    shift = dict(id=f"QS-{eid[3:]}-{day:%Y%m%d}", employee_id=eid,
                 start_at=iso(day), end_at=iso(day + timedelta(days=1)), start_location_id=warehouse,
                 end_location_id=warehouse, break_windows=[])
    return dict(employees=[employee], shifts=[shift])


def _can_fallback(result):
    return result['status'] in ('NO_SOLUTION_FOUND', 'PROVEN_INFEASIBLE')


def _staff_job(body, job):
    # Downstream customer promises remain fixed unless explicitly approved.
    if job['id'] not in body['approved_job_ids']:
        plan = next((p for p in body['snapshot']['plan_items'] if p['job_id'] == job['id']), None)
        service = next((s for s in plan['segments_json'] if s['kind'] == 'SERVICE'), None) if plan else None
        if service:
            return {**job, 'window_start': service['start_at'], 'window_end': service['end_at']}
    return job


def _next_pickup_inputs(inp, op):
    snapshot, old = inp['snapshot'], op['job']
    today = parse(snapshot['as_of']).astimezone(KST).date()
    if parse(old['window_start']).astimezone(KST).date() != today:
        return
    if staff.available(snapshot, old) is not False:
        return
    customer = next(c for c in snapshot['customers'] if c['location_id'] == old['from_id'])
    item = next(i for i in snapshot['items'] if i['id'] == old['item_id'])
    employees = {e['id'] for e in snapshot['employees'] if e['active'] and not quick.is_quick(e['id'])
                 and dict(task_kind='PICKUP', item_category=item['category']) in e['skills']}
    horizon = parse(inp['horizon_end'])
    prep_ids = [d['successor_job_id'] for d in snapshot['dependencies'] if d['predecessor_job_id'] == old['id']]
    preps = [j for j in snapshot['jobs'] if j['id'] in prep_ids and j['kind'] == 'PREP']
    if len(preps) != 1:
        return
    for days in range(1, 7):
        day = parse(snapshot['as_of']).astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days)
        if day >= horizon:
            break
        shifts = [s for s in snapshot['shifts'] if s['employee_id'] in employees
                  and parse(s['start_at']).astimezone(KST).date() == day.date()]
        if not shifts:
            continue
        due = min(max(parse(s['end_at']) for s in shifts), horizon)
        for window in sorted(customer['visit_windows'], key=lambda w: parse(w['start'])):
            lo, hi = max(parse(window['start']), day), min(parse(window['end']), day + timedelta(days=1), due)
            if hi <= lo:
                continue
            job = {**old, 'window_start': iso(lo), 'window_end': iso(hi), 'due_at': iso(due)}
            if staff.available(snapshot, job) is not True:
                continue
            prep = deepcopy(preps[0])
            delta = (day.date() - parse(prep['window_end']).astimezone(KST).date()).days
            prep['window_end'] = iso(min(parse(prep['window_end']) + timedelta(days=delta), horizon))
            prep['due_at'] = prep['window_end']
            trial = deepcopy(inp)
            trial['operations'] = [normalize_operation(snapshot, 'RESCHEDULE', old['id'], job,
                confirmed=True, rental_id=op['rental_id'], return_policy='NOT_APPLICABLE', prep_job=prep)]
            trial['approved_job_ids'] = sorted(set(trial['approved_job_ids']) | {prep['id']})
            yield trial, dict(kind='PICKUP_NEXT_WORKDAY', job_id=old['id'],
                old_window_start=old['window_start'], old_window_end=old['window_end'], old_due_at=old['due_at'],
                window_start=job['window_start'], window_end=job['window_end'], due_at=job['due_at'],
                notice='회수 날짜·방문 시간·완료 기한 변경을 확인한 뒤 확정해 주세요.')


def solve(inp):
    """Return v1 result, v2 candidate, effective input, review notices, used resources."""
    started = monotonic()
    stages = []

    def run(body):
        body['input_hash'] = solver_input_hash(body)
        result = v2_bridge.solve(body)
        stages.append(result['search_stats'])
        return result

    def finish(result, body, notices=(), resources=None):
        if result['status'] == 'FEASIBLE':
            for p in result['candidate_plan']['plan_items']:
                if quick.is_quick(p['employee_id']):
                    # A failed shift/return check is not necessarily an overlap.
                    p['reason_codes'] = [r for r in p['reason_codes'] if r != 'PREFERRED_EMPLOYEE_CONFLICT']
                    if 'QUICK_SERVICE_REQUIRED' not in p['reason_codes']:
                        p['reason_codes'].append('QUICK_SERVICE_REQUIRED')
                if any(n['kind'] == 'PICKUP_NEXT_WORKDAY' and n['job_id'] == p['job_id'] for n in notices):
                    p['reason_codes'].append('PICKUP_NEXT_WORKDAY')
            result['candidate_items'] = deepcopy(result['candidate_plan']['plan_items'])
        result['search_stats'] = dict(elapsed_ms=int((monotonic()-started)*1000),
            candidates_examined=sum(s['candidates_examined'] for s in stages),
            limit_reached=any(s['limit_reached'] for s in stages) or len(stages) >= MAX_STAGES)
        converted, candidate = v2_bridge.to_v1_result(inp['snapshot'], result)
        return converted, candidate, body, list(notices), resources or dict(employees=[], shifts=[])

    def try_quick(body, failed):
        if not _can_fallback(failed) or len(stages) >= MAX_STAGES:
            return None
        jobs = _jobs(body)
        targets = [jobs[j] for j in failed['affected_job_ids'] if jobs[j]['kind'] == 'DELIVERY'
                   and staff.available(body['snapshot'], _staff_job(body, jobs[j])) is False]
        if not targets:
            return None
        trial = deepcopy(body)
        resources, notices = dict(employees=[], shifts=[]), []
        for job in targets:
            added = _quick_resources(body['snapshot'], job)
            for name in resources:
                resources[name].extend(added[name])
            eid = quick.resource_id(job['id'])
            trial['overrides'].append(dict(job_id=job['id'], employee_id=eid))
            notices.append(dict(kind='QUICK', job_id=job['id'], employee_id=eid, status='CALL_REQUIRED',
                                notice='계획용 퀵 배정입니다. 실제 업체 호출·수락·요금 결제는 별도로 진행해야 합니다.'))
        trial['snapshot'] = add_resources(trial['snapshot'], resources)
        result = run(trial)
        return (result, trial, notices, resources) if result['status'] == 'FEASIBLE' else None

    original = deepcopy(inp)
    base = run(original)
    if base['status'] == 'FEASIBLE' or original['overrides'] or not _can_fallback(base):
        return finish(base, original)
    proposed = try_quick(original, base)
    if proposed:
        return finish(*proposed)
    if len(original['operations']) == 1 and original['operations'][0]['job']['kind'] == 'PICKUP':
        for trial, notice in _next_pickup_inputs(original, original['operations'][0]):
            if len(stages) >= MAX_STAGES:
                break
            result = run(trial)
            if result['status'] == 'FEASIBLE':
                return finish(result, trial, [notice])
            proposed = try_quick(trial, result)
            if proposed:
                result, trial, notices, resources = proposed
                return finish(result, trial, [notice, *notices], resources)
    return finish(base, original)
