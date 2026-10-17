"""B form compatibility without weakening extraction, confirmation or solver."""
from copy import deepcopy

import pytest

from rentwise.contracts import types as c
from rentwise.engine import RealEngine
from rentwise.engine.b_review import prepare_review
from rentwise.engine.interpret import OpenAIInterpreter
from tests.engine.test_interpret import FakeBudget, FakeClient, interpretation_input, intent, response, run

TEXT = '오늘 J-AS1 정수기 AS 방문을 오전 10시 15분으로 변경해 주세요.'


def partial_payload():
    return intent(window_end=None, due_at=None, evidence=[
        {'path': 'operation', 'quote': '변경'}, {'path': 'kind', 'quote': 'AS'},
        {'path': 'window_start', 'quote': TEXT}])


def extracted(payload=None, inp=None):
    inp = inp or interpretation_input(text=TEXT)
    result, _, _ = run(payload or partial_payload(), inp)
    assert result.status == 'OK', result
    return inp, result


def test_existing_deadline_is_a_separate_confirmable_proposal_without_fake_evidence_or_mutation():
    inp, raw = extracted()
    before_inp, before_raw = inp.model_dump(), raw.model_dump()
    assert raw.payload.operations[0].due_at is None  # independent extraction remains unchanged
    prepared = prepare_review(inp, raw)
    assert prepared.status == 'OK'
    op = prepared.payload.operations[0]
    assert op.due_at == '2026-10-16T11:00:00+09:00' and op.window_end is None
    assert op.evidence == raw.payload.operations[0].evidence
    question = next(q for q in prepared.payload.needs_confirmation if q.path.endswith('.due_at'))
    assert question.reason == 'MISSING' and '기존 작업' in question.question and '11:00' in question.question
    assert '원문에 새 완료 기한이 없습니다' in question.question
    assert prepared.call == raw.call
    assert inp.model_dump() == before_inp and raw.model_dump() == before_raw
    assert c.InterpretationResult.model_validate_json(prepared.model_dump_json()) == prepared
    assert prepare_review(inp, prepared) == prepared


def test_unmentioned_existing_item_is_visible_for_b_duration_suggestion_without_model_evidence():
    inp, raw = extracted()
    raw.payload.operations[0].item_id = None
    prepared = prepare_review(inp, raw)
    assert prepared.payload.operations[0].item_id == 'WP-A'
    assert raw.payload.operations[0].item_id is None
    assert prepared.payload.operations[0].evidence == raw.payload.operations[0].evidence
    raw.payload.needs_confirmation.append(c.NeedsConfirmation(path='operations.0.item_id',
        reason='AMBIGUOUS', question='다른 품목인지 확인해 주세요.'))
    assert prepare_review(inp, raw).payload.operations[0].item_id is None


@pytest.mark.parametrize('case', ['explicit', 'ambiguous', 'out_of_range', 'quoted', 'no_target', 'no_start',
    'outside_window', 'late_end', 'wrong_kind', 'wrong_customer', 'bad_existing_time', 'duplicate_job'])
def test_a_never_replaces_explicit_uncertain_or_unrelated_conditions(case):
    inp, result = extracted()
    op = result.payload.operations[0]
    if case == 'explicit': op.due_at = '2026-10-16T17:00:00+09:00'
    elif case in ('ambiguous', 'out_of_range'):
        next(q for q in result.payload.needs_confirmation if q.path.endswith('.due_at')).reason = case.upper()
    elif case == 'quoted': op.evidence.append(c.Evidence(path='due_at', quote='11시'))
    elif case == 'no_target': op.target_job_id = None
    elif case == 'no_start': op.window_start = None
    elif case == 'outside_window': op.window_start = '2026-10-16T14:00:00+09:00'
    elif case == 'late_end': op.window_end = '2026-10-16T11:30:00+09:00'
    elif case == 'wrong_kind': op.kind = 'PICKUP'
    elif case == 'wrong_customer': inp.existing_jobs[0]['customer_id'] = 'C-S'
    elif case == 'bad_existing_time': inp.existing_jobs[0]['due_at'] = 'invalid'
    elif case == 'duplicate_job': inp.existing_jobs.append(deepcopy(inp.existing_jobs[0]))
    before = result.model_dump()
    prepared = prepare_review(inp, result)
    assert prepared.payload.operations[0].due_at == op.due_at
    assert result.model_dump() == before


@pytest.mark.parametrize('field,operation', [('rental_end_at','CREATE'), ('source_customer_id','RESCHEDULE'),
    ('destination_customer_id','CREATE'), ('quantity','RESCHEDULE'), ('asset_ids','CREATE'),
    ('priority_hint','RESCHEDULE'), ('operation','CREATE')])
def test_uneditable_questions_are_explicit_errors_not_silently_removed_or_acknowledged(field, operation):
    inp, result = extracted()
    result.payload.operations[0].operation = operation
    result.payload.needs_confirmation.append(c.NeedsConfirmation(path=f'operations.0.{field}',
        reason='MISSING', question='확인해 주세요.'))
    before = result.model_dump()
    prepared = prepare_review(inp, result)
    assert prepared.status == 'ERROR' and prepared.payload is None
    assert prepared.error.code == 'AI_REVIEW_UNSUPPORTED' and not prepared.error.retryable
    assert prepared.error.details['paths'] == [f'operations.0.{field}']
    assert '현재 조건 확인 화면' in prepared.error.message
    assert prepared.call == result.call and result.model_dump() == before


def test_empty_unsupported_and_mixed_requests_never_leave_a_partial_operation_to_apply():
    inp, result = extracted()
    result.payload.operations.append(result.payload.operations[0].model_copy(deep=True))
    result.payload.needs_confirmation.append(c.NeedsConfirmation(path='operations.1.destination_customer_id',
        reason='AMBIGUOUS', question='고객을 선택해 주세요.'))
    prepared = prepare_review(inp, result)
    assert prepared.status == 'ERROR' and prepared.payload is None
    empty = result.model_copy(deep=True)
    empty.payload = c.Intent(operations=[], needs_confirmation=[c.NeedsConfirmation(
        path='operations', reason='UNSUPPORTED', question='요청 종류를 확인해 주세요.')])
    assert prepare_review(inp, empty).error.code == 'AI_REVIEW_UNSUPPORTED'


def test_facade_applies_form_policy_but_keeps_real_model_metadata_and_one_charge():
    provider, budget = FakeClient(response(partial_payload())), FakeBudget()
    engine = RealEngine(interpreter=OpenAIInterpreter(client=provider, budget=budget))
    result = engine.interpret(interpretation_input(text=TEXT))
    assert result.payload.operations[0].due_at == '2026-10-16T11:00:00+09:00'
    assert result.call.origin == 'AI' and result.call.provider_call_id == 'resp-unit'
    assert len(provider.calls) == len(budget.settled) == 1
    failure = c.InterpretationResult(status='ERROR',payload=None,error=c.DomainError(code='AI_TIMEOUT',message='시간초과'),call=result.call)
    assert prepare_review(interpretation_input(text=TEXT), failure) is failure


def test_supported_form_fields_remain_editable_and_model_specified_values_remain_visible():
    inp, result = extracted()
    result.payload.operations[0].due_at = '2026-10-16T10:55:00+09:00'
    for field in ('kind', 'item_id', 'target_job_id', 'window_start'):
        result.payload.needs_confirmation.append(c.NeedsConfirmation(path=f'operations.0.{field}',
            reason='AMBIGUOUS',question='직접 선택해 주세요.'))
    prepared = prepare_review(inp,result)
    assert prepared.status == 'OK' and prepared.payload == result.payload


def test_b_api_requires_acknowledgement_then_confirms_the_original_deadline(admin, monkeypatch):
    from rentwise.services import requests, plans
    from rentwise.db import database
    engine = RealEngine(interpreter=OpenAIInterpreter(client=FakeClient(response(partial_payload())),budget=FakeBudget()))
    monkeypatch.setattr(requests, 'get_engine', lambda: engine)
    monkeypatch.setattr(plans, 'get_engine', lambda: engine)
    created = admin.post('/api/v1/requests', json={'source_customer_id':'C-B','text':TEXT,
        'received_at':'2026-10-16T09:00:00+09:00'})
    assert created.status_code == 201
    rid = created.json()['id']
    read = admin.post(f'/api/v1/requests/{rid}/interpret',json={'expected_request_revision':1})
    assert read.status_code == 200,read.text
    draft = read.json()['interpretation']['payload']
    assert draft['operations'][0]['due_at'] == '2026-10-16T11:00:00+09:00'
    # B's existing "start + service duration" button, no hardcoded 17:00 necessary.
    draft['operations'][0]['window_end'] = '2026-10-16T10:55:00+09:00'
    saved = admin.put(f'/api/v1/requests/{rid}/interpretation',json={'expected_request_revision':1,
        'payload':draft,'acknowledged_paths':['operations.0.window_end']})
    assert saved.status_code == 200 and saved.json()['pending_confirmations'] == ['operations.0.due_at']
    body = dict(request_id=rid,interpretation_revision=saved.json()['interpretation']['revision'],base_state_revision=7,
        overrides=[{'job_id':'J-AS2','employee_id':'E2'}])
    blocked = admin.post('/api/v1/plans',json=body)
    assert blocked.status_code == 422 and blocked.json()['error']['code'] == 'UNCONFIRMED_FIELDS'
    saved = admin.put(f'/api/v1/requests/{rid}/interpretation',json={'expected_request_revision':1,
        'payload':draft,'acknowledged_paths':[q['path'] for q in draft['needs_confirmation']]})
    assert saved.status_code == 200
    body['interpretation_revision'] = saved.json()['interpretation']['revision']
    with database.get_db_engine().connect() as conn:
        before = database.read_snapshot(conn)
    planned = admin.post('/api/v1/plans',json=body)
    assert planned.status_code == 201 and planned.json()['status'] == 'READY',planned.text
    confirmed = admin.post(f"/api/v1/plans/{planned.json()['id']}/confirm",
        json={'expected_plan_revision':1,'base_state_revision':7})
    assert confirmed.status_code == 200,confirmed.text
    with database.get_db_engine().connect() as conn:
        after = database.read_snapshot(conn)
    job = next(j for j in after['jobs'] if j['id'] == 'J-AS1')
    assert job['due_at'] == '2026-10-16T11:00:00+09:00' and job['window_start'] == '2026-10-16T10:15:00+09:00'
    for table in ('rentals','reservations','assets','dependencies'):
        assert before[table] == after[table]


def test_b_api_uneditable_confirmation_is_a_clear_error_with_no_interpretation_or_plan(admin,monkeypatch):
    from rentwise.services import requests
    inp, raw = extracted()
    raw.payload.needs_confirmation.append(c.NeedsConfirmation(path='operations.0.source_customer_id',
        reason='AMBIGUOUS',question='방문 고객을 확인해 주세요.'))
    class FixedInterpreter:
        def interpret(self, inp): return raw
    engine = RealEngine(interpreter=FixedInterpreter())
    monkeypatch.setattr(requests,'get_engine',lambda:engine)
    created = admin.post('/api/v1/requests',json={'source_customer_id':'C-B','text':TEXT})
    rid = created.json()['id']
    from rentwise.db import database
    with database.get_db_engine().connect() as conn:
        before = database.read_snapshot(conn)
    failed = admin.post(f'/api/v1/requests/{rid}/interpret',json={'expected_request_revision':1})
    assert failed.status_code == 422 and failed.json()['error']['code'] == 'AI_REVIEW_UNSUPPORTED'
    assert failed.json()['error']['details']['paths'] == ['operations.0.source_customer_id']
    view = admin.get(f'/api/v1/requests/{rid}').json()
    assert view['interpretation'] is None and view['plans'] == []
    with database.get_db_engine().connect() as conn:
        assert database.read_snapshot(conn) == before
