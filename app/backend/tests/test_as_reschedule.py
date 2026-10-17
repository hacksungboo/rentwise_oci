"""Reviewed AS promises outside the old morning window, no paid model calls."""
import json
import os
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update

from tests.test_real_mode import delay_intent, real, response  # noqa: F401
from tests.test_request_queue import snapshot

TEXT = '오늘 정수기 AS 일정을 오후 4시로 미뤄주세요.'


def draft(admin, real, monkeypatch, busy=False, ack=True, customer_closes_at_noon=False):
    from rentwise.db import database
    from rentwise.services import plans
    if busy:
        path = os.environ.get('RENTWISE_BUSY_SEED')
        if not path:
            pytest.skip('RENTWISE_BUSY_SEED operational fixture not supplied; no gold used')
        monkeypatch.setattr(plans, 'settings', replace(plans.settings, seed_path=Path(path)))
        with database.get_db_engine().begin() as c:
            database.load_seed(c, json.loads(Path(path).read_text()))
    customer = 'C-G' if busy else 'C-B'
    if customer_closes_at_noon:
        # Explicit test-only customer restriction; original fixtures stay intact.
        from rentwise.db import tables as T
        with database.get_db_engine().begin() as c:
            c.execute(update(T.customers).where(T.customers.c.id == customer).values(visit_windows_json=json.dumps([
                {'start_at': '2026-10-16T09:00:00+09:00', 'end_at': '2026-10-16T12:00:00+09:00'}])))
    payload = delay_intent()
    payload['operations'][0].update(kind='AS', target_job_id='J-AS1', item_id='WP-A', asset_ids=['W01'],
        source_customer_id=customer, window_start='2026-10-16T16:00:00+09:00', evidence=[
            {'path': 'kind', 'quote': 'AS'}, {'path': 'operation', 'quote': '미뤄'},
            {'path': 'window_start', 'quote': '오늘 정수기 AS 일정을 오후 4시로'}])
    provider = real(response(payload))
    before = snapshot()
    req = admin.post('/api/v1/requests', json={'source_customer_id': customer, 'text': TEXT}).json()
    interpreted = admin.post(f"/api/v1/requests/{req['id']}/interpret", json={'expected_request_revision': 1})
    assert interpreted.status_code == 200, interpreted.text
    value = interpreted.json()['interpretation']['payload']
    assert value['operations'][0]['due_at'] is None  # Old 11:00/11:30 is not silently inherited.
    minutes = next(i for i in before['items'] if i['id'] == 'WP-A')['service_minutes_by_kind']['AS']
    value['operations'][0].update(target_job_id='J-AS1', window_end=f'2026-10-16T16:{minutes:02d}:00+09:00', due_at='2026-10-16T17:30:00+09:00')
    saved = admin.put(f"/api/v1/requests/{req['id']}/interpretation", json={
        'expected_request_revision': 1, 'payload': value,
        'acknowledged_paths': [q['path'] for q in value['needs_confirmation']] if ack else []})
    assert saved.status_code == 200, saved.text
    plan = admin.post('/api/v1/plans', json={'request_id': req['id'],
        'interpretation_revision': saved.json()['interpretation']['revision'], 'base_state_revision': 7})
    return before, req, value, plan, provider


def confirm(admin, p):
    return admin.post(f"/api/v1/plans/{p['id']}/confirm", json={
        'expected_plan_revision': p['revision'], 'base_state_revision': p['base_state_revision']})


@pytest.mark.parametrize('busy', [False, True])
def test_afternoon_as_new_deadline_confirms_and_preserves_other_promises(admin, real, monkeypatch, busy):
    before, req, value, result, provider = draft(admin, real, monkeypatch, busy)
    assert result.status_code == 201, result.text
    p = result.json()
    assert p['status'] == 'READY', json.dumps(p['result'], ensure_ascii=False)
    assert snapshot() == before
    changed = [r for r in p['diff'] if r['changed']]
    assert [r['job_id'] for r in changed] == ['J-AS1']
    assert changed[0]['after']['service_start_at'].startswith('2026-10-16T16:00')
    confirmed = confirm(admin, p)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['new_state_revision'] == 8 and provider.calls == 1
    after = snapshot()
    job = next(j for j in after['jobs'] if j['id'] == 'J-AS1')
    for field, clock in [('window_start', '16:00'), ('window_end', '16:30' if busy else '16:40'), ('due_at', '17:30')]:
        assert job[field].startswith('2026-10-16T' + clock)
    assert [j for j in before['jobs'] if j['id'] != 'J-AS1'] == [j for j in after['jobs'] if j['id'] != 'J-AS1']
    for table in ('assets', 'rentals', 'reservations', 'dependencies'):
        assert before[table] == after[table]
    old_rows = {r['job_id']: r for r in before['plan_items']}
    for row in after['plan_items']:
        if row['job_id'] != 'J-AS1':
            for field in ('employee_id', 'asset_ids', 'start_at', 'end_at', 'segments'):
                assert row[field] == old_rows[row['job_id']][field]
    from rentwise.services import requests
    assert requests.get_engine().validate(after, after['plan_items']).status == 'VALID'
    msg = admin.get(f"/api/v1/plans/{p['id']}/customer-message")
    assert msg.status_code == 200 and ('16:00~16:30' if busy else '16:00~16:40') in msg.json()['text']


def test_afternoon_as_requires_explicit_human_acknowledgement(admin, real, monkeypatch):
    before, _, _, result, _ = draft(admin, real, monkeypatch, ack=False)
    assert result.status_code == 422 and result.json()['error']['code'] == 'UNCONFIRMED_FIELDS'
    assert snapshot() == before


def test_single_as_old_draft_cannot_confirm_after_human_changes_conditions(admin, real, monkeypatch):
    before, req, value, result, _ = draft(admin, real, monkeypatch)
    assert result.json()['status'] == 'READY'
    value['operations'][0]['due_at'] = '2026-10-16T18:00:00+09:00'
    saved = admin.put(f"/api/v1/requests/{req['id']}/interpretation", json={
        'expected_request_revision': 1, 'payload': value, 'acknowledged_paths': [q['path'] for q in value['needs_confirmation']]})
    assert saved.status_code == 200
    rejected = confirm(admin, result.json())
    assert rejected.status_code == 409 and rejected.json()['error']['code'] == 'STALE_INTERPRETATION'
    assert snapshot() == before


def test_confirmation_rechecks_new_as_window_instead_of_only_old_or_broader_deadline(admin, real, monkeypatch):
    from rentwise.db import database, tables as T
    from rentwise.timeutil import parse, to_db
    before, _, _, result, _ = draft(admin, real, monkeypatch)
    p = result.json()
    assert p['status'] == 'READY'
    with database.get_db_engine().begin() as c:
        row = c.execute(select(T.plan_items).where((T.plan_items.c.plan_id == p['id']) & (T.plan_items.c.job_id == 'J-AS1'))).one()
        segments = json.loads(row.segments_json)
        for s in segments:
            for field in ('start_at', 'end_at'):
                s[field] = (parse(s[field]) + timedelta(minutes=30)).isoformat()
        c.execute(update(T.plan_items).where(T.plan_items.c.id == row.id).values(
            start_at=to_db(segments[0]['start_at']), end_at=to_db(segments[-1]['end_at']), segments_json=json.dumps(segments)))
    rejected = confirm(admin, p)
    assert rejected.status_code == 422 and rejected.json()['error']['code'] == 'CONSTRAINT_VIOLATION'
    assert 'VISIT_WINDOW' in {v['code'] for v in rejected.json()['error']['details']['violations']}
    assert snapshot() == before


def test_as_confirm_failure_rolls_back_new_promises_and_schedule(admin, real, monkeypatch):
    from rentwise.api.errors import ApiError
    from rentwise.services import plans
    before, _, _, result, _ = draft(admin, real, monkeypatch)
    assert result.json()['status'] == 'READY'
    finish = plans._finish_confirm
    def fail(*args, **kwargs):
        finish(*args, **kwargs)
        raise ApiError(503, 'TEST_ROLLBACK', '시험용 저장 실패')
    monkeypatch.setattr(plans, '_finish_confirm', fail)
    rejected = confirm(admin, result.json())
    assert rejected.status_code == 503
    assert snapshot() == before
    assert admin.get('/api/v1/operations').json()['workspace']['state_revision'] == 7


def test_changed_as_promise_still_respects_existing_customer_visit_windows(admin, real, monkeypatch):
    before, _, _, result, _ = draft(admin, real, monkeypatch, customer_closes_at_noon=True)
    p = result.json()
    assert p['status'] == 'UNRESOLVED'
    assert 'B_V1_PERSISTENCE_UNSUPPORTED' not in {u['code'] for u in p['result']['unresolved']}
    assert 'CUSTOMER_VISIT_WINDOW' in {v['code'] for v in p['result']['violations']}
    assert snapshot() == before


def test_confirm_rejects_plan_conditions_not_equal_to_latest_human_review(admin, real, monkeypatch):
    from rentwise.db import database, tables as T
    before, _, _, result, _ = draft(admin, real, monkeypatch)
    p = result.json()
    assert p['status'] == 'READY'
    with database.get_db_engine().begin() as c:
        row = c.execute(select(T.plans).where(T.plans.c.id == p['id'])).one()
        ops = json.loads(row.operations_json)
        ops[0]['due_at'] = '2026-10-16T18:00:00+09:00'
        c.execute(update(T.plans).where(T.plans.c.id == p['id']).values(operations_json=json.dumps(ops)))
    rejected = confirm(admin, p)
    assert rejected.status_code == 409 and rejected.json()['error']['code'] == 'STALE_INTERPRETATION'
    assert snapshot() == before


def test_confirm_rechecks_current_customer_availability_after_draft(admin, real, monkeypatch):
    from rentwise.db import database, tables as T
    _, _, _, result, _ = draft(admin, real, monkeypatch)
    p = result.json()
    assert p['status'] == 'READY'
    with database.get_db_engine().begin() as c:
        c.execute(update(T.customers).where(T.customers.c.id == 'C-B').values(visit_windows_json=json.dumps([
            {'start_at': '2026-10-16T09:00:00+09:00', 'end_at': '2026-10-16T12:00:00+09:00'}])))
    current = snapshot()
    rejected = confirm(admin, p)
    assert rejected.status_code == 422 and rejected.json()['error']['code'] == 'CONSTRAINT_VIOLATION'
    assert 'CUSTOMER_VISIT_WINDOW' in {v['code'] for v in rejected.json()['error']['details']['violations']}
    assert snapshot() == current
