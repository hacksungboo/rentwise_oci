"""Intraday status feedback on existing v1/v2 contracts; no execution API fakes."""
from copy import deepcopy

import pytest

from rentwise.contracts import types as c
from rentwise.engine import RealEngine, solve as solve_v2, validate as validate_v2
from rentwise.engine import execution, v1
from .test_compat import public_snapshot, request
from .test_delivery import operation, prepare, assert_no_writes
from .sample import snapshot, t, availability_input
from .solver_sample import solver_input, normal_operation, delay_operation


def day(status='COMPLETED', employee='E1'):
    s = public_snapshot()
    s['jobs'] = [j for j in s['jobs'] if j['id'] == 'J-AS1']
    s['jobs'][0]['status'] = status
    s['plan_items'] = [p for p in s['plan_items'] if p['job_id'] == 'J-AS1']
    s['plan_items'][0]['employee_id'] = employee
    s['rentals'], s['reservations'], s['dependencies'] = [], [], []
    return s


def new_request(s, **kw):
    return request(snapshot=s, operations=[operation()], overrides=[], **kw)


def codes(vr):
    return {v.code for v in vr.violations}


@pytest.mark.parametrize('status', ['COMPLETED', 'IN_PROGRESS', 'FAILED'])
def test_afternoon_addition_keeps_entire_frozen_row_and_actual_state(status):
    s = day(status); before = deepcopy(s)
    engine = RealEngine(as_of=t('13:00'), delivery_enabled=True)
    inp = new_request(s); result = engine.solve(inp)
    assert result.status == 'FEASIBLE', result
    old = next(p for p in result.candidate_items if p.job_id == 'J-AS1')
    assert v1.signature(old.model_dump()) == v1.signature(s['plan_items'][0])
    new = next(p for p in result.candidate_items if p.job_id == 'J-NEW')
    if status != 'COMPLETED':
        assert new.employee_id != 'E1'  # Even after its scheduled end, ongoing work isn't released.
    assert prepare(inp, result, engine=engine).validation.status == 'VALID'
    assert s == before


@pytest.mark.parametrize('status', ['COMPLETED', 'IN_PROGRESS', 'FAILED'])
@pytest.mark.parametrize('field', ['employee', 'time', 'asset', 'missing'])
def test_confirmation_rejects_any_frozen_assignment_change(status, field):
    s = day(status); rows = deepcopy(s['plan_items'])
    if field == 'employee': rows[0]['employee_id'] = 'E2'
    if field == 'time': rows[0]['start_at'] = t('09:45')
    if field == 'asset': rows[0]['asset_ids'] = ['W02']
    if field == 'missing': rows = []
    assert RealEngine(as_of=t('13:00')).validate(s, rows).status != 'VALID'


def test_overdue_unstarted_work_requires_feedback_not_rescheduling_from_the_past():
    s = day('ASSIGNED')
    e = RealEngine(as_of=t('10:00'), delivery_enabled=True)
    for inp in (new_request(s), request(snapshot=s, overrides=[{'job_id':'J-AS1','employee_id':'E2'}])):
        r = e.solve(inp)
        assert r.status == 'NEEDS_REVIEW' and r.unresolved[0].code == 'EXECUTION_STATUS_REQUIRED'
        assert not r.candidate_items and not r.reservation_changes
    assert 'EXECUTION_STATUS_REQUIRED' in codes(e.validate(s, s['plan_items']))
    # Feedback, not time manipulation, clears the block.
    s['jobs'][0]['status'] = 'COMPLETED'
    assert e.solve(new_request(s)).status == 'FEASIBLE'


def test_exact_start_is_not_stale_but_one_second_later_is():
    s = day('ASSIGNED')
    assert execution.stale_jobs(s, t('09:40')) == []
    assert execution.stale_jobs(s, '2026-10-16T09:40:01+09:00') == ['J-AS1']
    assert execution.stale_jobs(s, '2026-10-16T00:40:01Z') == ['J-AS1']


def test_future_as_staff_change_after_completed_morning_preserves_history():
    s = day()
    original = public_snapshot()
    for name, key in [('jobs', 'id'), ('plan_items', 'job_id')]:
        s[name].extend(r for r in original[name] if r[key] == 'J-AS2')
    for shift in s['shifts']:
        if shift['employee_id'] == 'E3': shift['break_windows'] = []
    inp = request(snapshot=s, overrides=[{'job_id':'J-AS2','employee_id':'E3'}])
    e = RealEngine(as_of=t('13:00'))
    r = e.solve(inp)
    assert r.status == 'FEASIBLE', r
    assert next(p for p in r.candidate_items if p.job_id == 'J-AS2').employee_id == 'E3'
    assert e.validate(s, r.candidate_items).status == 'VALID'
    assert v1.signature(next(p.model_dump() for p in r.candidate_items if p.job_id == 'J-AS1')) == v1.signature(s['plan_items'][0])


def test_locked_confirmation_rechecks_employee_started_since_draft_and_returns_no_writes():
    s = day('ASSIGNED'); clock = [t('09:00')]
    e = RealEngine(as_of=lambda: clock[0], delivery_enabled=True)
    inp = new_request(s); r = e.solve(inp)
    assert r.status == 'FEASIBLE'
    assert next(p for p in r.candidate_items if p.job_id == 'J-NEW').employee_id == 'E1'
    # The database snapshot has changed since draft; A reads current status.
    inp.snapshot['jobs'][0]['status'] = 'IN_PROGRESS'
    clock[0] = t('10:00')
    changes = prepare(inp, r, engine=e)
    assert_no_writes(changes)
    assert 'EMPLOYEE_EXECUTION_IN_PROGRESS' in codes(changes.validation)


def test_confirmation_rechecks_clock_even_when_workspace_revision_has_not_changed():
    clock = [t('13:00')]; e = RealEngine(as_of=lambda: clock[0], delivery_enabled=True)
    inp = new_request(day()); r = e.solve(inp)
    assert r.status == 'FEASIBLE'
    clock[0] = t('14:41')
    changes = prepare(inp, r, engine=e)
    assert_no_writes(changes)
    assert 'DELIVERY_DEPARTURE_PASSED' in codes(changes.validation)


def test_legacy_two_argument_validate_reads_fresh_clock_and_blocks_stale_as_draft():
    clock = [t('09:00')]; s = day('ASSIGNED')
    e = RealEngine(as_of=lambda: clock[0])
    r = e.solve(request(snapshot=s, overrides=[{'job_id':'J-AS1','employee_id':'E2'}]))
    assert r.status == 'FEASIBLE', r
    clock[0] = t('09:41')
    assert 'EXECUTION_FIXED_JOB_CHANGED' in codes(e.validate(s, r.candidate_items))
    clock[0] = 'invalid'
    assert e.validate(s, r.candidate_items).status == 'DATA_MISSING'


def test_in_progress_asset_never_becomes_ready_from_scheduled_end_or_physical_flag():
    s = day('IN_PROGRESS')
    # Inconsistent physical feed must not advertise this asset as available.
    asset = next(a for a in s['assets'] if a['id'] == 'W01')
    asset.update(physical_state='READY_WAREHOUSE', location_id='L-W')
    r = RealEngine(as_of=t('13:00')).availability(c.AvailabilityInput(snapshot=s,
        from_at=t('14:00'), to_at=t('18:00'), base_state_revision=7))
    assert r.status == 'OK'
    assert all('W01' not in w.ready_asset_ids and all(a.asset_id != 'W01' for a in w.conditional_assets) for w in r.windows)
    assert any('W01' in w.unavailable_asset_ids for w in r.windows)


def test_no_available_employee_returns_empty_candidate_instead_of_reusing_busy_employee():
    s = day('IN_PROGRESS')
    for emp in s['employees']: emp['active'] = emp['id'] == 'E1'
    r = RealEngine(as_of=t('13:00'), delivery_enabled=True).solve(new_request(s))
    assert r.status == 'NO_SOLUTION_FOUND' and not r.candidate_items and not r.reservation_changes
    assert 'EMPLOYEE_EXECUTION_IN_PROGRESS' in {v.code for v in r.violations}


def test_current_travel_cannot_be_paid_by_time_before_the_request():
    s = day(); row = deepcopy(s['plan_items'][0])
    row.update(job_id='NEW', employee_id='E2', start_at=t('14:00'), end_at=t('14:40'))
    row['segments'] = [dict(kind='SERVICE', from_id='L-B', to_id='L-B', start_at=t('14:00'), end_at=t('14:40'))]
    # Shift started at 09:00, but at 13:59 the worker cannot already be at L-B.
    assert 'EMPLOYEE_CURRENT_TRAVEL_GAP' in {c for c, _, _ in execution.violations(s, s['plan_items']+[row], t('13:59'))}
    assert list(execution.violations(s, s['plan_items']+[row], t('13:00'))) == []


def progressed_v2():
    s = snapshot()
    s['as_of'] = t('12:40')
    for j in s['jobs']:
        j['status'] = 'IN_PROGRESS' if j['id'] == 'DEL' else 'COMPLETED'
    s['assets'][0].update(physical_state='AT_CUSTOMER', location_id='S')
    s['rentals'][0].update(status='CLOSED', actual_end=t('10:10'))
    s['rentals'][1].update(status='ACTIVE', actual_start=t('12:15'))
    return s


def test_v2_new_delivery_preserves_completed_and_ongoing_rows_and_selects_other_employee():
    s = progressed_v2(); before = deepcopy(s)
    op = normal_operation(s, start='15:00', end='15:15', due='17:00')
    r = solve_v2(solver_input(s, [op]))
    assert r['status'] == 'FEASIBLE', r
    assert next(p for p in r['candidate_items'] if p['job_id'] == 'NEW-DEL')['employee_id'] == 'E2'
    old = {p['job_id']:p for p in s['plan_items']}
    for p in r['candidate_items']:
        if p['job_id'] in old:
            assert execution._signature(p, 'segments_json') == execution._signature(old[p['job_id']], 'segments_json')
    assert validate_v2(s, r['candidate_plan'])['status'] == 'VALID'
    assert s == before
    # Replay under fresh as_of must reject even if state_revision was unchanged.
    s['as_of'] = t('15:00')
    vr = validate_v2(s, r['candidate_plan'])
    assert vr['status'] == 'INVALID'
    assert 'EXECUTION_START_PASSED' in {v['code'] for v in vr['violations']}


def test_v2_delayed_pickup_cannot_resurrect_past_unstarted_work():
    s = snapshot(); s['as_of'] = t('10:00')
    r = solve_v2(solver_input(s, [delay_operation(s)]))
    assert r['status'] == 'NEEDS_REVIEW'
    assert r['unresolved'][0]['code'] == 'EXECUTION_STATUS_REQUIRED'
    assert not r['candidate_items'] and r['candidate_plan'] is None


@pytest.mark.parametrize('status', ['COMPLETED', 'IN_PROGRESS', 'FAILED'])
def test_v2_frozen_pickup_rejects_rescheduling_even_with_customer_approval(status):
    s = snapshot(); s['jobs'][0]['status'] = status
    r = solve_v2(solver_input(s, [delay_operation(s)]))
    assert r['status'] == 'NEEDS_REVIEW' and not r['candidate_items']
    assert r['unresolved'][0]['code'] == 'FIXED_JOB_CHANGED'


@pytest.mark.parametrize('kind,jid,customer,item,asset,start,end', [
    ('AS','J-AS1','C-B','WP-A','W01','10:15','10:55'),
    ('PICKUP','J-PICK1','C-H','PR-A','P01','14:00','14:10'),
])
def test_existing_b_http_confirm_rejects_started_work_without_partial_writes(
        admin, monkeypatch, kind, jid, customer, item, asset, start, end):
    from sqlalchemy import select, update
    from rentwise.db import database, tables as T
    from rentwise.services import plans
    clock = [t('09:00')]
    eng = RealEngine(as_of=lambda: clock[0])
    monkeypatch.setattr(plans, 'get_engine', lambda: eng)
    # B's existing pickup bridge reads a separate clock; integrate both in test.
    monkeypatch.setattr(plans, '_as_of', lambda: clock[0])
    req = admin.post('/api/v1/requests', json={'source_customer_id':customer, 'text':'당일 변경'}).json()
    op = dict(operation='RESCHEDULE',kind=kind,target_job_id=jid,item_id=item,asset_ids=[asset],quantity=1,
        source_customer_id=customer,destination_customer_id=None,window_start=t(start),window_end=t(end),
        due_at=t('11:00') if kind == 'AS' else t('17:00'),rental_end_at=None,priority_hint='NORMAL',evidence=[])
    saved = admin.put(f"/api/v1/requests/{req['id']}/interpretation", json={'expected_request_revision':1,
        'payload':{'schema_version':'rental.intent.v1','operations':[op],'needs_confirmation':[]}, 'acknowledged_paths':[]})
    assert saved.status_code == 200, saved.text
    draft = admin.post('/api/v1/plans', json={'request_id':req['id'],
        'interpretation_revision':saved.json()['interpretation']['revision'], 'base_state_revision':7})
    assert draft.status_code == 201 and draft.json()['status'] == 'READY', draft.text
    pid = draft.json()['id']
    # Simulate the future B start-event writer using existing columns. Deliberately
    # leave workspace revision unchanged to exercise A's extra guard, not B's 409.
    with database.get_db_engine().begin() as conn:
        conn.execute(update(T.jobs).where(T.jobs.c.id == jid).values(status='IN_PROGRESS'))
    clock[0] = t('09:30')
    with database.get_db_engine().connect() as conn:
        before = database.read_snapshot(conn)
        before_ws = dict(conn.execute(select(T.workspace_state)).mappings().one())
        before_audit = list(conn.execute(select(T.audit_log)).mappings())
    response = admin.post(f'/api/v1/plans/{pid}/confirm', json={'expected_plan_revision':1,'base_state_revision':7})
    assert response.status_code == 422, response.text
    assert 'FIXED_JOB_CHANGED' in response.text
    with database.get_db_engine().connect() as conn:
        assert database.read_snapshot(conn) == before
        assert dict(conn.execute(select(T.workspace_state)).mappings().one()) == before_ws
        assert list(conn.execute(select(T.audit_log)).mappings()) == before_audit
        assert conn.execute(select(T.plans.c.status).where(T.plans.c.id == pid)).scalar_one() == 'READY'


def test_completed_endpoint_requires_fresh_travel_and_completion_order_is_not_guessed():
    s = day()
    # Endpoint after a completed service-only block can be a customer location.
    old = s['plan_items'][0]
    old['segments'] = [dict(kind='SERVICE', from_id='L-B', to_id='L-B', start_at=t('10:00'), end_at=t('10:40'))]
    old.update(start_at=t('10:00'), end_at=t('10:40'))
    new = deepcopy(old)
    new.update(job_id='NEW', start_at=t('15:00'), end_at=t('15:15'))
    new['segments'] = [dict(kind='SERVICE', from_id='L-W', to_id='L-W', start_at=t('15:00'), end_at=t('15:15'))]
    assert 'EMPLOYEE_CURRENT_TRAVEL_GAP' in {c for c, _, _ in execution.violations(s, [old,new], t('14:59'))}
    assert list(execution.violations(s, [old,new], t('14:00'))) == []
    completed = deepcopy(old); completed.update(job_id='DONE2', start_at=t('11:00'), end_at=t('11:15'))
    completed['segments'] = [dict(kind='SERVICE', from_id='L-W', to_id='L-W', start_at=t('11:00'), end_at=t('11:15'))]
    s['jobs'].append(dict(s['jobs'][0], id='DONE2'))
    s['plan_items'].append(completed)
    # Planned order does not prove actual completion order. Both endpoints count.
    assert 'EMPLOYEE_CURRENT_TRAVEL_GAP' in {c for c, _, _ in execution.violations(s, [old,completed,new], t('14:59'))}


def test_history_ids_and_reason_labels_can_be_rebound_without_changing_execution():
    s = day(); row = deepcopy(s['plan_items'][0])
    row.update(id='NEW-PLAN-ROW', plan_id='NEW-PLAN', reason_codes=['HISTORY_PRESERVED'])
    assert list(execution.violations(s, [row], t('13:00'))) == []
    assert RealEngine(as_of=t('13:00')).validate(s, [row]).status == 'VALID'


def test_v2_availability_does_not_release_an_ongoing_asset_with_no_later_jobs():
    from rentwise.engine import availability
    s = snapshot()
    s['jobs'] = s['jobs'][:1]; s['jobs'][0]['status'] = 'IN_PROGRESS'
    s['plan_items'] = s['plan_items'][:1]
    s['rentals'], s['reservations'], s['dependencies'] = [], [], []
    s['assets'][0].update(physical_state='READY_WAREHOUSE', location_id='W')
    s['as_of'] = t('13:00')
    r = availability(availability_input(s, '14:00', '18:00'))
    assert r['status'] == 'OK', r
    assert all('P01' in w['unavailable_asset_ids'] for w in r['windows'])


def test_native_recovery_prepare_also_rechecks_clock_and_returns_no_writes():
    from .test_recovery import operation as pickup_operation
    clock = [t('09:00')]
    engine = RealEngine(as_of=lambda: clock[0], recovery_enabled=True)
    inp = request(operations=[pickup_operation()])
    r = engine.solve(inp)
    assert r.status == 'FEASIBLE', r
    clock[0] = t('13:41')
    changes = engine.prepare_confirmation(inp.snapshot, inp.operations, r.candidate_items,
        r.reservation_changes, input_hash=inp.input_hash)
    assert changes.validation.status == 'INVALID'
    assert 'EXECUTION_STATUS_REQUIRED' in codes(changes.validation)
    assert not changes.job_updates and not changes.rental_updates and not changes.dependency_deletions and not changes.reservation_changes
    clock[0] = 'invalid'
    assert engine.prepare_confirmation(inp.snapshot, inp.operations, r.candidate_items,
        r.reservation_changes, input_hash=inp.input_hash).validation.status == 'DATA_MISSING'


def test_native_recovery_cannot_reschedule_elapsed_unconfirmed_work():
    from .test_recovery import operation as pickup_operation
    r = RealEngine(as_of=t('10:00'), recovery_enabled=True).solve(request(operations=[pickup_operation()]))
    assert r.status == 'NEEDS_REVIEW' and r.unresolved[0].code == 'EXECUTION_STATUS_REQUIRED'
    assert not r.candidate_items and not r.reservation_changes


def test_both_opt_in_modes_dispatch_without_changing_default_b_v2_path():
    from rentwise.engine import recovery, delivery
    from .test_recovery import operation as pickup_operation
    engine = RealEngine(recovery_enabled=True, delivery_enabled=True)
    r = engine.solve(request(operations=[pickup_operation()]))
    assert r.status == 'FEASIBLE' and r.solver_version == recovery.VERSION
    r = engine.solve(request(operations=[operation()], overrides=[]))
    assert r.status == 'FEASIBLE' and r.solver_version == delivery.VERSION
    r = engine.solve(request(operations=[operation(), pickup_operation()], overrides=[]))
    assert r.status == 'NEEDS_REVIEW' and not r.candidate_items and not r.reservation_changes
