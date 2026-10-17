"""Bounded old/new visit references. FakeClient only, no paid AI."""
from copy import deepcopy

import pytest

from rentwise.engine import RealEngine
from rentwise.engine.interpret import OpenAIInterpreter
from tests.engine.test_interpret import interpretation_input, intent, FakeClient, FakeBudget, response

TEXT = '오늘 4시 프린터 설치를 3시~3시반 사이로 당겨주실 수 있을까요?'


def example(text=TEXT, target='J-TODAY'):
    job = dict(id='J-TODAY', kind='DELIVERY', customer_id='C-B', item_id='PR-A', asset_ids=['P10'],
        window_start='2026-10-16T16:00:00+09:00', window_end='2026-10-16T16:30:00+09:00', due_at='2026-10-16T16:30:00+09:00')
    jobs = [job, dict(job, id='J-NEXT', window_start='2026-10-21T16:00:00+09:00'),
            dict(job, id='J-NB', item_id='NB-A')]
    inp = interpretation_input(text=text, existing_jobs=jobs,
        candidate_items=[{'id': 'PR-A', 'name': '프린터'}, {'id': 'NB-A', 'name': '노트북'}])
    payload = intent(operation='RESCHEDULE', kind='DELIVERY', target_job_id=target, item_id='PR-A', asset_ids=[],
        source_customer_id=None, destination_customer_id='C-B', window_start='2026-10-16T15:00:00+09:00',
        window_end='2026-10-16T15:30:00+09:00', due_at=None, evidence=[
            {'path': 'kind', 'quote': '설치'}, {'path': 'operation', 'quote': '당겨'},
            {'path': 'item_id', 'quote': '프린터'}, {'path': 'window_start', 'quote': text}, {'path': 'window_end', 'quote': text}])
    return inp, payload


def run(inp, payload):
    provider, budget = FakeClient(response(payload)), FakeBudget()
    result = RealEngine(interpreter=OpenAIInterpreter(client=provider, budget=budget)).interpret(inp)
    assert len(provider.calls) == 1  # Post-processing never calls another model.
    return result


@pytest.mark.parametrize('target', ['J-TODAY', None])
def test_date_item_original_hour_match_one_old_visit_and_new_range_is_confirmable(target):
    inp, payload = example(target=target)
    original = deepcopy(payload)
    result = run(inp, payload)
    assert result.status == 'OK', result
    op = result.payload.operations[0]
    assert op.target_job_id == 'J-TODAY'
    assert op.window_start == '2026-10-16T15:00:00+09:00'
    assert op.window_end == '2026-10-16T15:30:00+09:00'
    assert op.due_at is None and op.quantity is None
    questions = {q.path: q for q in result.payload.needs_confirmation}
    for field in ('target_job_id', 'window_start', 'window_end'):
        assert questions['operations.0.' + field].reason == 'AMBIGUOUS'
    assert '오전·오후' in questions['operations.0.window_start'].question
    assert [e.model_dump() for e in op.evidence] == original['operations'][0]['evidence'] and payload == original


def test_duplicate_old_reference_does_not_pick_one_or_infer_pm():
    inp, payload = example()
    inp.existing_jobs.append(dict(inp.existing_jobs[0], id='J-DUPLICATE'))
    result = run(inp, payload)
    assert result.status == 'OK'
    op = result.payload.operations[0]
    assert op.target_job_id is None and op.window_start is None and op.window_end is None


def test_model_target_that_conflicts_with_unique_referenced_old_visit_is_rejected():
    inp, payload = example(target='J-NEXT')
    result = run(inp, payload)
    assert result.status == 'ERROR' and result.error.code == 'AI_SCHEMA_INVALID'


@pytest.mark.parametrize('text', [
    '프린터 설치를 3시~3시반 사이로 당겨주세요.',
    '오늘 4시 프린터 설치를 3시~3시반 사이로 당겨주세요. 내일 5시도 변경해주세요.',
    '오늘 4시 프린터 설치를 5시~5시반 사이로 당겨주세요.',
    '오늘 4시 프린터 설치를 3시~3시반 사이로 당겨주세요. 다음 요청은 7시입니다.',
])
def test_incomplete_multiple_or_contradictory_references_keep_manual_confirmation(text):
    inp, payload = example(text)
    result = run(inp, payload)
    assert result.status == 'OK', result
    assert result.payload.operations[0].window_start is None
    assert result.payload.operations[0].window_end is None


def test_existing_explicit_pm_and_half_hour_range_is_preserved():
    text = '오늘 오후 4시 프린터 설치를 오후 3시~오후 3시반 사이로 당겨주세요.'
    inp, payload = example(text)
    result = run(inp, payload)
    assert result.status == 'OK', result
    op = result.payload.operations[0]
    assert op.target_job_id == 'J-TODAY' and op.window_start.endswith('15:00:00+09:00')
    assert op.window_end.endswith('15:30:00+09:00')


def test_full_day_clock_and_minutes_also_work_without_nearest_time_heuristics():
    text = '오늘 16시 프린터 설치를 15시10분~15시40분 사이로 당겨주세요.'
    inp, payload = example(text)
    payload['operations'][0].update(window_start='2026-10-16T15:10:00+09:00', window_end='2026-10-16T15:40:00+09:00')
    result = run(inp, payload)
    assert result.status == 'OK', result
    op = result.payload.operations[0]
    assert op.target_job_id == 'J-TODAY' and op.window_start.endswith('15:10:00+09:00')
    assert op.window_end.endswith('15:40:00+09:00')


def test_context_suggestions_can_fill_missing_extraction_but_preserve_evidence_and_require_review():
    inp, payload = example(target=None)
    payload['operations'][0].update(window_start=None, window_end=None)
    payload['operations'][0]['evidence'] = [e for e in payload['operations'][0]['evidence'] if e['path'] not in ('window_start', 'window_end')]
    result = run(inp, payload)
    assert result.status == 'OK', result
    op = result.payload.operations[0]
    assert op.window_start.endswith('15:00:00+09:00') and op.window_end.endswith('15:30:00+09:00')
    assert not any(e.path in ('window_start', 'window_end') for e in op.evidence)
    assert len([q for q in result.payload.needs_confirmation if q.path.endswith(('.window_start', '.window_end'))]) == 2
    from rentwise.engine.b_review import prepare_review
    assert prepare_review(inp, result) == result


def test_ambiguous_original_am_and_pm_anchor_cannot_choose_a_job():
    inp, payload = example()
    inp.existing_jobs.append(dict(inp.existing_jobs[0], id='J-AM', window_start='2026-10-16T04:00:00+09:00'))
    result = run(inp, payload)
    assert result.status == 'OK'
    assert result.payload.operations[0].target_job_id is None
    assert result.payload.operations[0].window_start is None


def test_context_rule_never_applies_one_clause_to_multiple_operations():
    inp, payload = example()
    payload['operations'].append(deepcopy(payload['operations'][0]))
    result = run(inp, payload)
    assert result.status == 'OK', result
    assert all(op.target_job_id is None and op.window_start is None for op in result.payload.operations)
