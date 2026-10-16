"""Prepare a validated intent for the existing B v1 confirmation form.

Extraction stays independent of the UI. Defaults here are explicit proposals
from the supplied job summary, never fabricated request evidence or approval.
"""
from __future__ import annotations

import re

from rentwise.contracts import types as c
from .intent_checks import _time

VERSION = 'b-review-v1'
_FORM_FIELDS = {'kind', 'item_id', 'window_start', 'window_end', 'due_at'}
_LABELS = {
    'rental_end_at': '대여 종료일·무기한 여부', 'source_customer_id': '출발·방문 고객',
    'destination_customer_id': '도착 고객', 'quantity': '수량', 'asset_ids': '장비 개체',
    'operation': '신규·변경 구분', 'priority_hint': '우선순위',
}


def prepare_review(inp: c.InterpretationInput, result: c.InterpretationResult) -> c.InterpretationResult:
    if result.status != 'OK' or result.payload is None:
        return result
    prepared = result.model_copy(deep=True)
    intent = prepared.payload
    for index, op in enumerate(intent.operations):
        job = _selected_job(inp, op)
        item_path = f'operations.{index}.item_id'
        # B already inherits this reference on RESCHEDULE. Showing it earlier
        # lets its existing duration button use the real model's service time.
        if job and op.item_id is None and not any(q.path == item_path for q in intent.needs_confirmation):
            if job.get('item_id') in {item.id for item in inp.candidate_items}:
                op.item_id = job['item_id']
        path = f'operations.{index}.due_at'
        questions = [q for q in intent.needs_confirmation if q.path == path]
        if op.due_at is not None or any(q.reason != 'MISSING' for q in questions):
            continue
        due_at = _existing_as_deadline(inp, op)
        if due_at is None:
            continue
        op.due_at = due_at
        question = ('원문에 새 완료 기한이 없습니다. 기존 작업의 완료 기한 '
            f'{_time(due_at):%Y-%m-%d %H:%M}(한국 시각)을 유지합니까? '
            '확인하거나 기존 약속 범위 안에서 수정해 주세요.')
        if questions:
            for q in questions:
                q.question = question
        else:
            intent.needs_confirmation.append(c.NeedsConfirmation(path=path, reason='MISSING', question=question))

    blocked = []
    for question in intent.needs_confirmation:
        match = re.fullmatch(r'operations\.(\d+)\.([a-z_]+)', question.path)
        if match and int(match[1]) < len(intent.operations):
            op = intent.operations[int(match[1])]
            editable = _FORM_FIELDS | ({'target_job_id'} if op.operation == 'RESCHEDULE' else {'quantity'})
            if match[2] in editable:
                continue
        blocked.append(question.path)
    if blocked:
        labels = sorted({_LABELS.get(p.split('.')[-1], '요청 업무·조건') for p in blocked})
        return c.InterpretationResult(status='ERROR', payload=None, call=prepared.call,
            error=c.DomainError(code='AI_REVIEW_UNSUPPORTED', retryable=False,
                message=f"현재 조건 확인 화면에서 {', '.join(labels)} 확인을 완료할 수 없습니다. "
                    '원문에 조건을 구체적으로 적어 다시 요청하거나 운영 담당자에게 수동 검토를 요청해 주세요.',
                details={'paths': sorted(set(blocked)), 'review_version': VERSION}))
    return prepared


def _existing_as_deadline(inp: c.InterpretationInput, op: c.Operation) -> str | None:
    if op.operation != 'RESCHEDULE' or op.kind != 'AS' or not op.target_job_id or not op.window_start:
        return None
    # A quoted, but unresolved deadline must be clarified rather than replaced.
    if any(e.path == 'due_at' for e in op.evidence):
        return None
    job = _selected_job(inp, op)
    if job is None:
        return None
    try:
        deadline, start = _time(job['due_at']), _time(op.window_start)
        old_start, old_end = _time(job['window_start']), _time(job['window_end'])
        if not old_start <= start < old_end or start > deadline:
            return None
        if op.window_end is not None and not start < _time(op.window_end) <= min(old_end, deadline):
            return None
        return deadline.isoformat()
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _selected_job(inp: c.InterpretationInput, op: c.Operation) -> dict | None:
    if op.operation != 'RESCHEDULE' or not op.target_job_id:
        return None
    matches = [j for j in inp.existing_jobs if j.get('id') == op.target_job_id]
    if len(matches) != 1:
        return None
    job = matches[0]
    customer = op.destination_customer_id if op.kind == 'DELIVERY' else op.source_customer_id
    return job if job.get('kind') == op.kind and customer is not None and job.get('customer_id') == customer else None
