"""Unchanged B v1 service/DTO contract; real seed and real temp-DB writes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from rentwise.contracts import types as c
from rentwise.engine import RealEngine
from rentwise.engine.v1 import TABLES


def public_snapshot():
    seed=json.loads((Path(__file__).resolve().parents[3]/'fixtures/v1/seed.json').read_text())
    return {k:deepcopy(seed[k]) for k in TABLES}


def request(snapshot=None, operations=None, overrides=None, **changes):
    body=dict(request_id='REQ-V1',interpretation_revision=1,base_plan_id='PL-007',base_state_revision=7,
        horizon_start='2026-10-16T00:00:00+09:00',horizon_end='2026-10-23T00:00:00+09:00',
        dataset_version='rental-dev-v1',policy_version='policy-v1',travel_version='travel-v1',
        snapshot=snapshot or public_snapshot(),operations=operations or [],
        overrides=overrides if overrides is not None else [{'job_id':'J-AS2','employee_id':'E2'}],
        max_search_ms=2000,max_candidates=1000)
    body.update(changes)
    body['operations']=[c.NormalizedOperation.model_validate(op).model_dump() for op in body['operations']]
    body['input_hash']='sha256:'+hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return c.SolverInput(**body)


@pytest.fixture()
def real_registry(monkeypatch):
    from dataclasses import replace
    from rentwise import engine_registry
    monkeypatch.setattr(engine_registry,'settings',replace(engine_registry.settings,engine_mode='real'))
    engine_registry.get_engine.cache_clear()
    try:
        yield engine_registry.get_engine()
    finally:
        engine_registry.get_engine.cache_clear()


def solve():
    inp=request(); result=RealEngine().solve(inp)
    assert result.status=='FEASIBLE',result
    return inp,result


def test_no_argument_entry_point_uses_existing_b_clock_and_exact_b_dtos():
    engine=RealEngine()
    assert engine._clock()=='2026-10-16T09:00:00+09:00'
    inp,result=solve()
    assert type(result) is c.SolverResult
    assert c.SolverResult.model_validate_json(result.model_dump_json())==result
    assert result.input_hash==inp.input_hash
    assert result.reservation_changes==[]
    assert 'candidate_plan' not in result.model_dump()
    rows={p.job_id:p for p in result.candidate_items}
    assert rows['J-AS2'].employee_id=='E2'
    assert all(p.id is None and p.plan_id is None for p in result.candidate_items)
    assert RealEngine().validate(inp.snapshot,result.candidate_items).status=='VALID'


def test_actual_b_seed_nullable_rental_ids_are_supported_without_fabrication():
    snap=public_snapshot(); before=deepcopy(snap)
    inp=c.AvailabilityInput(snapshot=snap,from_at='2026-10-16T00:00:00+09:00',to_at='2026-10-16T18:00:00+09:00',base_state_revision=7)
    result=RealEngine().availability(inp)
    assert type(result) is c.AvailabilityResult and result.status=='OK'
    assert sum(p.count for p in result.physical_counts)==12
    assert snap==before
    assert sum(r['rental_id'] is None for r in snap['reservations'])==3
    # B seed fix (2026-10-17): J-AS2 moved to E2, so the base plan no longer crosses E1's break.
    checked=RealEngine().validate(snap,[c.PlanItem(**p) for p in snap['plan_items']])
    assert checked.status=='VALID',checked.violations


def test_staff_candidate_keeps_job_conditions_asset_actuals_and_all_other_rows():
    inp,result=solve(); before=deepcopy(inp.snapshot)
    old={p['job_id']:p for p in inp.snapshot['plan_items']}
    for p in result.candidate_items:
        data=p.model_dump(); data['id']=old[p.job_id]['id']; data['plan_id']=old[p.job_id]['plan_id']
        if p.job_id=='J-AS2':
            data['employee_id']=old[p.job_id]['employee_id']; data['reason_codes']=old[p.job_id]['reason_codes']
        assert data==old[p.job_id]
    assert inp.snapshot==before


def test_delay_requires_review_with_empty_candidate_and_no_partial_writes():
    op=dict(operation='RESCHEDULE',kind='PICKUP',target_job_id='J-PICK1',
        window_start='2026-10-16T14:00:00+09:00',window_end='2026-10-16T14:10:00+09:00',due_at='2026-10-16T17:00:00+09:00')
    r=RealEngine().solve(request(operations=[op]))
    assert r.status=='NEEDS_REVIEW'
    assert r.unresolved[0].code=='B_V1_PERSISTENCE_UNSUPPORTED'
    assert r.candidate_items==[] and r.reservation_changes==[]


@pytest.mark.parametrize('override',[
    {'job_id':'J-DEL1','asset_ids':['P02']},
    {'job_id':'J-PICK1','start_at':'2026-10-16T14:00:00+09:00'},
    {'job_id':'J-TR1','start_at':'2026-10-18T11:30:00+09:00'},
    {'job_id':'J-AS1','start_at':'2026-10-16T10:15:00+09:00'},
    {'job_id':'J-PREP1','employee_id':'E2'},
    {'job_id':'UNKNOWN','employee_id':'E2'},
    {'job_id':'J-AS2','surprise':True},
])
def test_unpersistable_or_unknown_overrides_never_emit_a_candidate(override):
    r=RealEngine().solve(request(overrides=[override]))
    assert r.status=='NEEDS_REVIEW' and r.candidate_items==[]


def test_new_jobs_cannot_be_ready_in_b_v1():
    op=dict(operation='CREATE',kind='DELIVERY',target_job_id=None)
    r=RealEngine().solve(request(operations=[op]))
    assert r.status=='NEEDS_REVIEW' and r.candidate_items==[]


def test_as_time_move_inside_existing_promise_is_supported():
    op=dict(operation='RESCHEDULE',kind='AS',target_job_id='J-AS1',
        window_start='2026-10-16T10:15:00+09:00',window_end='2026-10-16T10:55:00+09:00',due_at='2026-10-16T11:00:00+09:00')
    inp=request(operations=[op])
    result=RealEngine().solve(inp)
    assert result.status=='FEASIBLE', result
    p=next(p for p in result.candidate_items if p.job_id=='J-AS1')
    assert next(s for s in p.segments if s.kind=='SERVICE').start_at=='2026-10-16T10:15:00+09:00'
    assert RealEngine().validate(inp.snapshot,result.candidate_items).status=='VALID'


@pytest.mark.parametrize('change', ['omit','duplicate','asset','employee','duration','due','window','frozen','travel','dependency'])
def test_two_argument_validator_blocks_invalid_stored_rows(change):
    inp,result=solve(); snap=deepcopy(inp.snapshot); rows=[p.model_copy(deep=True) for p in result.candidate_items]
    p=next(p for p in rows if p.job_id=='J-AS1')
    if change=='omit': rows.pop()
    elif change=='duplicate': rows.append(rows[0])
    elif change=='asset': p.asset_ids=['W04']
    elif change=='employee': p.employee_id='UNKNOWN'
    elif change=='duration': p.segments[1].end_at=p.segments[1].start_at
    elif change=='due': next(j for j in snap['jobs'] if j['id']=='J-AS1')['due_at']='2026-10-16T09:00:00+09:00'
    elif change=='window': next(j for j in snap['jobs'] if j['id']=='J-AS1')['window_start']='2026-10-16T10:45:00+09:00'
    elif change=='frozen':
        next(j for j in snap['jobs'] if j['id']=='J-AS2')['status']='IN_PROGRESS'
    elif change=='travel': p.segments[0].start_at=p.segments[0].end_at; p.start_at=p.segments[0].start_at
    elif change=='dependency': snap['dependencies'].append(dict(id='D-CYCLE',predecessor_job_id='J-DEL1',successor_job_id='J-PICK1',minimum_gap_minutes=0,reason='TEST'))
    assert RealEngine().validate(snap,rows).status in ('INVALID','DATA_MISSING')


def test_old_snapshot_and_bad_limits_or_hash_fail_without_search_success():
    inp=request(); inp.input_hash='sha256:'+'0'*64
    assert RealEngine().solve(inp).status=='DATA_MISSING'
    for changes in ({'max_candidates':0},{'max_search_ms':3000},{'horizon_end':'2027-01-01T00:00:00+09:00'}):
        assert RealEngine().solve(request(**changes)).status=='DATA_MISSING'
    assert RealEngine().solve(request(base_plan_id='OLD')).status=='NEEDS_REVIEW'
    assert RealEngine().solve(request(overrides=[{}])).status=='DATA_MISSING'


def test_search_budget_miss_does_not_claim_impossibility():
    r=RealEngine().solve(request(overrides=[{'job_id':'J-AS2','employee_id':'E1'}],max_candidates=1))
    assert r.status=='NO_SOLUTION_FOUND'
    assert r.candidate_items==[]


def test_missing_real_travel_is_data_missing_but_diagonal_is_optional():
    s=public_snapshot(); s['travel_times'].pop()
    assert RealEngine().solve(request(snapshot=s)).status=='DATA_MISSING'
    assert RealEngine().validate(s,[c.PlanItem(**p) for p in s['plan_items']]).status=='DATA_MISSING'


def test_interpret_is_explicit_error_until_a_model_is_supplied(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    inp=c.InterpretationInput(request_id='R',request_revision=1,received_at='2026-10-16T09:00:00+09:00',text='회수',
        source_customer_id=None,candidate_customers=[],candidate_items=[])
    r=RealEngine().interpret(inp)
    assert type(r) is c.InterpretationResult and r.status=='ERROR' and r.error.code=='AI_NOT_CONFIGURED'
    assert r.call.attempts==0


@pytest.mark.parametrize('scenario',['staff','as_time'])
def test_b_api_confirm_and_requery_work_without_service_changes_or_context(admin,real_registry,scenario):
    from sqlalchemy import select
    from rentwise.db import database,tables as T
    assert admin.get('/api/v1/operations').json()['availability']['status']=='OK'
    r=admin.post('/api/v1/requests',json={'source_customer_id':'C-D','text':'담당 직원 변경 요청'})
    assert r.status_code==201; rid=r.json()['id']
    # B already permits direct human review, no model/fake extraction involved.
    ops=[]
    if scenario=='as_time':
        ops=[dict(operation='RESCHEDULE',kind='AS',target_job_id='J-AS1',item_id='WP-A',asset_ids=['W01'],quantity=1,
            source_customer_id='C-B',destination_customer_id=None,window_start='2026-10-16T10:15:00+09:00',
            window_end='2026-10-16T10:55:00+09:00',due_at='2026-10-16T11:00:00+09:00',rental_end_at=None,priority_hint='NORMAL',evidence=[])]
    r=admin.put(f'/api/v1/requests/{rid}/interpretation',json={'expected_request_revision':1,
        'payload':{'schema_version':'rental.intent.v1','operations':ops,'needs_confirmation':[]},'acknowledged_paths':[]})
    assert r.status_code==200,r.text
    with database.get_db_engine().connect() as conn:
        old=database.read_snapshot(conn)
    r=admin.post('/api/v1/plans',json={'request_id':rid,'interpretation_revision':r.json()['interpretation']['revision'],
        'base_state_revision':7,'overrides':[{'job_id':'J-AS2','employee_id':'E2'}]})
    assert r.status_code==201 and r.json()['status']=='READY',r.text
    pid=r.json()['id']
    assert not r.json()['is_mock']
    with database.get_db_engine().connect() as conn:
        assert database.read_snapshot(conn)==old
        meta=json.loads(conn.execute(select(T.plans.c.result_json).where(T.plans.c.id==pid)).scalar_one())
        assert 'candidate_plan' not in meta and 'snapshot_metadata' not in meta
    r=admin.post(f'/api/v1/plans/{pid}/confirm',json={'expected_plan_revision':1,'base_state_revision':7},headers={'Idempotency-Key':'v1-confirm'})
    assert r.status_code==200,r.text
    repeated=admin.post(f'/api/v1/plans/{pid}/confirm',json={'expected_plan_revision':1,'base_state_revision':7},headers={'Idempotency-Key':'v1-confirm'})
    assert repeated.json()==r.json()
    with database.get_db_engine().connect() as conn:
        latest=database.read_snapshot(conn)
    assert latest['rentals']==old['rentals'] and latest['reservations']==old['reservations'] and latest['dependencies']==old['dependencies']
    assert latest['assets']==old['assets']
    if scenario=='as_time':
        assert next(j for j in latest['jobs'] if j['id']=='J-AS1')['window_start']=='2026-10-16T10:15:00+09:00'
    assert RealEngine().validate(latest,[c.PlanItem(**p) for p in latest['plan_items']]).status=='VALID'
    view=admin.get('/api/v1/operations').json()
    assert view['workspace']['state_revision']==8 and view['workspace']['current_plan_id']==pid
    tomorrow=admin.get('/api/v1/operations?date=2026-10-17').json()
    assert any(p['job_id']=='J-AS2' for e in tomorrow['employees'] if e['id']=='E2' for p in e['items'])
    second=admin.post(f'/api/v1/plans/{pid}/confirm',json={'expected_plan_revision':1,'base_state_revision':8})
    assert second.status_code==409


def test_existing_registry_can_construct_real_engine_without_new_arguments(monkeypatch):
    from dataclasses import replace
    from rentwise import engine_registry
    monkeypatch.setattr(engine_registry,'settings',replace(engine_registry.settings,engine_mode='real'))
    engine_registry.get_engine.cache_clear()
    try:
        engine=engine_registry.get_engine()
        assert type(engine) is RealEngine
        assert engine.solve(request()).status=='FEASIBLE'
    finally:
        engine_registry.get_engine.cache_clear()


def test_as_window_cannot_expand_old_promise_or_change_asset_fields():
    for change in ({'window_start':'2026-10-16T08:00:00+09:00'}, {'asset_ids':['W04']}):
        op=dict(operation='RESCHEDULE',kind='AS',target_job_id='J-AS1',window_start='2026-10-16T10:00:00+09:00',
            window_end='2026-10-16T11:00:00+09:00',due_at='2026-10-16T11:00:00+09:00')
        op.update(change)
        r=RealEngine().solve(request(operations=[op]))
        assert r.status=='NEEDS_REVIEW' and r.candidate_items==[]


def test_ready_count_and_conditional_boundary_respect_bookings_and_preparation():
    snapshot=public_snapshot()
    inp=c.AvailabilityInput(snapshot=snapshot,from_at='2026-10-16T09:00:00+09:00',to_at='2026-10-16T12:00:00+09:00',base_state_revision=7)
    result=RealEngine().availability(inp)
    windows=[w for w in result.windows if w.item_id=='PR-A']
    before=next(w for w in windows if w.from_at=='2026-10-16T09:00:00+09:00')
    ready=next(w for w in windows if w.from_at=='2026-10-16T11:00:00+09:00')
    used=next(w for w in windows if w.from_at=='2026-10-16T11:40:00+09:00')
    assert 'P01' in before.unavailable_asset_ids
    assert 'P02' in before.ready_asset_ids
    assert any(a.asset_id=='P01' for a in ready.conditional_assets)
    assert 'P01' in used.unavailable_asset_ids
    assert snapshot==inp.snapshot


def test_real_b_delay_request_uses_v2_core_and_confirm_writes_full_candidate(admin,real_registry):
    from rentwise.db import database
    with database.get_db_engine().connect() as conn: before=database.read_snapshot(conn)
    req=admin.post('/api/v1/requests',json={'source_customer_id':'C-H','text':'회수 지연'}).json()
    op=dict(operation='RESCHEDULE',kind='PICKUP',target_job_id='J-PICK1',item_id='PR-A',asset_ids=['P01'],quantity=1,
        source_customer_id='C-H',destination_customer_id=None,window_start='2026-10-16T14:00:00+09:00',
        window_end='2026-10-16T14:10:00+09:00',due_at='2026-10-16T17:00:00+09:00',rental_end_at=None,priority_hint='NORMAL',evidence=[])
    saved=admin.put(f"/api/v1/requests/{req['id']}/interpretation",json={'expected_request_revision':1,
        'payload':{'schema_version':'rental.intent.v1','operations':[op],'needs_confirmation':[]},'acknowledged_paths':[]})
    assert saved.status_code==200,saved.text
    draft=admin.post('/api/v1/plans',json={'request_id':req['id'],'interpretation_revision':saved.json()['interpretation']['revision'],'base_state_revision':7})
    # B v2 bridge (2026-10-17): delayed pickup goes through A's v2 core, not the v1 compat solver.
    assert draft.status_code==201 and draft.json()['status']=='READY',draft.text
    assert draft.json()['solver_version']=='rental-solver-normal-delay-v2'
    with database.get_db_engine().connect() as conn: assert database.read_snapshot(conn)==before  # draft writes nothing
    done=admin.post(f"/api/v1/plans/{draft.json()['id']}/confirm",json={'expected_plan_revision':1,'base_state_revision':7})
    assert done.status_code==200,done.text
    with database.get_db_engine().connect() as conn: after=database.read_snapshot(conn)
    jobs={j['id']:j for j in after['jobs']}; rentals={r['id']:r for r in after['rentals']}
    assert jobs['J-PICK1']['window_start']=='2026-10-16T14:00:00+09:00'
    assert jobs['J-DEL1']['asset_ids']==['P02'] and rentals['R-S2']['asset_id']=='P02'
    assert not any(d['id']=='D-PREP1-DEL1' for d in after['dependencies'])
