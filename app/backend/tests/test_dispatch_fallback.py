"""Manager-reviewed dispatch alternatives; real solver/SQLite, no paid clients."""
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select, update

from rentwise.db import database, tables as T
from rentwise.db.database import J
from rentwise.engine import RealEngine, quick
from rentwise.services import plans
from rentwise.timeutil import to_db
from tests.test_real_mode import delay_intent
from tests.test_request_queue import snapshot


@pytest.fixture()
def real_planner(admin, monkeypatch):
    monkeypatch.setattr(plans, 'get_engine', lambda: RealEngine(as_of='2026-10-16T09:00:00+09:00'))
    return admin


def shorten_today(end):
    with database.get_db_engine().begin() as conn:
        conn.execute(update(T.shifts).where(T.shifts.c.start_at < to_db('2026-10-17T00:00:00+09:00'))
                     .values(end_at=to_db(f'2026-10-16T{end}:00+09:00')))


def request_plan(c, kind='DELIVERY', start='17:00', end='17:15', due='17:15', revision=7, overrides=None, busy=False,
                 queued=None):
    payload = delay_intent()
    op = payload['operations'][0]
    customer = 'C-S' if kind == 'DELIVERY' else 'C-J'
    op.update(kind=kind, target_job_id='J-DEL1' if kind == 'DELIVERY' else 'J-PICK2',
              item_id='PR-A' if kind == 'DELIVERY' else 'NB-A', asset_ids=['P01'] if kind == 'DELIVERY' else ['N04'],
              source_customer_id=None if kind == 'DELIVERY' else customer,
              destination_customer_id=customer if kind == 'DELIVERY' else None,
              window_start=f'2026-10-16T{start}:00+09:00', window_end=f'2026-10-16T{end}:00+09:00',
              due_at=f'2026-10-16T{due}:00+09:00', evidence=[])
    if busy and kind == 'PICKUP':
        customer = 'C-H'
        op.update(target_job_id='J-PICK1', item_id='PR-A', asset_ids=['P01'], source_customer_id=customer)
    payload['needs_confirmation'] = []
    if queued:
        qid, rid = queued
    else:
        r = c.post('/api/v1/requests', json=dict(source_customer_id=customer, text='일정 변경 요청'))
        assert r.status_code == 201, r.text
        rid = r.json()['id']
    r = c.put(f'/api/v1/requests/{rid}/interpretation', json=dict(expected_request_revision=1,
        payload=payload, acknowledged_paths=[]))
    assert r.status_code == 200, r.text
    body = dict(request_id=rid, interpretation_revision=r.json()['interpretation']['revision'])
    if queued:
        r = c.post(f'/api/v1/request-queues/{qid}/plan', json=body)
    else:
        r = c.post('/api/v1/plans', json={**body, 'base_state_revision': revision, 'overrides': overrides or []})
    assert r.status_code == 201, r.text
    return r.json()


def confirm(c, p, revision=7):
    return c.post(f"/api/v1/plans/{p['id']}/confirm", json=dict(expected_plan_revision=1, base_state_revision=revision))


def test_internal_delivery_preferred_and_reservation_moves(real_planner):
    before = snapshot()
    p = request_plan(real_planner)
    assert p['status'] == 'READY', p['result']
    assert p['fallbacks'] == [] and p['preview_employees'] == []
    d = next(d for d in p['diff'] if d['job_id'] == 'J-DEL1')
    assert not quick.is_quick(d['after']['employee_id'])
    assert snapshot() == before
    assert confirm(real_planner, p).status_code == 200
    s = snapshot()
    active = next(r for r in s['reservations'] if r['rental_id'] == 'R-S2' and r['status'] == 'ACTIVE')
    assert active['start_at'] == '2026-10-16T16:40:00+09:00'
    assert s['assets'] == before['assets']
    assert s['rentals'] == before['rentals']


def test_courier_draft_then_atomic_confirm_and_next_plan(real_planner):
    shorten_today('17:00')
    before = snapshot()
    p = request_plan(real_planner)
    assert p['status'] == 'READY', p['result']
    assert [n['kind'] for n in p['fallbacks']] == ['QUICK']
    assert p['fallbacks'][0]['status'] == 'CALL_REQUIRED'
    eid = quick.resource_id('J-DEL1')
    assert p['preview_employees'] == [dict(id=eid, name='퀵서비스 · 호출 필요 (J-DEL1)')]
    d = next(d for d in p['diff'] if d['job_id'] == 'J-DEL1')
    assert d['after']['employee_id'] == eid and 'QUICK_SERVICE_REQUIRED' in d['reason_codes']
    assert snapshot() == before
    r = confirm(real_planner, p)
    assert r.status_code == 200, r.text
    assert r.json()['new_state_revision'] == 8
    after = snapshot()
    assert any(e['id'] == eid and '호출 필요' in e['name'] for e in after['employees'])
    assert next(x for x in after['plan_items'] if x['job_id'] == 'J-DEL1')['employee_id'] == eid
    assert len(after['shifts']) == len(before['shifts']) + 1
    assert after['assets'] == before['assets'] and after['rentals'] == before['rentals']
    # Same job can be replanned using the persisted resource; no duplicate rows/reasons.
    p2 = request_plan(real_planner, start='17:30', end='17:45', due='17:45', revision=8)
    assert p2['status'] == 'READY', p2['result']
    assert confirm(real_planner, p2, 8).status_code == 200
    s = snapshot()
    assert len(s['employees']) == len(after['employees']) and len(s['shifts']) == len(after['shifts'])
    assert next(x for x in s['plan_items'] if x['job_id'] == 'J-DEL1')['reason_codes'].count('QUICK_SERVICE_REQUIRED') == 1


@pytest.mark.parametrize('skip_weekend', [False, True])
def test_pickup_uses_next_staff_and_customer_workday(real_planner, skip_weekend):
    shorten_today('16:00')
    if skip_weekend:
        with database.get_db_engine().begin() as conn:
            row = conn.execute(select(T.customers).where(T.customers.c.id == 'C-J')).one()
            windows = [w for w in json.loads(row.visit_windows_json) if w['start_at'][:10] not in ('2026-10-17','2026-10-18')]
            conn.execute(update(T.customers).where(T.customers.c.id == 'C-J').values(visit_windows_json=J(windows)))
    before = snapshot()
    p = request_plan(real_planner, 'PICKUP', '16:30', '16:40', '17:20')
    assert p['status'] == 'READY', p['result']
    assert [n['kind'] for n in p['fallbacks']] == ['PICKUP_NEXT_WORKDAY']
    day = '2026-10-19' if skip_weekend else '2026-10-17'
    assert p['fallbacks'][0]['window_start'].startswith(day)
    assert p['preview_employees'] == [] and snapshot() == before
    d = {d['job_id']: d for d in p['diff']}
    assert d['J-PICK2']['after']['service_start_at'].startswith(day)
    assert d['J-PREP2']['after']['start_at'].startswith(day)
    assert confirm(real_planner, p).status_code == 200
    after = snapshot()
    assert next(j for j in after['jobs'] if j['id'] == 'J-PICK2')['window_start'].startswith(day)
    assert next(j for j in after['jobs'] if j['id'] == 'J-PREP2')['due_at'].startswith(day)
    assert next(r for r in after['rentals'] if r['id'] == 'R-J')['expected_return_at'].startswith(day)
    assert after['assets'] == before['assets']
    old = {p['job_id']: p for p in before['plan_items']}
    for row in after['plan_items']:
        if row['job_id'] not in ('J-PICK2', 'J-PREP2'):
            assert all(row[k] == old[row['job_id']][k] for k in ('employee_id','asset_ids','start_at','end_at','segments'))


@pytest.mark.parametrize('case', ['no_future_visit', 'too_short_visit', 'pinned_employee'])
def test_pickup_does_not_relax_invalid_or_explicit_constraints(real_planner, case):
    shorten_today('16:00')
    if case == 'no_future_visit':
        with database.get_db_engine().begin() as conn:
            row = conn.execute(select(T.customers).where(T.customers.c.id == 'C-J')).one()
            conn.execute(update(T.customers).where(T.customers.c.id == 'C-J').values(
                visit_windows_json=J(json.loads(row.visit_windows_json)[:1])))
    before = snapshot()
    p = request_plan(real_planner, 'PICKUP', '16:30', '16:35' if case == 'too_short_visit' else '16:40', '17:20',
                     overrides=[dict(job_id='J-PICK2', employee_id='E3')] if case == 'pinned_employee' else None)
    assert p['status'] == 'UNRESOLVED', p
    assert not p['fallbacks'] and not p['preview_employees'] and not p['diff']
    assert confirm(real_planner, p).status_code == 422
    assert snapshot() == before


def test_quick_cannot_bypass_asset_readiness(real_planner):
    shorten_today('17:00')
    # Modelled stock is unavailable even though courier capacity can be proposed.
    with database.get_db_engine().begin() as conn:
        conn.execute(update(T.assets).where(T.assets.c.id == 'P01').values(physical_state='UNAVAILABLE'))
    before = snapshot()
    p = request_plan(real_planner)
    assert p['status'] == 'UNRESOLVED' and p['fallbacks'] == []
    assert snapshot() == before


def test_confirmation_failure_rolls_back_courier_and_revision(real_planner, monkeypatch):
    shorten_today('17:00')
    p = request_plan(real_planner)
    assert p['fallbacks']
    before = snapshot()
    original = plans._finish_confirm
    def fail(*args, **kwargs):
        raise RuntimeError('injected transaction failure')
    monkeypatch.setattr(plans, '_finish_confirm', fail)
    with pytest.raises(RuntimeError, match='injected'):
        confirm(real_planner, p)
    assert snapshot() == before
    monkeypatch.setattr(plans, '_finish_confirm', original)
    assert confirm(real_planner, p).status_code == 200


def test_stale_courier_draft_cannot_add_resources(real_planner):
    shorten_today('17:00')
    pending = request_plan(real_planner)
    normal = request_plan(real_planner, start='15:00', end='15:15', due='15:15')
    assert normal['status'] == 'READY' and normal['fallbacks'] == []
    assert confirm(real_planner, normal).status_code == 200
    before = snapshot()
    r = confirm(real_planner, pending)
    assert r.status_code == 409 and r.json()['error']['code'] == 'STALE_PLAN'
    assert snapshot() == before
    assert not any(quick.is_quick(e['id']) for e in before['employees'])


def test_queue_after_quick_confirmation_uses_latest_and_keeps_delivery(real_planner):
    shorten_today('16:00')
    q = real_planner.post('/api/v1/request-queues', json=dict(items=[
        dict(source_customer_id='C-S', text='납품 변경'), dict(source_customer_id='C-J', text='회수 변경')])).json()
    requests = [x['request']['id'] for x in q['items']]
    first = request_plan(real_planner, queued=(q['id'], requests[0]))
    assert first['fallbacks'][0]['kind'] == 'QUICK'
    assert confirm(real_planner, first).status_code == 200
    old_delivery = next(p for p in snapshot()['plan_items'] if p['job_id'] == 'J-DEL1')
    second = request_plan(real_planner, 'PICKUP', '16:30', '16:40', '17:20', queued=(q['id'], requests[1]))
    assert second['base_state_revision'] == 8 and second['base_plan_id'] == first['id']
    assert second['fallbacks'][0]['kind'] == 'PICKUP_NEXT_WORKDAY'
    assert confirm(real_planner, second, 8).status_code == 200
    new_delivery = next(p for p in snapshot()['plan_items'] if p['job_id'] == 'J-DEL1')
    assert all(new_delivery[k] == old_delivery[k] for k in ('employee_id','asset_ids','start_at','end_at','segments'))
    q = real_planner.get(f"/api/v1/request-queues/{q['id']}").json()
    assert q['status'] == 'DONE'


def test_fallback_stage_limit_keeps_original_schedule(real_planner, monkeypatch):
    from rentwise.services import dispatch_fallback
    shorten_today('17:00')
    monkeypatch.setattr(dispatch_fallback, 'MAX_STAGES', 1)
    before = snapshot()
    p = request_plan(real_planner)
    assert p['status'] == 'UNRESOLVED' and p['result']['search_stats']['limit_reached']
    assert p['fallbacks'] == [] and p['diff'] == [] and snapshot() == before


@pytest.mark.parametrize('kind', ['DELIVERY', 'PICKUP'])
def test_busy_operational_seed_fallback_confirm_and_preserve_other_promises(real_planner, monkeypatch, kind):
    path = os.environ.get('RENTWISE_BUSY_SEED')
    if not path:
        pytest.skip('RENTWISE_BUSY_SEED operational fixture not supplied')
    monkeypatch.setattr(plans, 'settings', replace(plans.settings, seed_path=Path(path)))
    with database.get_db_engine().begin() as conn:
        database.load_seed(conn, json.loads(Path(path).read_text()))
    shorten_today('17:30')
    before = snapshot()
    p = request_plan(real_planner, kind, '17:30', '17:45' if kind == 'DELIVERY' else '17:40', '18:00', busy=True)
    assert p['status'] == 'READY', p['result']
    assert p['fallbacks'][0]['kind'] == ('QUICK' if kind == 'DELIVERY' else 'PICKUP_NEXT_WORKDAY')
    assert snapshot() == before
    r = confirm(real_planner, p)
    assert r.status_code == 200, r.text
    after = snapshot()
    assert len(after['plan_items']) == len(before['plan_items']) == 169
    assert after['assets'] == before['assets']
    old = {x['job_id']: x for x in before['plan_items']}
    for row in after['plan_items']:
        if row['job_id'] not in p['result']['affected_job_ids']:
            assert all(row[k] == old[row['job_id']][k] for k in ('employee_id','asset_ids','start_at','end_at','segments'))
