"""Opt-in CREATE DELIVERY for B v1. IDs and approval belong to B.

Planning and confirmation preparation are pure. B persists all returned writes
under its existing lock/revision/idempotency guards; no public DTO is extended.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import itertools
import json
from math import ceil
import re
from time import monotonic

from rentwise.contracts import types as c
from rentwise.contracts.v2.schema import ContractError, timestamp
from . import v1, execution

VERSION = 'rental-new-delivery-b-v1-2'
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}')


@dataclass
class DeliveryConfirmation:
    validation: c.ValidationResult
    job_creates: list[dict] = field(default_factory=list)
    rental_creates: list[dict] = field(default_factory=list)
    dependency_creates: list[dict] = field(default_factory=list)
    job_updates: dict[str, dict] = field(default_factory=dict)
    reservation_changes: list[c.ReservationChange] = field(default_factory=list)


class DeliveryError(ValueError):
    def __init__(self, code, status='NEEDS_REVIEW'):
        super().__init__(code)
        self.code, self.status = code, status


def _context(snapshot, operations, request_id):
    ix, travel, wh = v1.inspect(snapshot)
    ops = [o if isinstance(o, c.NormalizedOperation) else c.NormalizedOperation.model_validate(o) for o in operations]
    if len(ops) != 1 or ops[0].operation != 'CREATE' or ops[0].kind != 'DELIVERY':
        raise DeliveryError('DELIVERY_SCOPE_UNSUPPORTED')
    op = ops[0].model_dump(exclude_unset=True)
    allowed = set(c.Operation.model_fields) - {'evidence'} | {'allocation', 'return_policy', 'from_id', 'to_id'}
    if set(op) - allowed or op.get('target_job_id') is not None:
        raise DeliveryError('DELIVERY_FIELDS_UNSUPPORTED')
    if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
        raise DeliveryError('DELIVERY_REQUEST_ID_REQUIRED', 'DATA_MISSING')
    allocation = op.get('allocation')
    names = {'job_id', 'rental_id', 'reservation_id', 'dependency_id'}
    if not isinstance(allocation, dict) or set(allocation) != names or any(
            not isinstance(v, str) or not _ID.fullmatch(v) for v in allocation.values()):
        raise DeliveryError('DELIVERY_ALLOCATION_REQUIRED', 'DATA_MISSING')
    existing = {r['id'] for table in v1.TABLES[:-1] for r in snapshot[table]}
    existing.update(p['plan_id'] for p in snapshot['plan_items'])
    if len(set(allocation.values())) != 4 or set(allocation.values()) & existing:
        raise DeliveryError('DELIVERY_ID_COLLISION', 'DATA_MISSING')
    old = {p['job_id']: p for p in snapshot['plan_items']}
    if len(old) != len(snapshot['plan_items']) or set(old) != {j['id'] for j in snapshot['jobs'] if j['status'] != 'CANCELLED'}:
        raise DeliveryError('PLAN_BASE_INVALID', 'DATA_MISSING')
    if op.get('item_id') not in ix['items'] or op.get('destination_customer_id') not in ix['customers']:
        raise DeliveryError('DELIVERY_ITEM_CUSTOMER_REQUIRED', 'DATA_MISSING')
    customer = ix['customers'][op['destination_customer_id']]
    if ix['locations'][customer['location_id']]['kind'] != 'CUSTOMER' or op.get('source_customer_id') not in (None, customer['id']):
        raise DeliveryError('DELIVERY_CUSTOMER_MISMATCH')
    if op.get('from_id') not in (None, wh) or op.get('to_id') not in (None, customer['location_id']):
        raise DeliveryError('DELIVERY_ROUTE_UNSUPPORTED')
    if type(op.get('quantity')) is not int or op['quantity'] != 1:
        raise DeliveryError('DELIVERY_SINGLE_ASSET_REQUIRED')
    if not isinstance(op.get('asset_ids'), list) or len(op['asset_ids']) > 1:
        raise DeliveryError('DELIVERY_ASSET_INVALID')
    if any(a not in ix['assets'] or ix['assets'][a]['item_id'] != op['item_id'] for a in op['asset_ids']):
        raise DeliveryError('DELIVERY_ASSET_INVALID')
    if op.get('priority_hint') not in ('NORMAL', 'URGENT', 'UNKNOWN'):
        raise DeliveryError('DELIVERY_PRIORITY_REQUIRED')
    if any(op.get(k) is None for k in ('window_start', 'window_end', 'due_at')):
        raise DeliveryError('UNCONFIRMED_FIELDS')
    if not timestamp(op['window_start']) < timestamp(op['window_end']) <= timestamp(op['due_at']):
        raise DeliveryError('DELIVERY_WINDOW_INVALID')
    if op.get('return_policy') not in ('FIXED', 'OPEN_ENDED') or 'rental_end_at' not in op:
        raise DeliveryError('DELIVERY_RETURN_POLICY_REQUIRED')
    if (op['return_policy'] == 'FIXED') != (op['rental_end_at'] is not None):
        raise DeliveryError('DELIVERY_RETURN_POLICY_MISMATCH')
    if op['rental_end_at'] is not None:
        timestamp(op['rental_end_at'])
    return dict(ix=ix, travel=travel, wh=wh, op=op, allocation=allocation, old=old,
        customer=customer, request_id=request_id)


def _row(ctx, start, employee, aid):
    wh, site = ctx['wh'], ctx['customer']['location_id']
    end = start + timedelta(minutes=ctx['ix']['items'][ctx['op']['item_id']]['service_minutes_by_kind']['DELIVERY'])
    departure = start - timedelta(minutes=ctx['travel'][wh, site])
    returned = end + timedelta(minutes=ctx['travel'][site, wh])
    return dict(id=None, plan_id=None, job_id=ctx['allocation']['job_id'], employee_id=employee,
        asset_ids=[aid], start_at=departure.isoformat(), end_at=returned.isoformat(),
        segments=[dict(kind=kind, from_id=a, to_id=b, start_at=x.isoformat(), end_at=y.isoformat())
            for kind, a, b, x, y in [('TRAVEL', wh, site, departure, start),
                ('SERVICE', site, site, start, end), ('TRAVEL', site, wh, end, returned)]], reason_codes=[])


def _preparation(ctx, aid, departure):
    asset = ctx['ix']['assets'][aid]
    if asset['physical_state'] == 'READY_WAREHOUSE' and asset['location_id'] == ctx['wh']:
        return None
    if asset['physical_state'] not in ('AT_CUSTOMER', 'PREP_REQUIRED'):
        raise DeliveryError('DELIVERY_ASSET_NOT_AVAILABLE')
    preps = [j for j in ctx['ix']['jobs'].values() if j['kind'] == 'PREP' and j['asset_ids'] == [aid]
        and j['item_id'] == ctx['op']['item_id'] and j['quantity'] == 1 and j['status'] not in v1.FROZEN | {'CANCELLED'}
        and j['id'] in ctx['old'] and any(r['status'] == 'ACTIVE' and r['asset_id'] == aid
            and r['release_job_id'] == j['id'] for r in ctx['ix']['reservations'].values())]
    if len(preps) != 1 or timestamp(ctx['old'][preps[0]['id']]['end_at']) > timestamp(departure):
        raise DeliveryError('DELIVERY_PREPARATION_REQUIRED')
    prep = preps[0]
    if asset['physical_state'] == 'AT_CUSTOMER':
        returns = [d for d in ctx['ix']['dependencies'].values() if d['successor_job_id'] == prep['id']
            and d['reason'] == 'RETURN_TO_PREP']
        pick = ctx['ix']['jobs'].get(returns[0]['predecessor_job_id']) if len(returns) == 1 else None
        if not pick or pick['kind'] != 'PICKUP' or pick['asset_ids'] != [aid] or pick['id'] not in ctx['old']:
            raise DeliveryError('DELIVERY_RETURN_BINDING_REQUIRED')
    return dict(id=ctx['allocation']['dependency_id'], predecessor_job_id=prep['id'],
        successor_job_id=ctx['allocation']['job_id'], minimum_gap_minutes=0, reason='ASSET_REUSE')


def _projection(snapshot, ctx, rows, input_hash, as_of):
    if not isinstance(input_hash, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', input_hash):
        raise DeliveryError('INVALID_INPUT_HASH', 'DATA_MISSING')
    jid = ctx['allocation']['job_id']
    by_job = {p['job_id']: p for p in rows}
    if len(by_job) != len(rows) or set(by_job) != set(ctx['old']) | {jid}:
        raise DeliveryError('PLAN_COVERAGE_INVALID', 'DATA_MISSING')
    row, op = by_job[jid], ctx['op']
    if len(row['asset_ids']) != 1 or row['asset_ids'][0] not in ctx['ix']['assets']:
        raise DeliveryError('DELIVERY_ASSET_INVALID')
    aid = row['asset_ids'][0]
    if ctx['ix']['assets'][aid]['item_id'] != op['item_id'] or op['asset_ids'] and op['asset_ids'] != [aid]:
        raise DeliveryError('DELIVERY_ASSET_INVALID')
    services = [s for s in row['segments'] if s['kind'] == 'SERVICE']
    if len(services) != 1 or v1.signature(row) != v1.signature(_row(ctx, timestamp(services[0]['start_at']), row['employee_id'], aid)):
        raise DeliveryError('DELIVERY_SEGMENTS_CHANGED')
    if timestamp(row['start_at']) < timestamp(as_of):
        raise DeliveryError('DELIVERY_DEPARTURE_PASSED')
    if op['rental_end_at'] is not None and timestamp(op['rental_end_at']) < timestamp(services[0]['end_at']):
        raise DeliveryError('DELIVERY_RENTAL_END_BEFORE_HANDOVER')
    dep = _preparation(ctx, aid, row['start_at'])
    job = dict(id=jid, request_id=ctx['request_id'], kind='DELIVERY', operation='CREATE', asset_ids=[aid],
        item_id=op['item_id'], quantity=1, from_id=ctx['wh'], to_id=ctx['customer']['location_id'],
        window_start=op['window_start'], window_end=op['window_end'], due_at=op['due_at'],
        rental_end_at=op['rental_end_at'], priority='URGENT' if op['priority_hint'] == 'URGENT' else 'NORMAL', status='ASSIGNED', revision=1)
    rental = dict(id=ctx['allocation']['rental_id'], asset_id=aid, customer_id=ctx['customer']['id'],
        actual_start=None, actual_end=None, expected_return_at=op['rental_end_at'], status='PLANNED')
    booking = dict(id=ctx['allocation']['reservation_id'], asset_id=aid, rental_id=rental['id'],
        start_at=row['start_at'], end_at=None, release_job_id=None, plan_id=None, status='ACTIVE', review_required=False)
    changes = [c.ReservationChange(action='CREATE', old_id=None, reservation=booking)]
    updates = {}
    for old_jid, old in ctx['old'].items():
        p = by_job[old_jid]
        if v1.signature(p, employee=False) != v1.signature(old, employee=False):
            raise DeliveryError('EXISTING_PROMISE_CHANGED')
        if p['employee_id'] != old['employee_id']:
            updates[old_jid] = {'asset_ids': list(p['asset_ids'])}
    if len(updates) > 3:
        raise DeliveryError('DELIVERY_OVERRIDE_LIMIT')
    view = deepcopy(snapshot)
    view['jobs'].append(deepcopy(job))
    view['rentals'].append(deepcopy(rental))
    view['reservations'].append(deepcopy(booking))
    if dep:
        view['dependencies'].append(deepcopy(dep))
    return view, job, rental, dep, changes, updates


def _change_key(changes):
    result = []
    for change in changes:
        d = c.ReservationChange.model_validate(change).model_dump()
        if d['reservation']:
            for key in ('start_at', 'end_at'):
                if d['reservation'].get(key) is not None:
                    d['reservation'][key] = timestamp(d['reservation'][key]).isoformat()
        result.append(json.dumps(d, sort_keys=True, separators=(',', ':')))
    return sorted(result)


def rejected(code, status='INVALID'):
    return DeliveryConfirmation(c.ValidationResult(status=status, violations=[c.Violation(code=code)], missing_fields=[]))


def prepare_confirmation(snapshot, operations, candidate_items, reservation_changes, *, request_id, input_hash, as_of) -> DeliveryConfirmation:
    """Recompute exact creates under B's lock. Failure contains no writes."""
    try:
        ctx = _context(snapshot, operations, request_id)
        rows = [c.PlanItem.model_validate(p).model_dump() for p in candidate_items]
        view, job, rental, dep, changes, updates = _projection(snapshot, ctx, rows, input_hash, as_of)
        if _change_key(reservation_changes) != _change_key(changes):
            raise DeliveryError('RESERVATION_DELTA_MISMATCH')
        vr = v1.validate(view, rows, new_jobs={job['id']}, as_of=as_of)
        if vr.status != 'VALID':
            return DeliveryConfirmation(vr)
        return DeliveryConfirmation(vr, [job], [rental], [dep] if dep else [], updates, changes)
    except DeliveryError as exc:
        return rejected(exc.code, 'DATA_MISSING' if exc.status == 'DATA_MISSING' else 'INVALID')
    except (ContractError, KeyError, TypeError, ValueError):
        return rejected('DELIVERY_DATA_MISSING', 'DATA_MISSING')


def solve(inp: c.SolverInput, as_of: str) -> c.SolverResult:
    started, examined, limited = monotonic(), 0, False
    affected = set()

    def result(status, rows=(), changes=(), edges=(), objective=(), code=None, violations=()):
        return c.SolverResult(status=status, candidate_items=[c.PlanItem(**r) for r in rows],
            reservation_changes=list(changes), affected_job_ids=sorted(affected), impact_edges=list(edges),
            violations=list(violations), unresolved=[c.Unresolved(job_id=None, code=code,
                details={'message': _MESSAGES.get(code, '신규 납품 조건·장비·직원 정보를 확인해 주세요.')})] if code else [],
            objective=list(objective), search_stats=c.SearchStats(elapsed_ms=max(0, int((monotonic()-started)*1000)),
                candidates_examined=examined, limit_reached=limited), input_hash=inp.input_hash, solver_version=VERSION)
    try:
        if inp.bundle_version != c.BUNDLE_VERSION:
            raise DeliveryError('INVALID_BUNDLE', 'DATA_MISSING')
        body = inp.model_dump(exclude={'schema_version', 'bundle_version', 'input_hash'})
        expected = 'sha256:' + hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if expected != inp.input_hash:
            raise DeliveryError('INVALID_INPUT_HASH', 'DATA_MISSING')
        if not 1 <= inp.max_candidates <= 1000 or not 1 <= inp.max_search_ms <= 2000:
            raise DeliveryError('INVALID_SEARCH_LIMIT', 'DATA_MISSING')
        if not timedelta(0) < timestamp(inp.horizon_end)-timestamp(inp.horizon_start) <= timedelta(days=7):
            raise DeliveryError('INVALID_HORIZON', 'DATA_MISSING')
        ctx = _context(inp.snapshot, inp.operations, inp.request_id)
        if v1.validate(inp.snapshot, inp.snapshot['plan_items']).status == 'DATA_MISSING':
            raise DeliveryError('PLAN_BASE_INVALID', 'DATA_MISSING')
        if {r['version'] for r in inp.snapshot['travel_times']} != {inp.travel_version}:
            raise DeliveryError('TRAVEL_VERSION_MISMATCH', 'DATA_MISSING')
        if {p['plan_id'] for p in inp.snapshot['plan_items']} != {inp.base_plan_id}:
            raise DeliveryError('STALE_PLAN')
        stale = execution.stale_jobs(inp.snapshot, as_of)
        if stale:
            return result('NEEDS_REVIEW', code='EXECUTION_STATUS_REQUIRED',
                violations=[c.Violation(code='EXECUTION_STATUS_REQUIRED', job_ids=[jid]) for jid in stale])
        op, jid = ctx['op'], ctx['allocation']['job_id']
        affected = {jid}
        base, overrides = deepcopy(ctx['old']), {}
        for o in inp.overrides:
            key = o.get('job_id')
            if set(o) != {'job_id', 'employee_id'} or key in overrides or key not in set(base) | {jid} \
                    or o['employee_id'] not in ctx['ix']['employees']:
                raise DeliveryError('DELIVERY_OVERRIDE_UNSUPPORTED')
            if key != jid and (ctx['ix']['jobs'][key]['kind'] == 'PREP' or ctx['ix']['jobs'][key]['status'] in v1.FROZEN | {'CANCELLED'}):
                raise DeliveryError('DELIVERY_OVERRIDE_UNSUPPORTED')
            overrides[key] = o['employee_id']
            if key != jid:
                base[key]['employee_id'] = o['employee_id']
            affected.add(key)
        if len(overrides) > 3:
            raise DeliveryError('DELIVERY_OVERRIDE_LIMIT')
        employees = sorted(e['id'] for e in ctx['ix']['employees'].values() if e['active']
            and {'task_kind': 'DELIVERY', 'item_category': ctx['ix']['items'][op['item_id']]['category']} in e['skills']
            and (jid not in overrides or overrides[jid] == e['id']))
        assets = op['asset_ids'] or sorted(a['id'] for a in ctx['ix']['assets'].values() if a['item_id'] == op['item_id']
            and a['physical_state'] in ('READY_WAREHOUSE', 'AT_CUSTOMER', 'PREP_REQUIRED'))
        if not employees or not assets:
            return result('NO_SOLUTION_FOUND', code='NO_DELIVERY_CANDIDATE')
        wh, site = ctx['wh'], ctx['customer']['location_id']
        duration = timedelta(minutes=ctx['ix']['items'][op['item_id']]['service_minutes_by_kind']['DELIVERY'])
        outbound, inbound = (timedelta(minutes=ctx['travel'][a, b]) for a, b in ((wh, site), (site, wh)))
        lo, hi = timestamp(op['window_start']), timestamp(op['window_end'])-duration
        earliest = max(lo, timestamp(as_of)+outbound, timestamp(inp.horizon_start)+outbound)
        start = lo if hi == lo else datetime.fromtimestamp(ceil(earliest.timestamp()/300)*300, tz=earliest.tzinfo)
        best, best_key, last = None, None, []
        while start <= hi:
            if start >= earliest and start+duration+inbound <= timestamp(inp.horizon_end):
                for aid, employee in itertools.product(assets, employees):
                    if examined >= inp.max_candidates or (monotonic()-started)*1000 >= inp.max_search_ms:
                        limited = True
                        break
                    examined += 1
                    selected = deepcopy(base)
                    selected[jid] = _row(ctx, start, employee, aid)
                    rows = [selected[k] for k in sorted(selected)]
                    try:
                        view, job, rental, dep, changes, updates = _projection(inp.snapshot, ctx, rows, inp.input_hash, as_of)
                    except DeliveryError:
                        continue
                    vr = v1.validate(view, rows, new_jobs={jid}, as_of=as_of)
                    if vr.status != 'VALID':
                        last = vr.violations
                        continue
                    preferred = ctx['customer']['preferred_employee_id']
                    key = (int(preferred is not None and employee != preferred), int(dep is not None), len(updates),
                        int((outbound+inbound).total_seconds()/60), start, aid, employee)
                    if best_key is None or key < best_key:
                        best_key, best = key, (deepcopy(rows), changes, dep)
            if limited:
                break
            start += timedelta(minutes=5)
        if best is None:
            return result('NO_SOLUTION_FOUND', code='SEARCH_LIMIT' if limited else 'NO_DELIVERY_CANDIDATE', violations=last)
        rows, changes, dep = best
        edges = []
        for row in rows:
            row.update(id=None, plan_id=None)
            if row['job_id'] == jid:
                row['reason_codes'] = ['PREPARATION_DEPENDENCY'] if dep else ['READY_DELIVERY']
                if best_key[0]:
                    row['reason_codes'].append('PREFERRED_EMPLOYEE_CONFLICT')
        if dep:
            new = next(p for p in rows if p['job_id'] == jid)
            edges = [c.ImpactEdge(from_job_id=dep['predecessor_job_id'], to_job_id=jid,
                reason='PREPARATION_DEPENDENCY', old_time=None, new_time=new['segments'][1]['start_at'])]
        return result('FEASIBLE', rows, changes, edges, best_key[:4])
    except DeliveryError as exc:
        return result(exc.status, code=exc.code)
    except (ContractError, KeyError, TypeError, ValueError):
        return result('DATA_MISSING', code='DELIVERY_DATA_MISSING')


_MESSAGES = {
    'EXECUTION_STATUS_REQUIRED': '예정 시작 시각이 지난 작업의 시작·완료 상태를 먼저 갱신해 주세요.',
    'DELIVERY_ALLOCATION_REQUIRED': '서버에서 신규 작업·대여·예약·준비 의존 ID를 발급해야 합니다.',
    'DELIVERY_RETURN_POLICY_REQUIRED': '대여 종료일 또는 반납 미정 정책을 사람이 확인해야 합니다.',
    'NO_DELIVERY_CANDIDATE': '기존 약속·예약과 충돌하지 않는 납품 직원·장비 조합을 찾지 못했습니다.',
    'SEARCH_LIMIT': '제한된 탐색 안에서 납품안을 찾지 못했습니다. 불가능하다는 뜻은 아닙니다.',
}
