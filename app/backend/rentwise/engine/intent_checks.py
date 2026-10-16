"""Deterministic checks after schema-constrained extraction; no provider or DB."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import re

from rentwise.contracts import types as c
from rentwise.timeutil import KST

TIME_FIELDS = ('window_start', 'window_end', 'due_at', 'rental_end_at')
JOB_FIELDS = ('id', 'kind', 'customer_id', 'item_id', 'asset_ids', 'window_start', 'window_end', 'due_at')


def _time(value: str) -> datetime:
    if not isinstance(value, str) or 'T' not in value:
        raise ValueError('offset timestamp required')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('offset timestamp required')
    return parsed.astimezone(KST)


def input_context(inp: c.InterpretationInput) -> dict:
    if inp.timezone != 'Asia/Seoul' or inp.schema_version != 'rental.intent.v1' or not inp.text.strip():
        raise ValueError('unsupported interpretation input')
    day = _time(inp.received_at).date()
    customers = {x.id for x in inp.candidate_customers}
    if inp.source_customer_id and inp.source_customer_id not in customers:
        raise ValueError('unknown source customer')
    if len(customers) != len(inp.candidate_customers) or len({x.id for x in inp.candidate_items}) != len(inp.candidate_items):
        raise ValueError('duplicate candidate ID')
    jobs = [{key: job[key] for key in JOB_FIELDS if key in job} for job in inp.existing_jobs]
    if any(not isinstance(j.get('id'), str) or j.get('kind') not in ('DELIVERY', 'PICKUP', 'AS', 'TRANSFER')
           or j.get('customer_id') not in customers or not isinstance(j.get('asset_ids', []), list) for j in jobs):
        raise ValueError('invalid job summary')
    if len({j['id'] for j in jobs}) != len(jobs):
        raise ValueError('duplicate job ID')
    return dict(request_id=inp.request_id, request_revision=inp.request_revision,
        received_at=inp.received_at, received_local_date=day.isoformat(), timezone=inp.timezone,
        text=inp.text, source_customer_id=inp.source_customer_id,
        candidate_customers=[x.model_dump() for x in inp.candidate_customers],
        candidate_items=[x.model_dump() for x in inp.candidate_items], existing_jobs=jobs)


def _required_keys(value, node, root):
    """Use B's schema for required nullable keys (Pydantic defaults are looser)."""
    if '$ref' in node:
        node = root['$defs'][node['$ref'].split('/')[-1]]
    if isinstance(value, dict):
        properties = node.get('properties', {})
        if not set(node.get('required', [])) <= value.keys():
            raise ValueError('missing required schema keys')
        if node.get('additionalProperties') is False and not value.keys() <= properties.keys():
            raise ValueError('unknown schema keys')
        for key, child in value.items():
            if key in properties:
                _required_keys(child, properties[key], root)
    elif isinstance(value, list) and 'items' in node:
        for child in value:
            _required_keys(child, node['items'], root)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def check_intent(raw: str, inp: c.InterpretationInput, schema: dict) -> c.Intent:
    data = json.loads(raw, object_pairs_hook=_unique_object)
    _required_keys(data, schema, schema)
    intent = c.Intent.model_validate(data, strict=True)
    jobs = {j['id']: j for j in inp.existing_jobs}
    customers = {x.id: x.name for x in inp.candidate_customers}
    items = {x.id: x.name for x in inp.candidate_items}
    assets = {a for j in inp.existing_jobs for a in j.get('asset_ids', [])}
    day = _time(inp.received_at).date()

    def confirm(path, question, reason='MISSING'):
        if not any(x.path == path for x in intent.needs_confirmation):
            intent.needs_confirmation.append(c.NeedsConfirmation(path=path, reason=reason, question=question))

    if not intent.operations:
        confirm('operations', '요청할 업무 종류와 조건을 확인해 주세요.', 'UNSUPPORTED')
    for index, op in enumerate(intent.operations):
        prefix = f'operations.{index}.'
        evidence = {}
        for entry in op.evidence:
            if entry.path not in c.Operation.model_fields or entry.path == 'evidence' or not entry.quote.strip() or entry.quote not in inp.text:
                raise ValueError('unsupported evidence')
            evidence.setdefault(entry.path, []).append(entry.quote)
        if 'kind' not in evidence or 'operation' not in evidence:
            raise ValueError('operation needs original evidence')
        if op.target_job_id is not None and op.target_job_id not in jobs:
            raise ValueError('unknown job ID')
        if any(a not in assets for a in op.asset_ids):
            raise ValueError('unknown asset ID')
        if op.item_id is not None and op.item_id not in items:
            raise ValueError('unknown item ID')
        for field in ('source_customer_id', 'destination_customer_id'):
            identifier = getattr(op, field)
            if identifier is not None and identifier not in customers:
                raise ValueError('unknown customer ID')
            if identifier is not None and identifier != inp.source_customer_id:
                quotes = evidence.get(field, [])
                name = customers[identifier]
                if not any(identifier in q or (name and name in q) for q in quotes):
                    raise ValueError('customer not supported by request')
                if list(customers.values()).count(name) > 1 and not any(identifier in q for q in quotes):
                    setattr(op, field, None)
                    confirm(prefix + field, '이름이 같은 고객 중 대상을 선택해 주세요.', 'AMBIGUOUS')

        job = jobs.get(op.target_job_id)
        if op.operation == 'CREATE' and job:
            raise ValueError('new request cannot target existing job')
        if job:
            customer = op.destination_customer_id if op.kind == 'DELIVERY' else op.source_customer_id
            if job['kind'] != op.kind or (customer is not None and job.get('customer_id') != customer):
                raise ValueError('job does not match customer/kind')
            matches = [j for j in jobs.values() if j['kind'] == op.kind and j.get('customer_id') == job.get('customer_id')]
            if len(matches) > 1 and op.target_job_id not in inp.text:
                op.target_job_id = None
                confirm(prefix + 'target_job_id', '동일 종류의 기존 업무가 여러 개입니다. 변경할 업무를 선택해 주세요.', 'AMBIGUOUS')
            if op.item_id is not None and op.item_id != job.get('item_id'):
                raise ValueError('job/item mismatch')
            if op.asset_ids and not set(op.asset_ids) <= set(job.get('asset_ids', [])):
                raise ValueError('job/asset mismatch')
        if op.item_id is not None and (job is None or op.item_id != job.get('item_id')):
            name = items[op.item_id]
            quotes = evidence.get('item_id', [])
            # Item aliases (e.g. 프린터 for PR-A) are model interpretations, always reviewed.
            if not quotes:
                raise ValueError('item needs original evidence')
            if list(items.values()).count(name) > 1 and not any(op.item_id in q for q in quotes):
                op.item_id = None
                confirm(prefix + 'item_id', '이름이 같은 품목 중 모델을 선택해 주세요.', 'AMBIGUOUS')
        if op.asset_ids and job is None:
            if not all(any(a in q for q in evidence.get('asset_ids', [])) for a in op.asset_ids):
                raise ValueError('asset needs original evidence')
        if op.quantity is not None and 'quantity' not in evidence:
            raise ValueError('quantity needs original evidence')
        if op.priority_hint != 'UNKNOWN' and 'priority_hint' not in evidence:
            raise ValueError('priority needs original evidence')

        parsed = {}
        for field in TIME_FIELDS:
            value = getattr(op, field)
            if value is None:
                continue
            quotes = evidence.get(field, [])
            if not quotes:
                raise ValueError('time needs original evidence')
            dt = _time(value)
            relative = {offset for word, offset in (('오늘', 0), ('내일', 1), ('모레', 2)) if any(word in q for q in quotes)}
            if len(relative) == 1 and dt.date() != day + timedelta(days=next(iter(relative))):
                raise ValueError('relative date mismatch')
            # A bare "2시" cannot establish 오전/오후, unless 24-hour notation is explicit.
            phrase = ' '.join(quotes)
            hours = [int(x) for x in re.findall(r'(?<!\d)(\d{1,2})\s*시', phrase)]
            if hours and all(1 <= h <= 12 for h in hours) and not any(w in phrase for w in ('오전', '오후', '아침', '저녁', '밤', '정오', '자정')):
                setattr(op, field, None)
                confirm(prefix + field, '오전·오후를 포함한 시각을 확인해 주세요.', 'AMBIGUOUS')
                continue
            setattr(op, field, dt.isoformat())
            parsed[field] = dt
        if 'window_start' in parsed and 'window_end' in parsed and parsed['window_end'] <= parsed['window_start']:
            raise ValueError('invalid visit window')
        if 'window_start' in parsed and 'due_at' in parsed and parsed['due_at'] < parsed['window_start']:
            raise ValueError('deadline precedes visit')
        if op.operation == 'RESCHEDULE' and op.target_job_id is None:
            confirm(prefix + 'target_job_id', '변경할 기존 업무를 선택해 주세요.', 'AMBIGUOUS')
        customer_field = 'destination_customer_id' if op.kind == 'DELIVERY' else 'source_customer_id'
        required = [customer_field, 'window_start', 'window_end', 'due_at']
        if op.kind == 'TRANSFER':
            required.append('destination_customer_id')
        if op.operation == 'CREATE':
            required.extend(['item_id', 'quantity'])
            if op.kind in ('DELIVERY', 'TRANSFER'):
                required.append('rental_end_at')
        for field in required:
            if getattr(op, field) is None:
                confirm(prefix + field, _QUESTIONS[field])

    # Paths are B's acknowledgement keys, not arbitrary model instructions.
    for entry in intent.needs_confirmation:
        if not entry.question.strip() or len(entry.question) > 300:
            raise ValueError('invalid confirmation question')
        match = re.fullmatch(r'operations\.(\d+)\.([a-z_]+)', entry.path)
        if entry.path != 'operations' and (not match or int(match[1]) >= len(intent.operations) or match[2] not in c.Operation.model_fields or match[2] == 'evidence'):
            raise ValueError('invalid confirmation path')
    return intent


_QUESTIONS = {
    'source_customer_id': '출발지·방문 대상 고객을 확인해 주세요.',
    'destination_customer_id': '도착지·납품 대상 고객을 확인해 주세요.',
    'window_start': '방문 시작 시각을 확인해 주세요.',
    'window_end': '방문 종료 시각을 확인해 주세요.',
    'due_at': '작업 완료 기한을 확인해 주세요.',
    'item_id': '렌탈 품목·모델을 확인해 주세요.',
    'quantity': '수량을 확인해 주세요(1~12대).',
    'rental_end_at': '대여 종료 시각 또는 무기한 대여 여부를 확인해 주세요.',
}
