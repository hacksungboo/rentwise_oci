"""No paid network in pytest. Provider and budget fakes are test-only."""
from copy import deepcopy
from decimal import Decimal
import json

import pytest

from rentwise.contracts import types as c
from rentwise.engine import RealEngine
from rentwise.engine.interpret import (
    BudgetExceeded, INSTRUCTIONS, OpenAIInterpreter, OpenAIResponsesClient,
    PRICE_VERSION, ProviderFailure, _ACTIVE_CALL,
)


TEXT = '오늘 J-AS1 정수기 AS를 오전 10시 15분부터 오전 10시 55분까지로 변경하고 오전 11시까지 완료해 주세요.'


def interpretation_input(**changes):
    data = dict(request_id='R-1', request_revision=1, received_at='2026-10-16T00:00:00+09:00',
        text=TEXT, source_customer_id='C-B',
        candidate_customers=[{'id': 'C-B', 'name': '바른법무사무소'}, {'id': 'C-S', 'name': '새봄디자인'}],
        candidate_items=[{'id': 'WP-A', 'name': '정수기 DEMO-W'}],
        existing_jobs=[dict(id='J-AS1', kind='AS', customer_id='C-B', item_id='WP-A', asset_ids=['W01'],
            window_start='2026-10-16T10:00:00+09:00', window_end='2026-10-16T11:00:00+09:00', due_at='2026-10-16T11:00:00+09:00')])
    data.update(changes)
    return c.InterpretationInput(**data)


def intent(**changes):
    op = dict(operation='RESCHEDULE', kind='AS', target_job_id='J-AS1', item_id='WP-A', asset_ids=['W01'],
        quantity=None, source_customer_id='C-B', destination_customer_id=None,
        window_start='2026-10-16T10:15:00+09:00', window_end='2026-10-16T10:55:00+09:00',
        due_at='2026-10-16T11:00:00+09:00', rental_end_at=None, priority_hint='UNKNOWN',
        evidence=[{'path': field, 'quote': quote} for field, quote in (
            ('kind', 'AS'), ('operation', '변경'), ('window_start', TEXT), ('window_end', TEXT), ('due_at', TEXT))])
    op.update(changes)
    return dict(schema_version='rental.intent.v1', operations=[op], needs_confirmation=[])


def response(payload=None, **changes):
    data = dict(id='resp-unit', status='completed', output=[{'type': 'message', 'role': 'assistant',
        'content': [{'type': 'output_text', 'text': json.dumps(payload or intent(), ensure_ascii=False)}]}],
        usage=dict(input_tokens=600, output_tokens=250, input_tokens_details={'cached_tokens': 100},
            output_tokens_details={'reasoning_tokens': 0}))
    data.update(changes)
    return data


class FakeClient:
    def __init__(self, *outputs):
        self.outputs = list(outputs) or [response()]
        self.calls = []

    def create(self, body, *, timeout):
        self.calls.append((deepcopy(body), timeout))
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


class FakeBudget:
    def __init__(self, remaining=Decimal('1')):
        self.remaining = remaining
        self.reservations, self.settled, self.unknown = [], [], []

    def reserve(self, key, maximum):
        if maximum > self.remaining:
            raise BudgetExceeded()
        self.remaining -= maximum
        rid = str(len(self.reservations))
        self.reservations.append((rid, key, maximum))
        return rid

    def settle(self, rid, usage, version):
        self.settled.append((rid, usage, version))

    def mark_unknown(self, rid, reason):
        self.unknown.append((rid, reason))


def run(payload=None, inp=None, client=None, budget=None):
    provider = client or FakeClient(response(payload))
    ledger = budget if budget is not None else FakeBudget()
    result = OpenAIInterpreter(client=provider, budget=ledger).interpret(inp or interpretation_input())
    return result, provider, ledger


def test_extract_uses_shared_schema_metadata_and_minimal_context():
    inp = interpretation_input()
    inp.existing_jobs[0]['private_contact'] = 'must not be sent'
    before = inp.model_dump()
    result, provider, ledger = run(inp=inp)
    assert result.status == 'OK', result
    assert c.InterpretationResult.model_validate_json(result.model_dump_json()) == result
    assert result.call.origin == 'AI' and result.call.model_id == 'gpt-5.6-terra'
    assert result.call.provider_call_id == 'resp-unit' and result.call.attempts == 1
    assert result.call.usage.cached_input_tokens == 100
    body, timeout = provider.calls[0]
    assert timeout <= 20 and body['store'] is False and body['max_output_tokens'] == 2000
    assert body['text']['format']['strict'] is True
    assert 'private_contact' not in body['input'][1]['content']
    assert body['input'][0] == {'role': 'developer', 'content': INSTRUCTIONS}
    assert ledger.settled[0][2] == PRICE_VERSION and not ledger.unknown
    assert ledger.reservations[0][2] == Decimal('.064')
    assert inp.model_dump() == before


@pytest.mark.parametrize('kind', ['DELIVERY', 'PICKUP', 'AS', 'TRANSFER'])
def test_four_kinds_use_same_b_contract_and_leave_missing_information_for_review(kind):
    payload = intent(operation='CREATE', kind=kind, target_job_id=None, item_id=None, asset_ids=[],
        window_start=None, window_end=None, due_at=None)
    result, _, _ = run(payload)
    assert result.status == 'OK'
    paths = {x.path for x in result.payload.needs_confirmation}
    assert {'operations.0.window_start', 'operations.0.window_end', 'operations.0.due_at',
        'operations.0.item_id', 'operations.0.quantity'} <= paths
    if kind in ('DELIVERY', 'TRANSFER'):
        assert 'operations.0.destination_customer_id' in paths


def test_relative_date_uses_korean_received_date_even_if_received_in_utc():
    # UTC Oct 15 is already Oct 16 in Korea. Tomorrow is Oct 17.
    inp = interpretation_input(received_at='2026-10-15T16:00:00+00:00', text=TEXT.replace('오늘', '내일'))
    payload = intent()
    for field in ('window_start', 'window_end', 'due_at'):
        payload['operations'][0][field] = payload['operations'][0][field].replace('10-16', '10-17')
    for entry in payload['operations'][0]['evidence']:
        entry['quote'] = entry['quote'].replace('오늘', '내일')
    result, provider, _ = run(payload, inp)
    assert result.status == 'OK'
    assert json.loads(provider.calls[0][0]['input'][1]['content'])['received_local_date'] == '2026-10-16'
    payload['operations'][0]['window_start'] = '2026-10-16T10:15:00+09:00'
    assert run(payload, inp)[0].error.code == 'AI_SCHEMA_INVALID'


def test_bare_hour_becomes_ambiguous_and_does_not_invent_duration_or_deadline():
    inp = interpretation_input(text='AS를 내일 2시로 변경')
    payload = intent(window_start='2026-10-17T14:00:00+09:00', window_end=None, due_at=None,
        evidence=[{'path': 'kind', 'quote': 'AS'}, {'path': 'operation', 'quote': '변경'},
            {'path': 'window_start', 'quote': '내일 2시'}])
    result, _, _ = run(payload, inp)
    assert result.status == 'OK' and result.payload.operations[0].window_start is None
    confirms = {x.path: x.reason for x in result.payload.needs_confirmation}
    assert confirms['operations.0.window_start'] == 'AMBIGUOUS'
    assert confirms['operations.0.window_end'] == 'MISSING'


def test_duplicate_customer_names_and_multiple_jobs_require_selection():
    inp = interpretation_input(text=TEXT.replace('J-AS1', '정우'), source_customer_id=None,
        candidate_customers=[{'id': 'C-B', 'name': '정우'}, {'id': 'C-S', 'name': '정우'}])
    payload = intent()
    payload['operations'][0]['evidence'] = [dict(x, quote=x['quote'].replace('J-AS1', '정우')) for x in payload['operations'][0]['evidence']]
    payload['operations'][0]['evidence'].append({'path': 'source_customer_id', 'quote': '정우'})
    result, _, _ = run(payload, inp)
    assert result.status == 'OK'
    assert result.payload.operations[0].source_customer_id is None
    assert any(x.reason == 'AMBIGUOUS' for x in result.payload.needs_confirmation)
    inp = interpretation_input(text=TEXT.replace('J-AS1 ', ''))
    inp.existing_jobs.append(dict(inp.existing_jobs[0], id='J-AS3'))
    payload = intent(evidence=[dict(x, quote=x['quote'].replace('J-AS1 ', '')) for x in intent()['operations'][0]['evidence']])
    result, _, _ = run(payload, inp)
    assert result.status == 'OK' and result.payload.operations[0].target_job_id is None


@pytest.mark.parametrize('field,value', [
    ('target_job_id', 'FAKE-JOB'), ('source_customer_id', 'FAKE-CUSTOMER'),
    ('destination_customer_id', 'C-S'), ('item_id', 'FAKE-ITEM'), ('asset_ids', ['FAKE-ASSET']),
    ('quantity', 2), ('quantity', 13), ('quantity', True), ('priority_hint', 'URGENT'),
    ('window_start', '2026-10-16T10:15:00'), ('window_end', '2026-10-16T09:00:00+09:00'),
    ('due_at', '2026-10-16T09:00:00+09:00'),
    ('evidence', [{'path': 'kind', 'quote': '원문에 없는 내용'}]),
])
def test_unverified_or_malformed_values_are_never_success(field, value):
    result, provider, budget = run(intent(**{field: value}))
    assert result.status == 'ERROR' and result.payload is None and result.error.code == 'AI_SCHEMA_INVALID'
    assert len(provider.calls) == 1 and len(budget.settled) == 1


@pytest.mark.parametrize('case', ['missing_nullable', 'extra_key', 'bad_confirmation', 'invalid_json', 'duplicate_json_key'])
def test_schema_is_checked_after_provider_response(case):
    payload = intent()
    if case == 'missing_nullable': del payload['operations'][0]['quantity']
    if case == 'extra_key': payload['execute_now'] = True
    if case == 'bad_confirmation': payload['needs_confirmation'] = [{'path': 'operations.99.kind', 'reason': 'MISSING', 'question': '확인'}]
    output = response(payload)
    if case == 'invalid_json': output['output'][0]['content'][0]['text'] = 'not json'
    if case == 'duplicate_json_key': output['output'][0]['content'][0]['text'] = '{"operations": [], "operations": []}'
    result, _, _ = run(client=FakeClient(output))
    assert result.error.code == 'AI_SCHEMA_INVALID' and result.call.attempts == 1


@pytest.mark.parametrize('status,content,code', [
    ('incomplete', [], 'AI_INCOMPLETE'),
    ('completed', [{'type': 'refusal', 'refusal': 'no'}], 'AI_REFUSED'),
    ('failed', [], 'AI_PROVIDER_ERROR'), ('completed', [], 'AI_RESPONSE_INVALID'),
])
def test_refusal_incomplete_and_bad_response_are_settled_but_not_retried(status, content, code):
    output = response(status=status, output=[{'type': 'message', 'role': 'assistant', 'content': content}])
    result, provider, ledger = run(client=FakeClient(output))
    assert result.error.code == code and len(provider.calls) == len(ledger.settled) == 1


def test_timeout_holds_reservation_no_retry_and_never_exposes_provider_error_body():
    result, provider, ledger = run(client=FakeClient(ProviderFailure('AI_TIMEOUT')))
    assert result.error.code == 'AI_TIMEOUT' and not result.error.retryable
    assert len(provider.calls) == 1 and ledger.unknown == [('0', 'AI_TIMEOUT')]
    result, _, _ = run(client=FakeClient(RuntimeError('SECRET/raw request/traceback')))
    assert 'SECRET' not in result.model_dump_json() and result.error.code == 'AI_PROVIDER_ERROR'


def test_only_transient_status_gets_one_retry_with_a_separate_reservation():
    client = FakeClient(ProviderFailure('AI_RATE_LIMITED', transient=True), response())
    result, _, ledger = run(client=client)
    assert result.status == 'OK' and result.call.attempts == 2
    assert result.call.usage is None  # first attempt's usage is unknown; no misleading partial total
    assert ledger.reservations[0][1] != ledger.reservations[1][1]
    assert len(ledger.unknown) == 1 and len(ledger.settled) == 1
    client = FakeClient(*[ProviderFailure('AI_PROVIDER_ERROR', transient=True)] * 2)
    result, _, ledger = run(client=client)
    assert result.error.retryable and len(client.calls) == len(ledger.unknown) == 2


def test_budget_and_concurrency_guards_block_before_network():
    result, provider, _ = run(budget=FakeBudget(Decimal('0')))
    assert result.error.code == 'BUDGET_EXCEEDED' and not provider.calls and result.call.attempts == 0
    _ACTIVE_CALL.acquire()
    try:
        result, provider, ledger = run()
        assert result.error.code == 'AI_BUSY' and not provider.calls and not ledger.reservations
    finally:
        _ACTIVE_CALL.release()
    provider = FakeClient()
    result = OpenAIInterpreter(client=provider).interpret(interpretation_input())
    assert result.error.code == 'AI_BUDGET_NOT_CONFIGURED' and not provider.calls
    result = OpenAIInterpreter(client=provider, budget=FakeBudget(), model_id='unapproved').interpret(interpretation_input())
    assert result.error.code == 'AI_MODEL_NOT_ALLOWED' and not provider.calls


def test_missing_or_invalid_usage_holds_reservation_and_cannot_claim_success():
    for raw in (None, {}, {'input_tokens': -1, 'output_tokens': 1}):
        result, provider, budget = run(client=FakeClient(response(usage=raw)))
        assert result.error.code == 'AI_USAGE_MISSING' and len(provider.calls) == len(budget.unknown) == 1
        assert not budget.settled


def test_accounting_failure_and_large_input_are_safe_errors():
    budget = FakeBudget()
    def fail(*args): raise RuntimeError('secret database info')
    budget.settle = fail
    result, _, _ = run(budget=budget)
    assert result.error.code == 'AI_BUDGET_UNAVAILABLE' and 'secret' not in result.model_dump_json()
    inp = interpretation_input(candidate_customers=[{'id': f'C-{i}', 'name': '긴이름' * 30} for i in range(50)],
        source_customer_id=None, existing_jobs=[])
    result, client, _ = run(inp=inp)
    assert result.error.code == 'AI_INPUT_TOO_LARGE' and not client.calls


def test_key_is_not_in_repr_or_outgoing_model_input(monkeypatch):
    key = 'unit-placeholder-not-a-real-key'
    monkeypatch.setenv('OPENAI_API_KEY', key)
    engine = RealEngine()
    assert isinstance(engine.interpreter.client, OpenAIResponsesClient)
    assert key not in repr(engine.interpreter.client)
    assert engine.interpret(interpretation_input()).error.code == 'AI_BUDGET_NOT_CONFIGURED'
    result, client, _ = run()
    assert key not in json.dumps(client.calls[0][0]) and key not in result.model_dump_json()


@pytest.mark.parametrize('status,code,transient', [
    (400, 'AI_PROVIDER_ERROR', False), (401, 'AI_AUTH_FAILED', False),
    (403, 'AI_AUTH_FAILED', False), (404, 'AI_MODEL_UNAVAILABLE', False),
    (429, 'AI_RATE_LIMITED', True), (500, 'AI_PROVIDER_ERROR', True),
    (503, 'AI_PROVIDER_ERROR', True), (302, 'AI_PROVIDER_ERROR', False),
])
def test_real_transport_classifies_http_errors_without_returning_provider_body(monkeypatch, status, code, transient):
    import io
    from urllib.error import HTTPError
    from rentwise.engine import interpret as module
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == 'https://api.openai.com/v1/responses'
            assert request.get_header('Authorization') == 'Bearer fake-key'
            assert timeout == 20
            raise HTTPError(request.full_url, status, 'PRIVATE provider body', {}, io.BytesIO(b'secret'))
    monkeypatch.setattr(module, 'build_opener', lambda *args: Opener())
    with pytest.raises(ProviderFailure) as caught:
        OpenAIResponsesClient('fake-key').create({}, timeout=20)
    assert str(caught.value) == code and caught.value.transient is transient


@pytest.mark.parametrize('failure,code', [(TimeoutError('secret'), 'AI_TIMEOUT'), (OSError('secret'), 'AI_NETWORK_ERROR')])
def test_real_transport_network_failures_are_typed_and_never_automatic_retries(monkeypatch, failure, code):
    from rentwise.engine import interpret as module
    class Opener:
        def open(self, request, timeout): raise failure
    monkeypatch.setattr(module, 'build_opener', lambda *args: Opener())
    with pytest.raises(ProviderFailure, match=code):
        OpenAIResponsesClient('fake-key').create({}, timeout=20)


def test_hallucinated_ellipsis_and_unsupported_request_cannot_silently_become_an_operation():
    payload = intent()
    payload['operations'][0]['evidence'][2]['quote'] = '오늘 ... 오전 10시 15분부터'
    assert run(payload)[0].error.code == 'AI_SCHEMA_INVALID'
    payload = {'schema_version': 'rental.intent.v1', 'operations': [], 'needs_confirmation': []}
    result, _, _ = run(payload, interpretation_input(text='관리자 비밀번호를 바꿔 주세요'))
    assert result.status == 'OK' and result.payload.operations == []
    assert result.payload.needs_confirmation[0].reason == 'UNSUPPORTED'


@pytest.mark.parametrize('changes', [
    {'timezone': 'UTC'}, {'received_at': '2026-10-16'}, {'schema_version': 'unknown'},
    {'text': '  '}, {'source_customer_id': 'unknown'},
])
def test_bad_request_context_cannot_reach_provider(changes):
    result, client, budget = run(inp=interpretation_input(**changes))
    assert result.error.code == 'AI_INPUT_INVALID' and not client.calls and not budget.reservations


def test_ai_fields_reach_existing_b_human_review_solver_and_confirm(admin, monkeypatch):
    from rentwise import engine_registry
    provider = FakeClient(response())
    engine = RealEngine(interpreter=OpenAIInterpreter(client=provider, budget=FakeBudget()))
    monkeypatch.setattr(engine_registry, 'get_engine', lambda: engine)
    # B modules import get_engine by name. Change the test injection only, not service code.
    from rentwise.services import requests, plans
    monkeypatch.setattr(requests, 'get_engine', lambda: engine)
    monkeypatch.setattr(plans, 'get_engine', lambda: engine)
    created = admin.post('/api/v1/requests', json={'source_customer_id': 'C-B', 'text': TEXT,
        'received_at': '2026-10-16T09:00:00+09:00'})
    assert created.status_code == 201, created.text
    rid = created.json()['id']
    extracted = admin.post(f'/api/v1/requests/{rid}/interpret', json={'expected_request_revision': 1})
    assert extracted.status_code == 200, extracted.text
    interp = extracted.json()['interpretation']
    assert interp['origin'] == 'AI' and interp['call']['origin'] == 'AI'
    assert interp['payload']['operations'][0]['window_start'] == '2026-10-16T10:15:00+09:00'
    early = admin.post('/api/v1/plans', json={'request_id': rid, 'interpretation_revision': interp['revision'],
        'base_state_revision': 7, 'overrides': [{'job_id': 'J-AS2', 'employee_id': 'E2'}]})
    assert early.status_code == 422  # raw AI is never approval
    reviewed = admin.put(f'/api/v1/requests/{rid}/interpretation', json={'expected_request_revision': 1,
        'payload': interp['payload'], 'acknowledged_paths': [x['path'] for x in interp['payload']['needs_confirmation']]})
    assert reviewed.status_code == 200, reviewed.text
    planned = admin.post('/api/v1/plans', json={'request_id': rid,
        'interpretation_revision': reviewed.json()['interpretation']['revision'], 'base_state_revision': 7,
        'overrides': [{'job_id': 'J-AS2', 'employee_id': 'E2'}]})
    assert planned.status_code == 201 and planned.json()['status'] == 'READY', planned.text
    pid = planned.json()['id']
    confirmed = admin.post(f'/api/v1/plans/{pid}/confirm', json={'expected_plan_revision': 1, 'base_state_revision': 7})
    assert confirmed.status_code == 200, confirmed.text
    from rentwise.db import database
    with database.get_db_engine().connect() as conn:
        snapshot = database.read_snapshot(conn)
    assert next(j for j in snapshot['jobs'] if j['id'] == 'J-AS1')['window_start'] == '2026-10-16T10:15:00+09:00'
    assert len(provider.calls) == 1
