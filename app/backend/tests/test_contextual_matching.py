"""Reported busy-v1 delivery wording through actual B HTTP, FakeClient only."""
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from tests.test_real_mode import delay_intent, real, response  # noqa: F401
from tests.test_request_queue import snapshot

TEXT = '오늘 4시 프린터 설치를 3시~3시반 사이로 당겨주실 수 있을까요?'


def test_busy_delivery_matching_human_confirmation_plan_and_confirm(admin, real, monkeypatch):
    path = os.environ.get('RENTWISE_BUSY_SEED')
    if not path:
        pytest.skip('RENTWISE_BUSY_SEED operational fixture not supplied; no gold data used')
    from rentwise.db import database
    from rentwise.services import plans
    monkeypatch.setattr(plans, 'settings', replace(plans.settings, seed_path=Path(path)))
    with database.get_db_engine().begin() as conn:
        database.load_seed(conn, json.loads(Path(path).read_text()))
    payload = delay_intent()
    payload['operations'][0].update(kind='DELIVERY', target_job_id='J-B045', item_id='PR-A', asset_ids=['P10'],
        source_customer_id=None, destination_customer_id='C-B16', window_start='2026-10-16T15:00:00+09:00',
        window_end='2026-10-16T15:30:00+09:00', due_at=None, evidence=[
            {'path': 'kind', 'quote': '프린터 설치'}, {'path': 'operation', 'quote': '당겨'},
            {'path': 'item_id', 'quote': '프린터'}, {'path': 'window_start', 'quote': TEXT}, {'path': 'window_end', 'quote': TEXT}])
    payload['needs_confirmation'] = []
    provider = real(response(payload))
    before = snapshot()
    created = admin.post('/api/v1/requests', json={'source_customer_id': 'C-B16', 'text': TEXT})
    assert created.status_code == 201
    req = created.json()
    result = admin.post(f"/api/v1/requests/{req['id']}/interpret", json={'expected_request_revision': 1})
    assert result.status_code == 200, result.text
    value = result.json()['interpretation']['payload']
    op = value['operations'][0]
    assert op['target_job_id'] == 'J-B045'
    assert op['window_start'] == '2026-10-16T15:00:00+09:00' and op['window_end'] == '2026-10-16T15:30:00+09:00'
    assert '오전·오후' in next(q['question'] for q in value['needs_confirmation'] if q['path'].endswith('.window_start'))
    op['due_at'] = '2026-10-16T16:30:00+09:00'  # Existing deadline, explicitly approved.
    unreviewed = admin.put(f"/api/v1/requests/{req['id']}/interpretation", json={
        'expected_request_revision': 1, 'payload': value, 'acknowledged_paths': []})
    assert unreviewed.status_code == 200
    pending = admin.post('/api/v1/plans', json={'request_id': req['id'],
        'interpretation_revision': unreviewed.json()['interpretation']['revision'], 'base_state_revision': 7})
    assert pending.status_code == 422 and pending.json()['error']['code'] == 'UNCONFIRMED_FIELDS'
    saved = admin.put(f"/api/v1/requests/{req['id']}/interpretation", json={
        'expected_request_revision': 1, 'payload': value,
        'acknowledged_paths': [q['path'] for q in value['needs_confirmation']]})
    p = admin.post('/api/v1/plans', json={'request_id': req['id'],
        'interpretation_revision': saved.json()['interpretation']['revision'], 'base_state_revision': 7})
    assert p.status_code == 201 and p.json()['status'] == 'READY', p.text
    assert snapshot() == before
    confirmed = admin.post(f"/api/v1/plans/{p.json()['id']}/confirm", json={
        'expected_plan_revision': 1, 'base_state_revision': 7})
    assert confirmed.status_code == 200, confirmed.text
    after = snapshot()
    changed = next(j for j in after['jobs'] if j['id'] == 'J-B045')
    assert changed['window_start'] == op['window_start'] and changed['window_end'] == op['window_end']
    assert next(j for j in after['jobs'] if j['id'] == 'J-B014') == next(j for j in before['jobs'] if j['id'] == 'J-B014')
    assert len(after['plan_items']) == len(before['plan_items']) and after['assets'] == before['assets']
    assert provider.calls == 1
