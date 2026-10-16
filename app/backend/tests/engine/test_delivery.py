"""Native B v1 delivery, authoritative bindings and reference persistence.

HTTP tests inject only a test normalization adapter. Production B stays intact.
"""
from copy import deepcopy
import json

import pytest

from rentwise.contracts import types as c
from rentwise.engine import RealEngine
from rentwise.engine import delivery
from .test_compat import public_snapshot, request


def operation(**changes):
    return dict(dict(operation='CREATE', kind='DELIVERY', target_job_id=None, item_id='PR-A',
        asset_ids=[], quantity=1, source_customer_id=None, destination_customer_id='C-S',
        window_start='2026-10-16T15:00:00+09:00', window_end='2026-10-16T15:15:00+09:00',
        due_at='2026-10-16T17:00:00+09:00', rental_end_at=None, priority_hint='NORMAL', return_policy='OPEN_ENDED',
        allocation={'job_id':'J-NEW', 'rental_id':'R-NEW', 'reservation_id':'RS-NEW', 'dependency_id':'D-NEW'}), **changes)


def solve(op=None, **kwargs):
    kwargs.setdefault('overrides', [])
    inp = request(operations=[op or operation()], **kwargs)
    result = RealEngine(delivery_enabled=True).solve(inp)
    assert result.status == 'FEASIBLE', result
    return inp, result


def prepare(inp, result, *, engine=None):
    result = c.SolverResult.model_validate_json(result.model_dump_json())
    for row in result.candidate_items:
        row.id, row.plan_id = 'PI-DRAFT-' + row.job_id, 'B-DRAFT'
    return (engine or RealEngine(delivery_enabled=True)).prepare_delivery_confirmation(inp.snapshot,
        inp.operations, result.candidate_items, result.reservation_changes, request_id=inp.request_id, input_hash=inp.input_hash)


def assert_no_writes(changes):
    assert changes.validation.status != 'VALID', changes
    assert not changes.job_creates and not changes.rental_creates and not changes.dependency_creates
    assert not changes.job_updates and not changes.reservation_changes


def test_new_delivery_uses_exact_b_dtos_and_preserves_all_existing_promises():
    inp, result = solve()
    before = deepcopy(inp.snapshot)
    old = {p['job_id']: p for p in before['plan_items']}
    new = next(p for p in result.candidate_items if p.job_id == 'J-NEW')
    assert type(result) is c.SolverResult and result.solver_version == delivery.VERSION
    assert result.input_hash == inp.input_hash
    assert new.asset_ids == ['P02'] and new.employee_id == 'E1'
    assert new.start_at == '2026-10-16T14:40:00+09:00'
    assert new.segments[1].start_at == '2026-10-16T15:00:00+09:00'
    assert new.segments[1].end_at == '2026-10-16T15:15:00+09:00'
    assert new.end_at == '2026-10-16T15:35:00+09:00'
    for row in result.candidate_items:
        assert row.id is None and row.plan_id is None
        if row.job_id in old:
            expected = dict(old[row.job_id], id=None, plan_id=None)
            assert row.model_dump() == expected
    changes = prepare(inp, result)
    assert changes.validation.status == 'VALID', changes
    assert changes.job_creates[0]['request_id'] == inp.request_id
    assert changes.job_creates[0]['asset_ids'] == ['P02'] and changes.job_creates[0]['revision'] == 1
    assert changes.rental_creates == [dict(id='R-NEW', asset_id='P02', customer_id='C-S',
        actual_start=None, actual_end=None, expected_return_at=None, status='PLANNED')]
    assert changes.reservation_changes[0].action == 'CREATE'
    assert changes.reservation_changes[0].reservation['end_at'] is None
    assert changes.dependency_creates == [] and changes.job_updates == {}
    assert inp.snapshot == before


def test_default_engine_and_legacy_validator_cannot_confirm_new_business_rows():
    inp, result = solve()
    disabled = RealEngine().solve(inp)
    assert disabled.status == 'NEEDS_REVIEW' and not disabled.candidate_items and not disabled.reservation_changes
    assert RealEngine().validate(inp.snapshot, result.candidate_items).status != 'VALID'
    assert_no_writes(prepare(inp, result, engine=RealEngine()))


def test_preferred_employee_break_is_respected_and_another_employee_is_selected():
    inp, result = solve(operation(window_start='2026-10-16T14:00:00+09:00', window_end='2026-10-16T14:15:00+09:00'))
    new = next(p for p in result.candidate_items if p.job_id == 'J-NEW')
    assert new.employee_id != 'E1'  # 13:40 outbound crosses E1's break, even though service starts at 14:00.
    assert 'PREFERRED_EMPLOYEE_CONFLICT' in new.reason_codes
    assert prepare(inp, result).validation.status == 'VALID'


def test_fixed_return_is_expected_only_and_does_not_fabricate_inventory_release():
    inp, result = solve(operation(return_policy='FIXED', rental_end_at='2026-10-17T10:00:00+09:00'))
    changes = prepare(inp, result)
    assert changes.validation.status == 'VALID'
    assert changes.rental_creates[0]['expected_return_at'] == '2026-10-17T10:00:00+09:00'
    assert changes.rental_creates[0]['actual_end'] is None
    assert changes.reservation_changes[0].reservation['end_at'] is None
    # P04 has an Oct19 booking: an Oct17 expected return still does not release it.
    r = RealEngine(delivery_enabled=True).solve(request(operations=[operation(asset_ids=['P04'],
        return_policy='FIXED', rental_end_at='2026-10-17T10:00:00+09:00')], overrides=[]))
    assert r.status == 'NO_SOLUTION_FOUND' and not r.candidate_items


def test_unspecified_urgency_uses_existing_b_normal_policy_without_inventing_ai_evidence():
    inp, result = solve(operation(priority_hint='UNKNOWN'))
    assert prepare(inp, result).job_creates[0]['priority'] == 'NORMAL'
    assert inp.operations[0].priority_hint == 'UNKNOWN'


def test_customer_window_and_no_qualified_employee_prevent_a_candidate():
    s = public_snapshot()
    next(cu for cu in s['customers'] if cu['id'] == 'C-S')['visit_windows'] = [
        {'start_at':'2026-10-16T09:00:00+09:00','end_at':'2026-10-16T14:00:00+09:00'}]
    result = RealEngine(delivery_enabled=True).solve(request(snapshot=s, operations=[operation()], overrides=[]))
    assert result.status == 'NO_SOLUTION_FOUND' and not result.candidate_items
    assert any(v.code == 'CUSTOMER_VISIT_WINDOW' and v.job_ids == ['J-NEW'] for v in result.violations)
    s = public_snapshot()
    for emp in s['employees']: emp['skills'] = []
    result = RealEngine(delivery_enabled=True).solve(request(snapshot=s, operations=[operation()], overrides=[]))
    assert result.status == 'NO_SOLUTION_FOUND' and result.search_stats.candidates_examined == 0


def conditional_snapshot():
    s = public_snapshot()
    s['jobs'] = [j for j in s['jobs'] if j['id'] != 'J-DEL1']
    s['plan_items'] = [p for p in s['plan_items'] if p['job_id'] != 'J-DEL1']
    s['reservations'] = [r for r in s['reservations'] if r['id'] != 'RS-S2']
    s['dependencies'] = [d for d in s['dependencies'] if d['successor_job_id'] != 'J-DEL1']
    return s


def test_existing_return_and_preparation_can_supply_a_new_delivery():
    inp, result = solve(operation(asset_ids=['P01']), snapshot=conditional_snapshot())
    changes = prepare(inp, result)
    assert changes.validation.status == 'VALID', changes
    assert changes.dependency_creates == [dict(id='D-NEW', predecessor_job_id='J-PREP1',
        successor_job_id='J-NEW', minimum_gap_minutes=0, reason='ASSET_REUSE')]
    assert result.impact_edges[0].from_job_id == 'J-PREP1'
    assert result.impact_edges[0].to_job_id == 'J-NEW'
    assert changes.rental_creates[0]['asset_id'] == 'P01'


@pytest.mark.parametrize('change', ['before_ready', 'missing_release', 'missing_prep', 'missing_return', 'review_booking'])
def test_conditional_inventory_requires_real_return_preparation_and_release(change):
    s = conditional_snapshot(); op = operation(asset_ids=['P01'])
    if change == 'before_ready': op.update(window_start='2026-10-16T10:30:00+09:00', window_end='2026-10-16T10:45:00+09:00')
    elif change == 'missing_release': next(r for r in s['reservations'] if r['id'] == 'RS-H')['release_job_id'] = None
    elif change == 'missing_prep': next(j for j in s['jobs'] if j['id'] == 'J-PREP1')['status'] = 'COMPLETED'
    elif change == 'missing_return': s['dependencies'] = [d for d in s['dependencies'] if d['reason'] != 'RETURN_TO_PREP']
    elif change == 'review_booking': next(r for r in s['reservations'] if r['id'] == 'RS-H')['review_required'] = True
    r = RealEngine(delivery_enabled=True).solve(request(snapshot=s, operations=[op], overrides=[]))
    assert r.status != 'FEASIBLE', r
    assert not r.candidate_items and not r.reservation_changes


@pytest.mark.parametrize('changes', [dict(quantity=2), dict(quantity=None), dict(item_id='UNKNOWN'),
    dict(destination_customer_id=None), dict(destination_customer_id='UNKNOWN'), dict(source_customer_id='C-H'),
    dict(target_job_id='J-DEL1'), dict(asset_ids=['P02','P04']), dict(asset_ids=['W01']), dict(asset_ids=['UNKNOWN']),
    dict(window_start=None), dict(due_at=None), dict(priority_hint='BAD'), dict(return_policy=None),
    dict(return_policy='FIXED'), dict(rental_end_at='2026-10-17T10:00:00+09:00'),
    dict(return_policy='FIXED', rental_end_at='2026-10-16T14:50:00+09:00'),
    dict(allocation=None), dict(allocation={'job_id':'J-NEW'}),
    dict(allocation={'job_id':'J-DEL1','rental_id':'R-NEW','reservation_id':'RS-NEW','dependency_id':'D-NEW'}),
    dict(from_id='L-H'), dict(to_id='L-H'), dict(extra_unknown=True)])
def test_unconfirmed_unsupported_or_invalid_input_has_no_partial_plan(changes):
    r = RealEngine(delivery_enabled=True).solve(request(operations=[operation(**changes)], overrides=[]))
    assert r.status != 'FEASIBLE', r
    assert not r.candidate_items and not r.reservation_changes


def test_search_limits_hash_versions_clock_and_multiple_operations():
    e = RealEngine(delivery_enabled=True)
    for kw in ({'max_candidates':0}, {'max_search_ms':3000}, {'base_plan_id':'STALE'},
        {'horizon_end':'2026-11-01T00:00:00+09:00'}, {'travel_version':'STALE'}, {'bundle_version':'bad'}):
        r = e.solve(request(operations=[operation()], overrides=[], **kw))
        assert r.status != 'FEASIBLE' and not r.candidate_items
    i = request(operations=[operation()], overrides=[]); i.input_hash = 'sha256:' + '0' * 64
    assert e.solve(i).status == 'DATA_MISSING'
    r = e.solve(request(operations=[operation(), operation()], overrides=[]))
    assert r.status == 'NEEDS_REVIEW' and not r.candidate_items
    r = RealEngine(delivery_enabled=True, as_of='2026-10-16T15:00:00+09:00').solve(request(operations=[operation()], overrides=[]))
    assert r.status == 'NEEDS_REVIEW' and r.unresolved[0].code == 'EXECUTION_STATUS_REQUIRED' and not r.candidate_items
    inp, result = solve(max_candidates=4)
    assert result.search_stats.limit_reached and result.search_stats.candidates_examined == 4
    assert prepare(inp, result).validation.status == 'VALID'


def test_timeout_without_candidate_is_not_an_impossibility_proof(monkeypatch):
    ticks = iter([0, 3, 3])
    monkeypatch.setattr(delivery, 'monotonic', lambda: next(ticks))
    r = RealEngine(delivery_enabled=True).solve(request(operations=[operation()], overrides=[]))
    assert r.status == 'NO_SOLUTION_FOUND' and r.unresolved[0].code == 'SEARCH_LIMIT'
    assert r.search_stats.limit_reached and r.search_stats.candidates_examined == 0


def test_grid_and_explicit_non_grid_times_use_the_requested_service_time():
    inp, r = solve(operation(window_start='2026-10-16T15:07:00+09:00', window_end='2026-10-16T15:22:00+09:00'))
    assert next(p for p in r.candidate_items if p.job_id == 'J-NEW').segments[1].start_at == '2026-10-16T15:07:00+09:00'
    inp, r = solve(operation(window_start='2026-10-16T15:07:00+09:00', window_end='2026-10-16T15:45:00+09:00'))
    assert next(p for p in r.candidate_items if p.job_id == 'J-NEW').segments[1].start_at == '2026-10-16T15:10:00+09:00'


@pytest.mark.parametrize('tamper', ['omit', 'duplicate', 'travel', 'service', 'wrong_asset', 'unpinned_asset',
    'existing_time', 'existing_asset', 'employee', 'delta_missing', 'delta_duplicate', 'delta_end',
    'delta_rental', 'delta_id', 'delta_plan', 'state_changed', 'id_collision', 'frozen_existing'])
def test_confirmation_rebuild_blocks_tampering_and_returns_zero_writes(tamper):
    inp, r = solve()
    rows = {p.job_id:p for p in r.candidate_items}; new = rows['J-NEW']
    if tamper == 'omit': r.candidate_items.pop()
    elif tamper == 'duplicate': r.candidate_items.append(new)
    elif tamper == 'travel': new.segments[0].start_at = new.segments[0].end_at
    elif tamper == 'service': new.segments[1].end_at = new.segments[1].start_at
    elif tamper == 'wrong_asset': new.asset_ids = ['W01']
    elif tamper == 'unpinned_asset': new.asset_ids = ['P04']
    elif tamper == 'existing_time': rows['J-AS1'].start_at = rows['J-AS1'].end_at
    elif tamper == 'existing_asset': rows['J-AS1'].asset_ids = ['W04']
    elif tamper == 'employee': new.employee_id = 'UNKNOWN'
    elif tamper == 'delta_missing': r.reservation_changes = []
    elif tamper == 'delta_duplicate': r.reservation_changes *= 2
    elif tamper.startswith('delta_'):
        key, value = {'delta_end':('end_at','2026-10-17T10:00:00+09:00'), 'delta_rental':('rental_id',None),
            'delta_id':('id','OTHER'), 'delta_plan':('plan_id','FORGED')}[tamper]
        r.reservation_changes[0].reservation[key] = value
    elif tamper == 'state_changed': next(a for a in inp.snapshot['assets'] if a['id'] == 'P02')['physical_state'] = 'REPAIR'
    elif tamper == 'id_collision': inp.snapshot['rentals'].append(dict(inp.snapshot['rentals'][0], id='R-NEW'))
    elif tamper == 'frozen_existing':
        next(j for j in inp.snapshot['jobs'] if j['id'] == 'J-AS1')['status'] = 'IN_PROGRESS'
        rows['J-AS1'].employee_id = 'E2'
    before = deepcopy(inp.snapshot)
    assert_no_writes(prepare(inp, r))
    assert inp.snapshot == before


def test_fresh_confirmation_clock_and_missing_ids_fail_closed():
    inp, result = solve()
    assert_no_writes(prepare(inp, result, engine=RealEngine(delivery_enabled=True, as_of='2026-10-16T15:00:00+09:00')))
    inp.input_hash = 'bad'
    assert_no_writes(prepare(inp, result))


def test_new_booking_after_draft_is_revalidated_including_beyond_horizon():
    inp, result = solve()
    inp.snapshot['reservations'].append(dict(id='NEW-FUTURE', asset_id='P02', rental_id=None,
        start_at='2026-12-01T09:00:00+09:00', end_at=None, release_job_id=None,
        plan_id=None, status='ACTIVE', review_required=False))
    changes = prepare(inp, result)
    assert_no_writes(changes)
    assert any(v.code == 'ASSET_RESERVATION_OVERLAP' for v in changes.validation.violations)


def test_explicit_staff_override_is_validated_but_does_not_change_business_conditions():
    inp, result = solve(overrides=[{'job_id':'J-NEW','employee_id':'E2'}])
    assert next(p for p in result.candidate_items if p.job_id == 'J-NEW').employee_id == 'E2'
    assert prepare(inp, result).validation.status == 'VALID'
    for override in ({'job_id':'J-PREP1','employee_id':'E2'}, {'job_id':'UNKNOWN','employee_id':'E2'},
        {'job_id':'J-NEW','start_at':'2026-10-16T15:00:00+09:00'}):
        r = RealEngine(delivery_enabled=True).solve(request(operations=[operation()], overrides=[override]))
        assert r.status != 'FEASIBLE' and not r.candidate_items


def draft_with_reference_binding(admin, monkeypatch, *, conditional=False):
    from rentwise.services import plans
    normalize = plans._normalize
    def bound(conn, intent, snapshot):
        ops, inherited = normalize(conn, intent, snapshot)
        for op in ops:
            op.allocation = operation()['allocation']
            op.return_policy = 'FIXED'  # Explicit human-reviewed date below; never infer OPEN_ENDED from missing data.
        return ops, inherited
    monkeypatch.setattr(plans, '_normalize', bound)
    monkeypatch.setattr(plans, 'get_engine', lambda: RealEngine(delivery_enabled=True))
    req = admin.post('/api/v1/requests', json={'source_customer_id':'C-S', 'text':'프린터 1대 신규 납품'}).json()
    op = {k:v for k,v in operation(return_policy='FIXED', rental_end_at='2026-10-20T10:00:00+09:00').items()
        if k in c.Operation.model_fields}
    op['evidence'] = []
    if conditional: op['asset_ids'] = ['P01']
    saved = admin.put(f"/api/v1/requests/{req['id']}/interpretation", json={'expected_request_revision':1,
        'payload':{'schema_version':'rental.intent.v1','operations':[op],'needs_confirmation':[]}, 'acknowledged_paths':[]})
    assert saved.status_code == 200, saved.text
    draft = admin.post('/api/v1/plans', json={'request_id':req['id'],
        'interpretation_revision':saved.json()['interpretation']['revision'], 'base_state_revision':7})
    assert draft.status_code == 201 and draft.json()['status'] == 'READY', draft.text
    return draft.json()


def test_existing_b_can_store_draft_but_requires_new_job_display_and_confirm_hooks(admin, monkeypatch):
    from rentwise.db import database
    with database.get_db_engine().connect() as conn: before = database.read_snapshot(conn)
    draft = draft_with_reference_binding(admin, monkeypatch)
    added = next(d for d in draft['diff'] if d['job_id'] == 'J-NEW')
    assert added['before'] is None and added['after']['asset_ids'] == ['P02']
    # Existing view has no job metadata until B overlays A's prepared job_creates.
    assert added['kind'] is None and added['site_id'] is None
    assert draft['solver_version'] == delivery.VERSION and not draft['is_mock']
    blocked = admin.post(f"/api/v1/plans/{draft['id']}/confirm", json={'expected_plan_revision':1,'base_state_revision':7})
    assert blocked.status_code == 422 and blocked.json()['error']['code'] == 'CONSTRAINT_VIOLATION', blocked.text
    with database.get_db_engine().connect() as conn: assert database.read_snapshot(conn) == before


class SimulatedFailure(Exception): pass


def reference_write(conn, changes, pid, *, fail_after_job=False):
    """Test-only B SQL adapter. Use only freshly recomputed validated changes."""
    from sqlalchemy import insert, update
    from rentwise.db import tables as T
    from rentwise.db.database import J
    from rentwise.timeutil import to_db
    assert changes.validation.status == 'VALID'
    for job in changes.job_creates:
        d = dict(job); d['asset_ids_json'] = J(d.pop('asset_ids'))
        for key in ('window_start','window_end','due_at','rental_end_at'): d[key] = to_db(d[key])
        conn.execute(insert(T.jobs).values(**d))
    if fail_after_job: raise SimulatedFailure()
    for rental in changes.rental_creates:
        d = dict(rental)
        for key in ('actual_start','actual_end','expected_return_at'): d[key] = to_db(d[key])
        conn.execute(insert(T.rentals).values(**d))
    for dep in changes.dependency_creates: conn.execute(insert(T.dependencies).values(**dep))
    for ch in changes.reservation_changes:
        d = dict(ch.reservation, plan_id=pid)
        for key in ('start_at','end_at'): d[key] = to_db(d[key])
        conn.execute(insert(T.reservations).values(**d))
    for jid, d in changes.job_updates.items():
        conn.execute(update(T.jobs).where(T.jobs.c.id == jid).values(asset_ids_json=J(d['asset_ids']), revision=T.jobs.c.revision+1))


@pytest.mark.parametrize('conditional', [False, True])
@pytest.mark.parametrize('failure', ['none', 'after_job', 'after_finish'])
def test_reference_transaction_persists_new_business_rows_and_rolls_back_atomically(admin, monkeypatch, failure, conditional):
    from sqlalchemy import delete, select
    from rentwise.db import database, tables as T
    from rentwise.services import plans
    from rentwise.timeutil import now
    if conditional:
        # Test-only scenario without an already-promised followup delivery. Never change C's fixture.
        with database.get_db_engine().begin() as conn:
            conn.execute(delete(T.plan_items).where(T.plan_items.c.job_id == 'J-DEL1'))
            conn.execute(delete(T.dependencies).where(T.dependencies.c.successor_job_id == 'J-DEL1'))
            conn.execute(delete(T.reservations).where(T.reservations.c.id == 'RS-S2'))
            conn.execute(delete(T.jobs).where(T.jobs.c.id == 'J-DEL1'))
    draft = draft_with_reference_binding(admin, monkeypatch, conditional=conditional); pid = draft['id']
    def state(conn):
        return (database.read_snapshot(conn), dict(conn.execute(select(T.workspace_state)).one()._mapping),
            [dict(r._mapping) for r in conn.execute(select(T.requests))],
            [dict(r._mapping) for r in conn.execute(select(T.audit_log))])
    with database.get_db_engine().connect() as conn: before = state(conn)
    try:
        with database.get_db_engine().begin() as conn:
            conn.exec_driver_sql('PRAGMA foreign_keys=ON')
            ws = plans._ws(conn, lock=True); p = plans._plan(conn, pid)
            assert ws.state_revision == p.base_state_revision == 7
            snap = database.read_snapshot(conn)
            changes = RealEngine(delivery_enabled=True).prepare_delivery_confirmation(snap,
                json.loads(p.operations_json), list(plans._items(conn,pid).values()),
                json.loads(p.result_json)['reservation_changes'], request_id=p.request_id, input_hash=p.input_hash)
            assert changes.validation.status == 'VALID', changes
            reference_write(conn, changes, pid, fail_after_job=failure == 'after_job')
            plans._finish_confirm(conn, ws, p, pid, 'admin', 'reference-delivery', now())
            if failure == 'after_finish': raise SimulatedFailure()
    except SimulatedFailure: pass
    with database.get_db_engine().connect() as conn: after = state(conn)
    if failure != 'none':
        assert after == before
        return
    snap, workspace, requests, audit = after
    assert workspace['current_plan_id'] == pid and workspace['state_revision'] == 8
    assert requests[0]['status'] == 'CONFIRMED' and audit[-1]['action'] == 'PLAN_CONFIRM'
    assert len(snap['jobs']) == len(before[0]['jobs'])+1
    assert len(snap['rentals']) == len(before[0]['rentals'])+1
    assert len(snap['reservations']) == len(before[0]['reservations'])+1
    assert len(snap['dependencies']) == len(before[0]['dependencies'])+int(conditional)
    assert snap['assets'] == before[0]['assets']
    assert RealEngine().validate(snap, snap['plan_items']).status == 'VALID'
    a = RealEngine().availability(c.AvailabilityInput(snapshot=snap,from_at='2026-10-16T15:00:00+09:00',
        to_at='2026-10-16T18:00:00+09:00',base_state_revision=8))
    assert a.status == 'OK' and all(('P01' if conditional else 'P02') in w.unavailable_asset_ids for w in a.windows if w.item_id == 'PR-A')
