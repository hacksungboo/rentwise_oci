"""A-only opt-in recovery, unchanged B HTTP boundary and reference persistence.

The reference writer below is a test adapter, not B's production confirm API.
"""
from copy import deepcopy
import json

import pytest

from rentwise.contracts import types as c
from rentwise.engine import RealEngine
from rentwise.engine import recovery, v1
from .test_compat import public_snapshot, request


def operation(**changes):
    op = dict(operation='RESCHEDULE', kind='PICKUP', target_job_id='J-PICK1',
        window_start='2026-10-16T14:00:00+09:00', window_end='2026-10-16T14:10:00+09:00',
        due_at='2026-10-16T17:00:00+09:00')
    return dict(op, **changes)


def solved(**kwargs):
    inp = request(operations=[operation()], **kwargs)
    result = RealEngine(recovery_enabled=True).solve(inp)
    assert result.status == 'FEASIBLE', result
    return inp, result


def prepare(inp, result):
    # Fresh instance, serialized result, and B-assigned row/plan IDs.
    result = c.SolverResult.model_validate_json(result.model_dump_json())
    for p in result.candidate_items:
        p.id, p.plan_id = 'B-' + p.job_id, 'B-DRAFT'
    return RealEngine(recovery_enabled=True).prepare_confirmation(inp.snapshot,
        inp.operations, result.candidate_items, result.reservation_changes, input_hash=inp.input_hash)


def test_delay_keeps_delivery_promise_and_computes_exact_business_writes():
    inp, result = solved()
    before = deepcopy(inp.snapshot)
    rows = {p.job_id: p for p in result.candidate_items}
    assert rows['J-PICK1'].employee_id == 'E2'  # E1's break includes the outbound trip.
    assert rows['J-PICK1'].start_at == '2026-10-16T13:40:00+09:00'
    assert rows['J-PREP1'].end_at == '2026-10-16T15:00:00+09:00'
    assert rows['J-DEL1'].asset_ids == ['P02']
    assert rows['J-DEL1'].segments[1].start_at == '2026-10-16T12:00:00+09:00'
    assert {e.reason for e in result.impact_edges} == {'RETURN_DELAY', 'SAME_MODEL_SUBSTITUTE'}
    writes = prepare(inp, result)
    assert writes.validation.status == 'VALID', writes
    assert writes.rental_updates == {'R-H': {'expected_return_at': '2026-10-16T14:10:00+09:00'}, 'R-S2': {'asset_id': 'P02'}}
    assert writes.dependency_deletions == ['D-PREP1-DEL1']
    assert {r.old_id for r in writes.reservation_changes} == {'RS-H', 'RS-S2'}
    assert all(len(r.reservation['id']) <= 64 for r in writes.reservation_changes)
    assert inp.snapshot == before
    # Existing B validator remains strict and cannot accidentally partially confirm.
    assert RealEngine().validate(inp.snapshot, result.candidate_items).status == 'INVALID'
    assert RealEngine().prepare_confirmation(inp.snapshot, inp.operations, result.candidate_items,
        result.reservation_changes, input_hash=inp.input_hash).validation.status == 'INVALID'


def test_small_delay_prefers_original_asset_and_preserves_dependency():
    inp = request(operations=[operation(window_start='2026-10-16T10:05:00+09:00', window_end='2026-10-16T10:15:00+09:00')])
    result = RealEngine(recovery_enabled=True).solve(inp)
    assert result.status == 'FEASIBLE', result
    assert next(p for p in result.candidate_items if p.job_id == 'J-DEL1').asset_ids == ['P01']
    writes = prepare(inp, result)
    assert writes.validation.status == 'VALID'
    assert writes.dependency_deletions == [] and len(writes.reservation_changes) == 1
    assert set(writes.rental_updates) == {'R-H'}


def test_pickup_without_followup_delivery_only_extends_existing_rental_booking():
    s = public_snapshot()
    s['jobs'] = [j for j in s['jobs'] if j['id'] != 'J-DEL1']
    s['plan_items'] = [p for p in s['plan_items'] if p['job_id'] != 'J-DEL1']
    s['reservations'] = [r for r in s['reservations'] if r['id'] != 'RS-S2']
    s['dependencies'] = [d for d in s['dependencies'] if d['successor_job_id'] != 'J-DEL1']
    inp, result = solved(snapshot=s)
    writes = prepare(inp, result)
    assert writes.validation.status == 'VALID'
    assert len(writes.reservation_changes) == 1 and writes.dependency_deletions == []
    assert set(writes.rental_updates) == {'R-H'}


@pytest.mark.parametrize('change', ['duplicate_job', 'missing_job', 'future_actual'])
def test_corrupt_base_plan_or_actual_time_is_data_missing(change):
    s = public_snapshot()
    if change == 'duplicate_job':
        duplicate = dict(s['plan_items'][0], id='EXTRA')
        s['plan_items'].append(duplicate)
    elif change == 'missing_job': s['plan_items'].pop()
    else: next(r for r in s['rentals'] if r['id'] == 'R-H')['actual_start'] = '2026-10-17T00:00:00+09:00'
    r = RealEngine(recovery_enabled=True).solve(request(snapshot=s, operations=[operation()]))
    assert r.status == 'DATA_MISSING' and not r.candidate_items


def test_timeout_without_a_candidate_is_not_a_proof_of_impossibility(monkeypatch):
    ticks = iter([0, 3, 3])
    monkeypatch.setattr(recovery, 'monotonic', lambda: next(ticks))
    r = RealEngine(recovery_enabled=True).solve(request(operations=[operation()]))
    assert r.status == 'NO_SOLUTION_FOUND' and r.search_stats.limit_reached
    assert r.search_stats.candidates_examined == 0 and not r.candidate_items


def test_search_limit_can_return_a_valid_best_so_far_without_claiming_optimality():
    inp, result = solved(max_candidates=13)
    assert result.search_stats.limit_reached
    assert result.search_stats.candidates_examined == 13
    assert prepare(inp, result).validation.status == 'VALID'


@pytest.mark.parametrize('change', ['pickup_rental', 'delivery_rental', 'prep_binding', 'travel', 'duplicate', 'future_booking'])
def test_missing_bindings_and_future_booking_never_fabricate_recovery(change):
    snapshot = public_snapshot()
    if change == 'pickup_rental': snapshot['reservations'][0]['rental_id'] = None
    elif change == 'delivery_rental': next(r for r in snapshot['reservations'] if r['id'] == 'RS-S2')['rental_id'] = None
    elif change == 'prep_binding': snapshot['dependencies'] = [d for d in snapshot['dependencies'] if d['reason'] != 'RETURN_TO_PREP']
    elif change == 'travel': snapshot['travel_times'].pop()
    elif change == 'duplicate': snapshot['assets'].append(deepcopy(snapshot['assets'][0]))
    elif change == 'future_booking':
        # P04 already has a future booking; reserving P02 also blocks both spares.
        snapshot['reservations'].append(dict(id='FUTURE', asset_id='P02', rental_id=None,
            start_at='2026-10-20T12:00:00+09:00', end_at=None, release_job_id=None,
            plan_id=None, status='ACTIVE', review_required=False))
    before = deepcopy(snapshot)
    result = RealEngine(recovery_enabled=True).solve(request(snapshot=snapshot, operations=[operation()]))
    assert result.status != 'FEASIBLE', result
    assert result.candidate_items == [] and result.reservation_changes == []
    assert snapshot == before


@pytest.mark.parametrize('change', ['frozen_pick', 'frozen_prep', 'frozen_delivery', 'wrong_item',
    'active_planned', 'completed_rental', 'multi_asset', 'cancelled_pick', 'cycle', 'review_booking', 'no_skill'])
def test_execution_bindings_and_calendars_are_hard_constraints(change):
    s = public_snapshot()
    jobs = {j['id']: j for j in s['jobs']}
    if change.startswith('frozen_'):
        jid = {'frozen_pick':'J-PICK1', 'frozen_prep':'J-PREP1', 'frozen_delivery':'J-DEL1'}[change]
        jobs[jid]['status'] = 'IN_PROGRESS'
    elif change == 'wrong_item': jobs['J-DEL1']['item_id'] = 'WP-A'
    elif change == 'active_planned': next(r for r in s['rentals'] if r['id'] == 'R-S2')['status'] = 'ACTIVE'
    elif change == 'completed_rental': next(r for r in s['rentals'] if r['id'] == 'R-H')['actual_end'] = '2026-10-16T09:00:00+09:00'
    elif change == 'multi_asset': jobs['J-PICK1'].update(asset_ids=['P01','P02'], quantity=2)
    elif change == 'cancelled_pick': jobs['J-PICK1']['status'] = 'CANCELLED'
    elif change == 'cycle': s['dependencies'].append(dict(id='CYCLE', predecessor_job_id='J-PREP1', successor_job_id='J-PICK1', minimum_gap_minutes=0, reason='TEST'))
    elif change == 'review_booking': next(r for r in s['reservations'] if r['id'] == 'RS-H')['review_required'] = True
    elif change == 'no_skill':
        for e in s['employees']: e['skills'] = []
    result = RealEngine(recovery_enabled=True).solve(request(snapshot=s, operations=[operation()]))
    assert result.status != 'FEASIBLE', result
    assert not result.candidate_items and not result.reservation_changes


@pytest.mark.parametrize('changes', [dict(window_start=None), dict(due_at=None), dict(target_job_id='UNKNOWN'),
    dict(window_start='2026-10-16T10:00:00+09:00'), dict(window_end='2026-10-16T14:05:00+09:00'),
    dict(due_at='2026-10-16T14:10:00+09:00'), dict(asset_ids=['P02']), dict(quantity=2),
    dict(from_id='L-W'), dict(source_customer_id='C-B'), dict(operation='CREATE')])
def test_unsupported_request_never_emits_partial_candidates(changes):
    result = RealEngine(recovery_enabled=True).solve(request(operations=[operation(**changes)]))
    assert result.status != 'FEASIBLE', result
    assert not result.candidate_items and not result.reservation_changes


def test_hash_search_clock_scope_and_seed_defect_remain_visible():
    e = RealEngine(recovery_enabled=True)
    for changes in ({'max_candidates':0}, {'max_search_ms':3000}, {'base_plan_id':'OLD'},
        {'horizon_end':'2026-11-01T00:00:00+09:00'}, {'overrides':[{}]}):
        result = e.solve(request(operations=[operation()], **changes))
        assert result.status != 'FEASIBLE', result
        assert result.candidate_items == []
    inp = request(operations=[operation()]); inp.input_hash = 'sha256:' + '0' * 64
    assert e.solve(inp).status == 'DATA_MISSING'
    assert e.solve(request(operations=[operation(), operation()])).status == 'NEEDS_REVIEW'
    result = e.solve(request(operations=[operation()], max_candidates=1))
    assert result.search_stats.limit_reached and result.search_stats.candidates_examined == 1
    assert result.unresolved[0].code == 'SEARCH_LIMIT'
    assert RealEngine(recovery_enabled=True, as_of='2026-10-16T14:00:00+09:00').solve(request(operations=[operation()])).status != 'FEASIBLE'


@pytest.mark.parametrize('tamper', ['omit', 'duplicate', 'travel', 'prep', 'delivery_time', 'delivery_asset',
    'unrelated_as_time', 'unrelated_asset', 'delta_missing', 'delta_extra', 'delta_end', 'delta_rental', 'delta_id', 'frozen_after', 'busy_after'])
def test_confirmation_rebuild_rejects_tampering_or_changed_state_without_any_writes(tamper):
    inp, result = solved()
    rows = {p.job_id:p for p in result.candidate_items}
    if tamper == 'omit': result.candidate_items.pop()
    elif tamper == 'duplicate': result.candidate_items.append(result.candidate_items[0])
    elif tamper == 'travel': rows['J-PICK1'].segments[0].start_at = rows['J-PICK1'].segments[0].end_at
    elif tamper == 'prep': rows['J-PREP1'].end_at = '2026-10-16T14:40:00+09:00'
    elif tamper == 'delivery_time': rows['J-DEL1'].segments[1].start_at = '2026-10-16T12:01:00+09:00'
    elif tamper == 'delivery_asset': rows['J-DEL1'].asset_ids = ['P04']
    elif tamper == 'unrelated_as_time': rows['J-AS1'].start_at = '2026-10-16T10:00:00+09:00'
    elif tamper == 'unrelated_asset': rows['J-AS2'].asset_ids = ['P02']
    elif tamper == 'delta_missing': result.reservation_changes.pop()
    elif tamper == 'delta_extra': result.reservation_changes.append(result.reservation_changes[0])
    elif tamper.startswith('delta_'):
        key, value = {'delta_end':('end_at','2026-10-16T14:30:00+09:00'), 'delta_rental':('rental_id',None), 'delta_id':('id','FORGED')}[tamper]
        result.reservation_changes[0].reservation[key] = value
    elif tamper == 'frozen_after': next(j for j in inp.snapshot['jobs'] if j['id'] == 'J-PICK1')['status'] = 'IN_PROGRESS'
    elif tamper == 'busy_after': next(a for a in inp.snapshot['assets'] if a['id'] == 'P02')['physical_state'] = 'REPAIR'
    before = deepcopy(inp.snapshot)
    writes = prepare(inp, result)
    assert writes.validation.status != 'VALID', writes
    assert not writes.job_updates and not writes.rental_updates and not writes.dependency_deletions and not writes.reservation_changes
    assert inp.snapshot == before


def test_active_binding_stays_strict_but_historical_asset_is_preserved():
    s = public_snapshot()
    next(r for r in s['rentals'] if r['id'] == 'R-S2')['asset_id'] = 'P02'
    with pytest.raises(ValueError): v1.inspect(s)
    next(r for r in s['reservations'] if r['id'] == 'RS-S2')['status'] = 'SUPERSEDED'
    v1.inspect(s)


def draft_from_existing_b_api(admin, monkeypatch):
    from rentwise.services import plans
    monkeypatch.setattr(plans, 'get_engine', lambda: RealEngine(recovery_enabled=True))
    # Only exercise the optional native adapter here. Existing B v2 pickup
    # integration is tested separately and stays enabled in production.
    monkeypatch.setattr(plans.v2_bridge, 'supports', lambda _: False)
    req = admin.post('/api/v1/requests', json={'source_customer_id':'C-H','text':'회수를 14시로 미뤄 주세요'}).json()
    op = operation(item_id='PR-A', asset_ids=['P01'], quantity=1, source_customer_id='C-H',
        destination_customer_id=None, rental_end_at=None, priority_hint='NORMAL', evidence=[])
    saved = admin.put(f"/api/v1/requests/{req['id']}/interpretation", json={'expected_request_revision':1,
        'payload':{'schema_version':'rental.intent.v1', 'operations':[op], 'needs_confirmation':[]}, 'acknowledged_paths':[]})
    assert saved.status_code == 200, saved.text
    draft = admin.post('/api/v1/plans', json={'request_id':req['id'],
        'interpretation_revision':saved.json()['interpretation']['revision'], 'base_state_revision':7,
        'overrides':[{'job_id':'J-AS2','employee_id':'E2'}]})
    assert draft.status_code == 201 and draft.json()['status'] == 'READY', draft.text
    assert len(draft.json()['result']['reservation_changes']) == 2
    assert any(d['kind'] == 'DELIVERY' and d['after']['asset_ids'] == ['P02'] for d in draft.json()['diff'])
    return draft.json()['id']


def test_existing_b_draft_and_view_work_but_unmodified_confirm_is_safely_blocked(admin, monkeypatch):
    from rentwise.db import database
    with database.get_db_engine().connect() as conn: before = database.read_snapshot(conn)
    pid = draft_from_existing_b_api(admin, monkeypatch)
    blocked = admin.post(f'/api/v1/plans/{pid}/confirm', json={'expected_plan_revision':1, 'base_state_revision':7})
    assert blocked.status_code == 422 and blocked.json()['error']['code'] == 'CONSTRAINT_VIOLATION', blocked.text
    with database.get_db_engine().connect() as conn: assert database.read_snapshot(conn) == before


def _reference_write(conn, pid, changes):
    """Minimal B write adapter example. No production service is patched."""
    from sqlalchemy import delete, insert, update
    from rentwise.db import tables as T
    from rentwise.db.database import J
    from rentwise.timeutil import to_db
    assert changes.validation.status == 'VALID'
    for jid, patch in changes.job_updates.items():
        values = {'asset_ids_json':J(patch['asset_ids']), 'revision':T.jobs.c.revision + 1}
        values.update({k:to_db(v) for k,v in patch.items() if k != 'asset_ids'})
        conn.execute(update(T.jobs).where(T.jobs.c.id == jid).values(**values))
    for rid, patch in changes.rental_updates.items():
        conn.execute(update(T.rentals).where(T.rentals.c.id == rid).values(**{
            k:to_db(v) if k == 'expected_return_at' else v for k,v in patch.items()}))
    for did in changes.dependency_deletions:
        conn.execute(delete(T.dependencies).where(T.dependencies.c.id == did))
    for ch in changes.reservation_changes:
        conn.execute(update(T.reservations).where(T.reservations.c.id == ch.old_id).values(status='SUPERSEDED'))
        r = dict(ch.reservation, plan_id=pid)
        for key in ('start_at','end_at'): r[key] = to_db(r[key])
        conn.execute(insert(T.reservations).values(**r))
    conn.execute(update(T.plans).where(T.plans.c.id == 'PL-007').values(status='SUPERSEDED'))
    conn.execute(update(T.plans).where(T.plans.c.id == pid).values(status='CONFIRMED'))
    conn.execute(update(T.workspace_state).where(T.workspace_state.c.id == 'DEMO').values(current_plan_id=pid, state_revision=8))


@pytest.mark.parametrize('rollback', [False, True])
def test_reference_b_transaction_persists_valid_plan_or_rolls_back_every_write(admin, monkeypatch, rollback):
    from sqlalchemy import select
    from rentwise.db import database, tables as T
    from rentwise.services.plans import _items
    pid = draft_from_existing_b_api(admin, monkeypatch)
    with database.get_db_engine().connect() as conn: before = database.read_snapshot(conn)
    class SimulatedFailure(Exception): pass
    try:
        with database.get_db_engine().begin() as conn:
            p = conn.execute(select(T.plans).where(T.plans.c.id == pid)).one()
            snapshot = database.read_snapshot(conn)
            changes = RealEngine(recovery_enabled=True).prepare_confirmation(snapshot, json.loads(p.operations_json),
                list(_items(conn, pid).values()), json.loads(p.result_json)['reservation_changes'], input_hash=p.input_hash)
            assert changes.validation.status == 'VALID', changes
            _reference_write(conn, pid, changes)
            if rollback: raise SimulatedFailure()
    except SimulatedFailure: pass
    with database.get_db_engine().connect() as conn: after = database.read_snapshot(conn)
    if rollback:
        assert after == before
        return
    assert RealEngine().validate(after, after['plan_items']).status == 'VALID'
    assert after['assets'] == before['assets']
    for rental in after['rentals']:
        old = next(r for r in before['rentals'] if r['id'] == rental['id'])
        assert {k:v for k,v in rental.items() if k not in ('asset_id','expected_return_at')} == {k:v for k,v in old.items() if k not in ('asset_id','expected_return_at')}
    assert len(after['reservations']) == len(before['reservations']) + 2
    assert next(r for r in after['rentals'] if r['id'] == 'R-S2')['asset_id'] == 'P02'
    # Availability remains consistent after persisted reservation/rental replacement.
    available = RealEngine().availability(c.AvailabilityInput(snapshot=after, from_at='2026-10-16T09:00:00+09:00',
        to_at='2026-10-16T18:00:00+09:00', base_state_revision=8))
    assert available.status == 'OK'
    assert all('P01' not in w.ready_asset_ids for w in available.windows if w.to_at <= '2026-10-16T15:00:00+09:00')
