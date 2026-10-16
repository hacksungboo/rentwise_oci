"""Opt-in B v1 pickup recovery and pure confirmation preparation.

No DB, network, hidden context or extended SolverResult. B must persist the
validated job/rental/dependency changes in its existing confirm transaction.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta
import hashlib
import itertools
import json
import re
from time import monotonic

from rentwise.contracts import types as c
from rentwise.contracts.v2.schema import ContractError, timestamp
from . import v1, execution

VERSION = 'rental-pickup-recovery-v1-2'


@dataclass
class ConfirmationChanges:
    validation: c.ValidationResult
    job_updates: dict[str, dict] = field(default_factory=dict)
    rental_updates: dict[str, dict] = field(default_factory=dict)
    dependency_deletions: list[str] = field(default_factory=list)
    reservation_changes: list[c.ReservationChange] = field(default_factory=list)


class RecoveryError(ValueError):
    def __init__(self, code, status='NEEDS_REVIEW'):
        super().__init__(code)
        self.code, self.status = code, status


def _one(rows, code):
    if len(rows) != 1:
        raise RecoveryError(code, 'DATA_MISSING')
    return rows[0]


def _operations(operations):
    return [op if isinstance(op, c.NormalizedOperation) else c.NormalizedOperation.model_validate(op) for op in operations]


def _context(snapshot, operations):
    ix, travel, warehouse = v1.inspect(snapshot)
    operations = _operations(operations)
    if len(operations) != 1 or operations[0].kind != 'PICKUP' or operations[0].operation != 'RESCHEDULE':
        raise RecoveryError('RECOVERY_SCOPE_UNSUPPORTED')
    op = operations[0]
    if op.target_job_id not in ix['jobs']:
        raise RecoveryError('RECOVERY_TARGET_REQUIRED')
    pick = ix['jobs'][op.target_job_id]
    if pick['kind'] != 'PICKUP' or pick['status'] in v1.FROZEN | {'CANCELLED'} or len(pick['asset_ids']) != 1 or pick['quantity'] != 1:
        raise RecoveryError('RECOVERY_TARGET_UNSUPPORTED')
    raw = op.model_dump(exclude_unset=True)
    allowed = set(c.Operation.model_fields) - {'evidence'} | {'from_id', 'to_id'}
    if set(raw) - allowed:
        raise RecoveryError('RECOVERY_FIELDS_UNSUPPORTED')
    for key in ('item_id', 'quantity', 'from_id', 'to_id', 'rental_end_at'):
        if raw.get(key) is not None and raw[key] != pick[key]:
            raise RecoveryError('RECOVERY_FIELDS_UNSUPPORTED')
    if raw.get('asset_ids') and raw['asset_ids'] != pick['asset_ids']:
        raise RecoveryError('RECOVERY_FIELDS_UNSUPPORTED')
    for key, loc in (('source_customer_id', pick['from_id']), ('destination_customer_id', pick['to_id'])):
        if raw.get(key) is not None and (raw[key] not in ix['customers'] or ix['customers'][raw[key]]['location_id'] != loc):
            raise RecoveryError('RECOVERY_CUSTOMER_MISMATCH')
    if any(getattr(op, key) is None for key in ('window_start', 'window_end', 'due_at')):
        raise RecoveryError('UNCONFIRMED_FIELDS')
    if not timestamp(op.window_start) < timestamp(op.window_end) <= timestamp(op.due_at):
        raise RecoveryError('RECOVERY_WINDOW_INVALID')
    old = {p['job_id']: p for p in snapshot['plan_items']}
    if len(old) != len(snapshot['plan_items']) or set(old) != {j['id'] for j in snapshot['jobs'] if j['status'] != 'CANCELLED'}:
        raise RecoveryError('PLAN_BASE_INVALID', 'DATA_MISSING')
    old_pick = old.get(pick['id'])
    if old_pick is None or timestamp(op.window_start) <= timestamp(_service(old_pick)['start_at']):
        raise RecoveryError('PICKUP_DELAY_REQUIRED')
    prep_edge = _one([d for d in snapshot['dependencies'] if d['predecessor_job_id'] == pick['id']
        and d['reason'] == 'RETURN_TO_PREP'], 'PICKUP_PREP_BINDING_REQUIRED')
    prep = ix['jobs'][prep_edge['successor_job_id']]
    if prep['kind'] != 'PREP' or prep['asset_ids'] != pick['asset_ids'] or prep['item_id'] != pick['item_id'] or prep['quantity'] != 1 \
            or prep['from_id'] != warehouse or prep['to_id'] != warehouse or prep['id'] not in old or prep['status'] in v1.FROZEN | {'CANCELLED'}:
        raise RecoveryError('PREP_RECOVERY_UNSUPPORTED')
    links = [d for d in snapshot['dependencies'] if d['predecessor_job_id'] == prep['id']]
    if len(links) > 1 or any(d['reason'] != 'ASSET_REUSE' for d in links):
        raise RecoveryError('RECOVERY_CHAIN_UNSUPPORTED')
    delivery = ix['jobs'][links[0]['successor_job_id']] if links else None
    if delivery and (delivery['kind'] != 'DELIVERY' or delivery['asset_ids'] != pick['asset_ids']
            or delivery['item_id'] != pick['item_id'] or delivery['quantity'] != 1 or delivery['id'] not in old
            or delivery['from_id'] != warehouse or delivery['status'] in v1.FROZEN | {'CANCELLED'}):
        raise RecoveryError('DELIVERY_RECOVERY_UNSUPPORTED')
    booking = _one([r for r in snapshot['reservations'] if r['status'] == 'ACTIVE'
        and r['asset_id'] == pick['asset_ids'][0] and r['release_job_id'] == prep['id']], 'PICKUP_RESERVATION_REQUIRED')
    if booking['review_required']:
        raise RecoveryError('RESERVATION_REVIEW_REQUIRED')
    rental = ix['rentals'].get(booking['rental_id'])
    if rental is None or rental['status'] != 'ACTIVE' or rental['actual_start'] is None or rental['actual_end'] is not None \
            or ix['customers'][rental['customer_id']]['location_id'] != pick['from_id']:
        raise RecoveryError('PICKUP_RENTAL_BINDING_REQUIRED', 'DATA_MISSING')
    if timestamp(rental['actual_start']) > timestamp(_service(old_pick)['start_at']) \
            or timestamp(booking['start_at']) > timestamp(_service(old_pick)['start_at']):
        raise RecoveryError('PICKUP_RENTAL_BINDING_REQUIRED', 'DATA_MISSING')
    delivery_booking = None
    if delivery:
        delivery_booking = _one([r for r in snapshot['reservations'] if r['status'] == 'ACTIVE'
            and r['asset_id'] == pick['asset_ids'][0] and timestamp(r['start_at']) == timestamp(old[delivery['id']]['start_at'])],
            'DELIVERY_RESERVATION_REQUIRED')
        if delivery_booking['review_required']:
            raise RecoveryError('RESERVATION_REVIEW_REQUIRED')
        planned = ix['rentals'].get(delivery_booking['rental_id'])
        if planned is None or planned['status'] != 'PLANNED' or planned['actual_start'] is not None or planned['actual_end'] is not None \
                or ix['customers'][planned['customer_id']]['location_id'] != delivery['to_id']:
            raise RecoveryError('DELIVERY_RENTAL_BINDING_REQUIRED', 'DATA_MISSING')
    return dict(ix=ix, travel=travel, warehouse=warehouse, op=op, pick=pick, prep=prep, prep_edge=prep_edge,
        delivery=delivery, delivery_edge=links[0] if links else None, booking=booking,
        rental=rental, delivery_booking=delivery_booking, old=old)


def _service(row):
    return _one([s for s in row['segments'] if s['kind'] == 'SERVICE'], 'SERVICE_STRUCTURE')


def _pickup(ctx, start, employee):
    pick, travel, wh = ctx['pick'], ctx['travel'], ctx['warehouse']
    site = pick['from_id']
    duration = ctx['ix']['items'][pick['item_id']]['service_minutes_by_kind']['PICKUP']
    service_end = start + timedelta(minutes=duration)
    departure = start - timedelta(minutes=travel[wh, site])
    returned = service_end + timedelta(minutes=travel[site, wh])
    segments = [dict(kind=kind, from_id=a, to_id=b, start_at=x.isoformat(), end_at=y.isoformat())
        for kind, a, b, x, y in [('TRAVEL', wh, site, departure, start),
            ('SERVICE', site, site, start, service_end), ('TRAVEL', site, wh, service_end, returned)]]
    return dict(id=None, plan_id=None, job_id=pick['id'], employee_id=employee,
        asset_ids=list(pick['asset_ids']), start_at=departure.isoformat(), end_at=returned.isoformat(),
        segments=segments, reason_codes=['RETURN_DELAY'])


def _prep(ctx, pick_row):
    start = timestamp(pick_row['end_at']) + timedelta(minutes=ctx['prep_edge']['minimum_gap_minutes'])
    end = start + timedelta(minutes=ctx['ix']['items'][ctx['prep']['item_id']]['prep_minutes'])
    wh = ctx['warehouse']
    return dict(id=None, plan_id=None, job_id=ctx['prep']['id'], employee_id=None,
        asset_ids=list(ctx['prep']['asset_ids']), start_at=start.isoformat(), end_at=end.isoformat(),
        segments=[dict(kind='PREP', from_id=wh, to_id=wh, start_at=start.isoformat(), end_at=end.isoformat())],
        reason_codes=['RETURN_DELAY'])


def _replace(old, *, input_hash, **updates):
    raw = deepcopy(old)
    raw.update(updates)
    raw['id'] = 'RS-' + hashlib.sha256((input_hash + ':' + old['id']).encode()).hexdigest()[:40]
    raw.update(plan_id=None, status='ACTIVE', review_required=False)
    return c.ReservationChange(action='REPLACE', old_id=old['id'], reservation=raw)


def _projection(snapshot, ctx, rows, input_hash):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', input_hash):
        raise RecoveryError('INVALID_INPUT_HASH', 'DATA_MISSING')
    by_job = {p['job_id']: p for p in rows}
    required = {j['id'] for j in snapshot['jobs'] if j['status'] != 'CANCELLED'}
    if len(by_job) != len(rows) or set(by_job) != required:
        raise RecoveryError('PLAN_COVERAGE_INVALID', 'DATA_MISSING')
    pick, prep, delivery, op = ctx['pick'], ctx['prep'], ctx['delivery'], ctx['op']
    pick_row, prep_row = by_job[pick['id']], by_job[prep['id']]
    canonical_pick = _pickup(ctx, timestamp(_service(pick_row)['start_at']), pick_row['employee_id'])
    if v1.signature(pick_row) != v1.signature(canonical_pick) or v1.signature(prep_row) != v1.signature(_prep(ctx, pick_row)):
        raise RecoveryError('RECOVERY_SEGMENTS_CHANGED')
    jobs = {pick['id']: dict(window_start=op.window_start, window_end=op.window_end, due_at=op.due_at,
                asset_ids=list(pick['asset_ids'])),
            prep['id']: dict(window_start=prep_row['start_at'], window_end=prep_row['end_at'],
                due_at=prep_row['end_at'], asset_ids=list(prep['asset_ids']))}
    rentals = {ctx['rental']['id']: {'expected_return_at': _service(pick_row)['end_at']}}
    changes = [_replace(ctx['booking'], input_hash=input_hash, end_at=prep_row['end_at'])]
    removals, replaceable = [], []
    if delivery:
        row, old = by_job[delivery['id']], ctx['old'][delivery['id']]
        if v1.signature(row, employee=False, assets=False) != v1.signature(old, employee=False, assets=False):
            raise RecoveryError('DELIVERY_PROMISE_CHANGED')
        if len(row['asset_ids']) != 1:
            raise RecoveryError('DELIVERY_ASSET_INVALID')
        aid = row['asset_ids'][0]
        if aid != delivery['asset_ids'][0]:
            asset = ctx['ix']['assets'].get(aid)
            if not asset or asset['item_id'] != delivery['item_id'] or asset['physical_state'] != 'READY_WAREHOUSE' or asset['location_id'] != ctx['warehouse']:
                raise RecoveryError('SUBSTITUTE_NOT_READY')
            jobs[delivery['id']] = {'asset_ids': [aid]}
            rentals[ctx['delivery_booking']['rental_id']] = {'asset_id': aid}
            changes.append(_replace(ctx['delivery_booking'], input_hash=input_hash, asset_id=aid))
            removals.append(ctx['delivery_edge']['id'])
            replaceable.append(delivery['id'])
    for row in rows:
        old = ctx['old'].get(row['job_id'])
        if old is None:
            raise RecoveryError('PLAN_BASE_REQUIRED', 'DATA_MISSING')
        if row['job_id'] not in {pick['id'], prep['id'], delivery['id'] if delivery else None} \
                and v1.signature(row, employee=False) != v1.signature(old, employee=False):
            raise RecoveryError('UNRELATED_JOB_CHANGED')
        if old and row['employee_id'] != old['employee_id']:
            jobs.setdefault(row['job_id'], {'asset_ids': list(row['asset_ids'])})
    view = deepcopy(snapshot)
    for job in view['jobs']:
        job.update(jobs.get(job['id'], {}))
    for rental in view['rentals']:
        rental.update(rentals.get(rental['id'], {}))
    view['dependencies'] = [d for d in view['dependencies'] if d['id'] not in removals]
    old_ids = {change.old_id for change in changes}
    for booking in view['reservations']:
        if booking['id'] in old_ids:
            booking['status'] = 'SUPERSEDED'
    new_ids = {change.reservation['id'] for change in changes}
    if len(new_ids) != len(changes) or new_ids & set(ctx['ix']['reservations']):
        raise RecoveryError('RESERVATION_ID_COLLISION', 'DATA_MISSING')
    view['reservations'].extend(deepcopy(change.reservation) for change in changes)
    return view, jobs, rentals, removals, changes, replaceable


def _change_key(changes):
    rows = []
    for change in changes:
        value = change.model_dump() if isinstance(change, c.ReservationChange) else c.ReservationChange.model_validate(change).model_dump()
        if value['reservation']:
            for key in ('start_at', 'end_at'):
                if value['reservation'].get(key) is not None:
                    value['reservation'][key] = timestamp(value['reservation'][key]).isoformat()
        rows.append(json.dumps(value, sort_keys=True, separators=(',', ':')))
    return sorted(rows)


def prepare_confirmation(snapshot, operations, candidate_items, reservation_changes, *, input_hash, as_of) -> ConfirmationChanges:
    """Rebuild exact writes under B's lock; invalid results contain no writes."""
    try:
        ctx = _context(snapshot, operations)
        rows = [p.model_dump() if isinstance(p, c.PlanItem) else c.PlanItem.model_validate(p).model_dump() for p in candidate_items]
        view, jobs, rentals, removals, expected, replaceable = _projection(snapshot, ctx, rows, input_hash)
        if _change_key(reservation_changes) != _change_key(expected):
            raise RecoveryError('RESERVATION_DELTA_MISMATCH')
        checked = v1.validate(view, rows, movable_jobs={ctx['pick']['id'], ctx['prep']['id']}, replaceable_jobs=replaceable, as_of=as_of)
        if checked.status != 'VALID':
            return ConfirmationChanges(validation=checked)
        return ConfirmationChanges(checked, jobs, rentals, removals, expected)
    except RecoveryError as exc:
        return ConfirmationChanges(c.ValidationResult(status='DATA_MISSING' if exc.status == 'DATA_MISSING' else 'INVALID',
            violations=[c.Violation(code=exc.code)], missing_fields=[]))
    except (ContractError, KeyError, TypeError, ValueError) as exc:
        return ConfirmationChanges(c.ValidationResult(status='DATA_MISSING', violations=[],
            missing_fields=exc.paths if isinstance(exc, ContractError) else ['recovery.input']))


def solve(inp: c.SolverInput, as_of: str) -> c.SolverResult:
    started, examined, limited = monotonic(), 0, False
    affected = set()

    def result(status, *, rows=(), changes=(), edges=(), code=None, violations=(), objective=()):
        return c.SolverResult(status=status, candidate_items=[c.PlanItem(**r) for r in rows], reservation_changes=list(changes),
            affected_job_ids=sorted(affected), impact_edges=list(edges), violations=list(violations),
            unresolved=[c.Unresolved(job_id=None, code=code, details={'message': _MESSAGES.get(code, '회수 지연 조건과 자원을 확인해 주세요.')})] if code else [],
            objective=list(objective), search_stats=c.SearchStats(elapsed_ms=max(0,int((monotonic()-started)*1000)),
                candidates_examined=examined, limit_reached=limited), input_hash=inp.input_hash, solver_version=VERSION)
    try:
        body = inp.model_dump(exclude={'schema_version','bundle_version','input_hash'})
        expected = 'sha256:' + hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if inp.bundle_version != c.BUNDLE_VERSION:
            raise RecoveryError('INVALID_BUNDLE', 'DATA_MISSING')
        if inp.input_hash != expected:
            raise RecoveryError('INVALID_INPUT_HASH', 'DATA_MISSING')
        if not 1 <= inp.max_candidates <= 1000 or not 1 <= inp.max_search_ms <= 2000:
            raise RecoveryError('INVALID_SEARCH_LIMIT', 'DATA_MISSING')
        if not timedelta(0) < timestamp(inp.horizon_end)-timestamp(inp.horizon_start) <= timedelta(days=7):
            raise RecoveryError('INVALID_HORIZON', 'DATA_MISSING')
        ctx = _context(inp.snapshot, inp.operations)
        if v1.validate(inp.snapshot, inp.snapshot['plan_items']).status == 'DATA_MISSING':
            raise RecoveryError('RECOVERY_DATA_MISSING', 'DATA_MISSING')
        if {r['version'] for r in inp.snapshot['travel_times']} != {inp.travel_version}:
            raise RecoveryError('TRAVEL_VERSION_MISMATCH', 'DATA_MISSING')
        if {p['plan_id'] for p in inp.snapshot['plan_items']} != {inp.base_plan_id}:
            raise RecoveryError('STALE_PLAN')
        if execution.stale_jobs(inp.snapshot, as_of):
            raise RecoveryError('EXECUTION_STATUS_REQUIRED')
        pick, prep, delivery = ctx['pick'], ctx['prep'], ctx['delivery']
        affected = {pick['id'], prep['id']} | ({delivery['id']} if delivery else set())
        base = deepcopy(ctx['old'])
        overrides = {}
        for override in inp.overrides:
            jid = override.get('job_id')
            if set(override) != {'job_id','employee_id'} or jid not in base or jid in overrides \
                    or override['employee_id'] not in ctx['ix']['employees'] or ctx['ix']['jobs'][jid]['kind'] == 'PREP' \
                    or ctx['ix']['jobs'][jid]['status'] in v1.FROZEN | {'CANCELLED'}:
                raise RecoveryError('RECOVERY_OVERRIDE_UNSUPPORTED')
            overrides[jid] = override['employee_id']
            base[jid]['employee_id'] = override['employee_id']
            affected.add(jid)
        if len(overrides) > 3:
            raise RecoveryError('RECOVERY_OVERRIDE_LIMIT')
        def employees(job):
            return [e['id'] for e in sorted(ctx['ix']['employees'].values(), key=lambda e:(e['id']!=ctx['old'][job['id']]['employee_id'], e['id']))
                if e['active'] and {'task_kind':job['kind'],'item_category':ctx['ix']['items'][job['item_id']]['category']} in e['skills']
                and (job['id'] not in overrides or e['id'] == overrides[job['id']])]
        assets = [pick['asset_ids'][0]]
        if delivery:
            assets += sorted(a['id'] for a in ctx['ix']['assets'].values() if a['id'] != assets[0]
                and a['item_id'] == delivery['item_id'] and a['physical_state'] == 'READY_WAREHOUSE' and a['location_id'] == ctx['warehouse'])
        duration = ctx['ix']['items'][pick['item_id']]['service_minutes_by_kind']['PICKUP']
        start = max(timestamp(ctx['op'].window_start), timestamp(as_of), timestamp(inp.horizon_start))
        high = min(timestamp(ctx['op'].window_end)-timedelta(minutes=duration),timestamp(inp.horizon_end))
        best, best_key, last = None, None, []
        while start <= high:
            for eid, asset_id, delivery_eid in itertools.product(employees(pick), assets, employees(delivery) if delivery else [None]):
                if examined >= inp.max_candidates or (monotonic()-started)*1000 >= inp.max_search_ms:
                    limited = True
                    break
                examined += 1
                selected = deepcopy(base)
                selected[pick['id']] = _pickup(ctx, start, eid)
                selected[prep['id']] = _prep(ctx, selected[pick['id']])
                if delivery:
                    selected[delivery['id']].update(employee_id=delivery_eid, asset_ids=[asset_id],
                        reason_codes=['SAME_MODEL_SUBSTITUTE'] if asset_id != pick['asset_ids'][0] else [])
                rows = [selected[jid] for jid in sorted(selected)]
                try:
                    view, jobs, rentals, removals, changes, replaceable = _projection(inp.snapshot, ctx, rows, inp.input_hash)
                except RecoveryError:
                    continue
                if any(not timestamp(inp.horizon_start) <= timestamp(selected[jid]['start_at']) < timestamp(selected[jid]['end_at']) <= timestamp(inp.horizon_end)
                        or timestamp(selected[jid]['start_at']) < timestamp(as_of) for jid in affected):
                    continue
                checked = v1.validate(view, rows, movable_jobs={pick['id'],prep['id']}, replaceable_jobs=replaceable, as_of=as_of)
                if checked.status != 'VALID':
                    last = checked.violations
                    continue
                key = (int(bool(removals)), sum(p['employee_id']!=ctx['old'][p['job_id']]['employee_id'] for p in rows),
                    tuple((p['employee_id'] or '', timestamp(p['start_at']), tuple(p['asset_ids']), p['job_id']) for p in rows))
                if best_key is None or key < best_key:
                    best, best_key = (deepcopy(rows), changes), key
            if limited:
                break
            start += timedelta(minutes=5)
        if best is None:
            return result('NO_SOLUTION_FOUND', code='SEARCH_LIMIT' if limited else 'NO_RECOVERY_CANDIDATE', violations=last)
        rows, changes = best
        for row in rows:
            row.update(id=None,plan_id=None)
            if row['employee_id'] != ctx['old'][row['job_id']]['employee_id']:
                row['reason_codes'] = sorted(set(row['reason_codes']) | {'PREFERRED_EMPLOYEE_CONFLICT'})
        prep_row = next(p for p in rows if p['job_id'] == prep['id'])
        edges = [c.ImpactEdge(from_job_id=pick['id'],to_job_id=prep['id'],reason='RETURN_DELAY',
            old_time=ctx['old'][prep['id']]['end_at'],new_time=prep_row['end_at'])]
        if delivery:
            new = next(p for p in rows if p['job_id'] == delivery['id'])
            edges.append(c.ImpactEdge(from_job_id=prep['id'],to_job_id=delivery['id'],
                reason='SAME_MODEL_SUBSTITUTE' if new['asset_ids']!=delivery['asset_ids'] else 'PREPARATION_DEPENDENCY',
                old_time=_service(ctx['old'][delivery['id']])['start_at'],new_time=_service(new)['start_at']))
        return result('FEASIBLE',rows=rows,changes=changes,edges=edges,objective=best_key[:2])
    except RecoveryError as exc:
        return result(exc.status,code=exc.code)
    except (ContractError, KeyError, TypeError, ValueError):
        return result('DATA_MISSING',code='RECOVERY_DATA_MISSING')


_MESSAGES = {
    'NO_RECOVERY_CANDIDATE': '기존 납품 약속을 지키는 회수·준비·대체 장비 조합을 찾지 못했습니다. 직원 휴식·재고·예약을 확인해 주세요.',
    'SEARCH_LIMIT': '제한된 탐색 안에서 복구안을 찾지 못했습니다. 불가능하다는 뜻은 아닙니다.',
    'PICKUP_RENTAL_BINDING_REQUIRED': '회수 장비의 기존 대여·예약 연결을 확인해 주세요.',
    'DELIVERY_RENTAL_BINDING_REQUIRED': '대체할 납품의 기존 대여·예약 연결을 확인해 주세요.',
}
