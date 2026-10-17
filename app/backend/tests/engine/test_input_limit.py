"""Input-size / budget regression. FakeClient only; C seed is opt-in data, not gold."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path

import pytest

from rentwise.contracts import types as c
from rentwise.engine import RealEngine
from rentwise.engine.interpret import (
    INPUT_LIMIT, INPUT_FRAMING_HEADROOM, OUTPUT_LIMIT, PRICE_VERSION, PROMPT_VERSION,
    OpenAIInterpreter, ProviderFailure,
)
from .test_interpret import FakeBudget, FakeClient, interpretation_input, response


def sized_input(count):
    customers = interpretation_input().candidate_customers
    customers += [c.CandidateRef(id=f'C-LOAD-{n:03d}', name=f'가상업체{n:03d}') for n in range(count-len(customers))]
    return interpretation_input(candidate_customers=customers)


def body_size(body):
    return len(json.dumps(body, ensure_ascii=False).encode('utf-8')) + INPUT_FRAMING_HEADROOM


@pytest.mark.parametrize('count', [38, 120])
def test_representative_customer_lists_pass_without_trimming_context(count):
    inp = sized_input(count); before = inp.model_dump()
    provider, budget = FakeClient(), FakeBudget()
    result = OpenAIInterpreter(client=provider, budget=budget).interpret(inp)
    assert result.status == 'OK', result
    body = provider.calls[0][0]
    assert 8000 < body_size(body) <= INPUT_LIMIT
    sent = json.loads(body['input'][1]['content'])
    assert sent['candidate_customers'] == before['candidate_customers']
    assert len(sent['candidate_customers']) == count
    assert inp.model_dump() == before
    assert budget.reservations[0][2] == Decimal('.064')
    assert result.call.prompt_version == PROMPT_VERSION == 'rental-extract-v1.1'
    assert budget.settled[0][2] == PRICE_VERSION == 'openai-standard-2026-10-17-terra'


@pytest.mark.parametrize('excess', [0, 1])
def test_exact_full_request_byte_boundary_and_one_byte_over(excess):
    inp = sized_input(38)
    probe = FakeClient()
    assert OpenAIInterpreter(client=probe, budget=FakeBudget()).interpret(inp).status == 'OK'
    padding = INPUT_LIMIT-body_size(probe.calls[0][0])+excess
    inp.candidate_customers[-1].name += 'x'*padding
    provider, budget = FakeClient(), FakeBudget()
    result = OpenAIInterpreter(client=provider, budget=budget).interpret(inp)
    if excess:
        assert result.status == 'ERROR' and result.error.code == 'AI_INPUT_TOO_LARGE'
        assert result.call.attempts == 0 and not provider.calls and not budget.reservations
    else:
        assert result.status == 'OK', result
        assert body_size(provider.calls[0][0]) == INPUT_LIMIT


def test_multibyte_customer_name_uses_utf8_bytes_not_characters():
    inp = sized_input(38)
    inp.candidate_customers[-1].name += '한'*3000
    provider, budget = FakeClient(), FakeBudget()
    r = OpenAIInterpreter(client=provider, budget=budget).interpret(inp)
    assert r.error.code == 'AI_INPUT_TOO_LARGE' and not provider.calls and not budget.reservations


@pytest.mark.parametrize('cached', [0, 8000, 16000])
def test_reservation_covers_full_input_output_and_conservative_cache_write_cost(cached):
    # Provider usage is a test value at the policy upper bound, not a tokenizer measurement.
    usage = dict(input_tokens=INPUT_LIMIT, output_tokens=OUTPUT_LIMIT,
        input_tokens_details={'cached_tokens':cached}, output_tokens_details={'reasoning_tokens':100})
    provider, budget = FakeClient(response(usage=usage)), FakeBudget()
    r = OpenAIInterpreter(client=provider, budget=budget).interpret(sized_input(120))
    assert r.status == 'OK', r
    reserved = budget.reservations[0][2]
    assert reserved == Decimal('.064')
    expected = (Decimal(INPUT_LIMIT-cached)*Decimal('2.00')*Decimal('1.25')
        + Decimal(cached)*Decimal('.20') + Decimal(OUTPUT_LIMIT)*Decimal('12.00')) / 1_000_000
    assert reserved >= expected
    if cached == 0:
        assert reserved == expected
    assert provider.calls[0][0]['max_output_tokens'] == OUTPUT_LIMIT == 2000


def test_two_transient_attempts_reserve_each_ceiling_and_retain_unknown_cost(monkeypatch):
    from rentwise.engine import interpret
    monkeypatch.setattr(interpret.time, 'sleep', lambda _: None)
    provider = FakeClient(ProviderFailure('AI_PROVIDER_ERROR', transient=True), response())
    budget = FakeBudget(Decimal('.128'))
    r = OpenAIInterpreter(client=provider, budget=budget).interpret(sized_input(120))
    assert r.status == 'OK' and r.call.attempts == 2
    assert [row[2] for row in budget.reservations] == [Decimal('.064')]*2
    assert sum(row[2] for row in budget.reservations) == Decimal('.128')
    assert len(budget.unknown) == len(budget.settled) == 1
    assert r.call.usage is None


@pytest.mark.parametrize('remaining,expected_calls', [(Decimal('.063999'),0), (Decimal('.127999'),1)])
def test_budget_never_starts_an_attempt_without_its_full_reservation(remaining, expected_calls, monkeypatch):
    from rentwise.engine import interpret
    monkeypatch.setattr(interpret.time, 'sleep', lambda _: None)
    provider = FakeClient(ProviderFailure('AI_PROVIDER_ERROR', transient=True), response())
    budget = FakeBudget(remaining)
    r = OpenAIInterpreter(client=provider, budget=budget).interpret(sized_input(120))
    assert r.error.code == 'BUDGET_EXCEEDED'
    assert len(provider.calls) == len(budget.reservations) == expected_calls
    assert all(row[2] == Decimal('.064') for row in budget.reservations)


def test_busy_seed_http_interpret_review_plan_confirm_with_real_ledger(admin, monkeypatch):
    """Optional C operating seed; never reads scenarios, labels, overlays or gold."""
    seed_path = os.environ.get('RENTWISE_BUSY_SEED')
    if not seed_path:
        pytest.skip('Set RENTWISE_BUSY_SEED to the C infra seed_busy.json for data integration')
    raw = Path(seed_path).read_bytes()
    seed = json.loads(raw)
    assert seed['manifest']['dataset_version'] == 'rental-synth-busy-v1'
    assert (len(seed['customers']),len(seed['employees']),len(seed['assets'])) == (38,12,132)
    from sqlalchemy import select
    from rentwise.db import database, tables as T
    from rentwise.services import ai_ledger, requests, plans
    from dataclasses import replace
    with database.get_db_engine().begin() as conn:
        database.load_seed(conn, seed)
    monkeypatch.setattr(ai_ledger, 'settings', replace(ai_ledger.settings, ai_budget_usd='1'))
    ai_ledger.sync_limit()
    text = '한빛상사입니다. 오늘 프린터 회수 오후 2시로 미뤄주세요!'
    payload = dict(schema_version='rental.intent.v1', operations=[dict(
        operation='RESCHEDULE',kind='PICKUP',target_job_id='J-PICK1',item_id='PR-A',asset_ids=['P01'],quantity=None,
        source_customer_id='C-H',destination_customer_id=None,window_start='2026-10-16T14:00:00+09:00',
        window_end=None,due_at=None,rental_end_at=None,priority_hint='UNKNOWN', evidence=[
            {'path':'kind','quote':'회수'}, {'path':'operation','quote':'미뤄'},
            {'path':'window_start','quote':'오늘 프린터 회수 오후 2시'}])], needs_confirmation=[
        {'path':'operations.0.window_end','reason':'MISSING','question':'방문 종료 시각을 확인해 주세요.'},
        {'path':'operations.0.due_at','reason':'MISSING','question':'완료 기한을 확인해 주세요.'}])
    provider = FakeClient(response(payload))
    engine = RealEngine(as_of=seed['manifest']['clock_anchor'], interpreter=OpenAIInterpreter(
        client=provider,budget=ai_ledger.LedgerBudget()))
    monkeypatch.setattr(requests, 'get_engine', lambda: engine)
    monkeypatch.setattr(plans, 'get_engine', lambda: engine)
    r = admin.post('/api/v1/requests', json={'source_customer_id':'C-H','text':text,
        'received_at':'2026-10-16T09:00:00+09:00'})
    assert r.status_code == 201, r.text
    rid = r.json()['id']
    r = admin.post(f'/api/v1/requests/{rid}/interpret', json={'expected_request_revision':1})
    assert r.status_code == 200, r.text
    interp = r.json()['interpretation']
    assert interp['origin'] == 'AI' and len(provider.calls) == 1
    body = provider.calls[0][0]
    assert len(json.loads(body['input'][1]['content'])['candidate_customers']) == 38
    assert 8000 < body_size(body) <= INPUT_LIMIT
    with database.get_db_engine().connect() as conn:
        ledger = conn.execute(select(T.ai_ledger)).mappings().one()
        assert Decimal(str(ledger['reserved_usd'])) == Decimal('.064')
        assert ledger['price_version'] == PRICE_VERSION
    early = admin.post('/api/v1/plans', json={'request_id':rid,'interpretation_revision':interp['revision'],
        'base_state_revision':seed['workspace']['state_revision']})
    assert early.status_code == 422  # Model output is never human approval.
    reviewed_payload = deepcopy(interp['payload'])
    reviewed_payload['operations'][0].update(window_end='2026-10-16T14:10:00+09:00',due_at='2026-10-16T17:00:00+09:00')
    reviewed = admin.put(f'/api/v1/requests/{rid}/interpretation', json={'expected_request_revision':1,
        'payload':reviewed_payload,'acknowledged_paths':[n['path'] for n in reviewed_payload['needs_confirmation']]})
    assert reviewed.status_code == 200 and reviewed.json()['status'] == 'READY', reviewed.text
    with database.get_db_engine().connect() as conn:
        before = database.read_snapshot(conn)
    draft = admin.post('/api/v1/plans', json={'request_id':rid,
        'interpretation_revision':reviewed.json()['interpretation']['revision'],
        'base_state_revision':seed['workspace']['state_revision']})
    assert draft.status_code == 201 and draft.json()['status'] == 'READY', draft.text
    pid = draft.json()['id']
    with database.get_db_engine().connect() as conn:
        assert database.read_snapshot(conn) == before
    done = admin.post(f'/api/v1/plans/{pid}/confirm', json={'expected_plan_revision':1,
        'base_state_revision':seed['workspace']['state_revision']})
    assert done.status_code == 200, done.text
    with database.get_db_engine().connect() as conn:
        latest = database.read_snapshot(conn)
    jobs = {j['id']:j for j in latest['jobs']}
    rows = {p['job_id']:p for p in latest['plan_items']}
    assert jobs['J-PICK1']['window_start'] == '2026-10-16T14:00:00+09:00'
    assert rows['J-PICK1']['employee_id'] == 'E2'
    assert jobs['J-DEL1']['asset_ids'] == ['P02']
    assert next(s for s in rows['J-DEL1']['segments'] if s['kind']=='SERVICE')['start_at'] == '2026-10-16T12:00:00+09:00'
    assert latest['assets'] == before['assets']
    assert Path(seed_path).read_bytes() == raw
    print('busy seed SHA256:', hashlib.sha256(raw).hexdigest(), 'request byte bound:', body_size(body))


def test_actual_b_ledger_settlement_at_policy_maximum_does_not_exceed_reservation(client, monkeypatch):
    from dataclasses import replace
    from sqlalchemy import select
    from rentwise.db import database, tables as T
    from rentwise.services import ai_ledger
    monkeypatch.setattr(ai_ledger, 'settings', replace(ai_ledger.settings, ai_budget_usd='1'))
    ai_ledger.sync_limit()
    provider = FakeClient(response(usage=dict(input_tokens=16000,output_tokens=2000,
        input_tokens_details={'cached_tokens':0},output_tokens_details={'reasoning_tokens':100})))
    r = OpenAIInterpreter(client=provider,budget=ai_ledger.LedgerBudget()).interpret(sized_input(120))
    assert r.status == 'OK'
    with database.get_db_engine().connect() as conn:
        ledger = conn.execute(select(T.ai_ledger)).mappings().one()
    assert ledger['status'] == 'SETTLED' and ledger['price_version'] == PRICE_VERSION
    assert Decimal(str(ledger['reserved_usd'])) == Decimal(str(ledger['settled_usd'])) == Decimal('.064')
