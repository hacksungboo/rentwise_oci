"""Customer acceptance drafts from persisted confirmations, no AI/send calls."""
import json

import pytest
from sqlalchemy import select, update

from rentwise.db import database, tables as T
from rentwise.db.database import J
from tests.test_explanations import before_after, draft
from tests.test_dispatch_fallback import real_planner, request_plan, shorten_today  # noqa: F401


def confirm(c, p):
    r = c.post(f"/api/v1/plans/{p['id']}/confirm", json=dict(expected_plan_revision=1, base_state_revision=7))
    assert r.status_code == 200, r.text


def message(c, p):
    return c.get(f"/api/v1/plans/{p['id']}/customer-message")


def test_confirmed_customer_draft_contains_only_requested_customer_facts(admin, monkeypatch):
    p = draft(admin, monkeypatch)
    assert message(admin, p).status_code == 409  # No acceptance before confirmation.
    confirm(admin, p)
    before = before_after()
    r = message(admin, p)
    assert r.status_code == 200, r.text
    value = r.json(); text = value['text']
    assert value['recipient'] == dict(id='C-H', name='한빛상사') and value['state_revision'] == 8
    assert value['source'] == 'SYSTEM' and not value['requires_dispatch']
    assert '2026년 10월 16일(금) 14:00~14:10' in text and '배정을 완료' in text
    for private in ('새봄디자인', 'P01', 'P02', '김현우', '이서연', '창고', '15:00', 'J-PICK'):
        assert private not in text
    assert '작업을 완료' not in text and before_after() == before
    with database.get_db_engine().connect() as conn:
        assert conn.execute(select(T.ai_calls)).first() is None


@pytest.mark.parametrize('case', ['held', 'stale', 'new_interpretation', 'missing_customer', 'other_customer'])
def test_unconfirmed_or_ambiguous_customer_drafts_are_blocked(admin, monkeypatch, case):
    p = draft(admin, monkeypatch)
    if case == 'held':
        admin.post(f"/api/v1/plans/{p['id']}/hold", json=dict(expected_plan_revision=1, reason='보류'))
    else:
        confirm(admin, p)
        with database.get_db_engine().begin() as conn:
            if case == 'stale':
                conn.execute(update(T.workspace_state).values(state_revision=9, current_plan_id='PL-007'))
            elif case == 'new_interpretation':
                conn.execute(update(T.plans).where(T.plans.c.id == p['id']).values(interpretation_revision=99))
            else:
                conn.execute(update(T.requests).where(T.requests.c.id == p['request_id']).values(
                    source_customer_id=None if case == 'missing_customer' else 'C-S'))
    r = message(admin, p)
    assert r.status_code in (409, 422), r.text
    assert 'text' not in r.json()


def test_recipient_mixed_operation_never_exposes_another_customer(admin, monkeypatch):
    p = draft(admin, monkeypatch); confirm(admin, p)
    with database.get_db_engine().begin() as conn:
        row = conn.execute(select(T.plans).where(T.plans.c.id == p['id'])).one()
        ops = json.loads(row.operations_json)
        ops.append({**ops[0], 'target_job_id': 'J-DEL1', 'kind': 'DELIVERY'})
        conn.execute(update(T.plans).where(T.plans.c.id == p['id']).values(operations_json=J(ops)))
    r = message(admin, p)
    assert r.status_code == 422 and r.json()['error']['code'] == 'MESSAGE_SCOPE_REVIEW'
    assert '새봄디자인' not in r.text


def test_unbooked_courier_message_does_not_claim_provider_acceptance(real_planner):
    shorten_today('17:00'); p = request_plan(real_planner)
    confirm(real_planner, p)
    r = message(real_planner, p)
    assert r.status_code == 200, r.text
    value = r.json()
    assert value['requires_dispatch'] and '배정안을 마련' in value['text']
    assert '호출·수락 확인 후' in value['text'] and '배정을 완료' not in value['text']
    assert '17:00~17:15' in value['text'] and 'QK-' not in value['text']


def test_next_workday_message_uses_saved_visit_not_original_requested_date(real_planner):
    shorten_today('16:00'); p = request_plan(real_planner, 'PICKUP', '16:30', '16:40', '17:20')
    confirm(real_planner, p)
    r = message(real_planner, p)
    assert r.status_code == 200, r.text
    assert '2026년 10월 17일(토)' in r.json()['text'] and '16:30' not in r.json()['text']


def test_customer_message_admin_only(admin, monkeypatch):
    p = draft(admin, monkeypatch); confirm(admin, p)
    admin.delete('/api/v1/sessions/current')
    assert message(admin, p).status_code == 401
    admin.post('/api/v1/sessions', json=dict(username='e1', password='rentwise2026'))
    assert message(admin, p).status_code == 403


@pytest.mark.parametrize('status', ['COMPLETED', 'IN_PROGRESS'])
def test_existing_execution_is_not_described_as_a_new_visit_acceptance(admin, monkeypatch, status):
    p = draft(admin, monkeypatch); confirm(admin, p)
    with database.get_db_engine().begin() as conn:
        conn.execute(update(T.jobs).where(T.jobs.c.id == 'J-PICK1').values(status=status))
    r = message(admin, p)
    assert r.status_code == 422 and r.json()['error']['code'] == 'MESSAGE_SCOPE_REVIEW'


def test_queue_customer_drafts_follow_latest_confirmation_and_recipient(real_planner):
    q = real_planner.post('/api/v1/request-queues', json=dict(items=[
        dict(source_customer_id='C-S', text='납품 변경'), dict(source_customer_id='C-J', text='회수 변경')])).json()
    ids = [x['request']['id'] for x in q['items']]
    first = request_plan(real_planner, queued=(q['id'], ids[0]))
    confirm(real_planner, first)
    assert message(real_planner, first).json()['recipient']['id'] == 'C-S'
    second = request_plan(real_planner, 'PICKUP', '16:30', '16:40', '17:20', queued=(q['id'], ids[1]))
    r = real_planner.post(f"/api/v1/plans/{second['id']}/confirm", json=dict(expected_plan_revision=1, base_state_revision=8))
    assert r.status_code == 200, r.text
    assert message(real_planner, first).status_code == 409
    result = message(real_planner, second)
    assert result.status_code == 200 and result.json()['recipient']['id'] == 'C-J'
    assert '새봄디자인' not in result.json()['text']
