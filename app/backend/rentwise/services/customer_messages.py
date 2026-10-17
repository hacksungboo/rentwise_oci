"""Read-only customer drafts from confirmed facts. No AI or delivery transport."""
import json

from sqlalchemy import select

from rentwise.api.errors import ApiError
from rentwise.db import tables as T
from rentwise.db.database import read_snapshot
from rentwise.engine import quick
from rentwise.services import plans
from rentwise.services.requests import latest_interpretation
from rentwise.timeutil import KST, parse

KINDS = {'DELIVERY': '납품', 'PICKUP': '회수', 'AS': 'A/S', 'TRANSFER': '고객 간 이동'}
CATEGORIES = {'PRINTER': '프린터', 'LAPTOP': '노트북', 'WATER_PURIFIER': '정수기'}
VERSION = 'rental-customer-message-v1'


def _plain(value):
    return ' '.join(str(value).split())


def _when(start, end):
    a, b = parse(start).astimezone(KST), parse(end).astimezone(KST)
    days = '월화수목금토일'
    first = f'{a:%Y년 %m월 %d일}({days[a.weekday()]}) {a:%H:%M}'
    last = b.strftime('%H:%M') if a.date() == b.date() else b.strftime('%Y년 %m월 %d일 %H:%M')
    return f'{first}~{last}'


def create(conn, plan_id):
    # A short lock gives the draft one consistent confirmed state; no model call.
    ws = plans._ws(conn, lock=True)
    p = plans._plan(conn, plan_id)
    if p.status != 'CONFIRMED' or ws.current_plan_id != plan_id or not p.request_id:
        raise ApiError(409, 'MESSAGE_PLAN_NOT_CURRENT', '현재 확정된 일정에서 고객 안내문을 다시 확인해 주세요.')
    latest = latest_interpretation(conn, p.request_id)
    if latest is None or latest['origin'] != 'HUMAN' or latest['revision'] != p.interpretation_revision:
        raise ApiError(409, 'STALE_INTERPRETATION', '요청 조건이 변경되었습니다. 현재 일정을 다시 확인해 주세요.')
    request = conn.execute(select(T.requests).where(T.requests.c.id == p.request_id)).one()
    s = read_snapshot(conn)
    customer = next((c for c in s['customers'] if c['id'] == request.source_customer_id), None)
    if customer is None:
        raise ApiError(422, 'MESSAGE_CUSTOMER_REQUIRED', '수신 고객을 확인해야 안내문을 만들 수 있습니다.')
    jobs, items = {j['id']: j for j in s['jobs']}, {i['id']: i for i in s['items']}
    rows = {r['job_id']: r for r in s['plan_items']}
    operations = json.loads(p.operations_json or '[]')
    lines, dispatch, seen = [], False, set()
    for op in operations:
        jid = op.get('target_job_id')
        j, row = jobs.get(jid), rows.get(jid)
        if (not j or not row or jid in seen or j['kind'] not in KINDS
                or j['status'] not in ('ASSIGNED', 'UNASSIGNED') or op.get('operation') != 'RESCHEDULE'):
            raise ApiError(422, 'MESSAGE_SCOPE_REVIEW', '고객에게 안내할 대상 작업을 직접 확인해 주세요.')
        site = customer['location_id']
        if site not in (j['from_id'], j['to_id']):
            raise ApiError(422, 'MESSAGE_SCOPE_REVIEW', '다른 고객의 작업이 포함되어 안내문을 자동 생성할 수 없습니다.')
        service = [seg for seg in row['segments'] if seg['kind'] == 'SERVICE' and seg['from_id'] == site]
        if len(service) != 1:
            raise ApiError(422, 'MESSAGE_SCOPE_REVIEW', '고객 방문 시간을 직접 확인해 주세요.')
        item = items[j['item_id']]
        label = CATEGORIES.get(item['category'], item['model_name'])
        lines.append(f"- {_plain(label)} {KINDS[j['kind']]}: {_when(service[0]['start_at'], service[0]['end_at'])} 방문 예정")
        dispatch |= quick.is_quick(row['employee_id'])
        seen.add(jid)
    if not lines:
        raise ApiError(422, 'MESSAGE_SCOPE_REVIEW', '안내할 확정 방문 일정이 없습니다.')
    opening = ('요청을 접수하고 아래 일정으로 배정안을 마련했습니다.' if dispatch else
               '요청하신 일정 변경을 접수하고 아래 방문 일정으로 배정을 완료했습니다.')
    closing = ('퀵서비스 업체의 호출·수락 확인 후 최종 방문 안내를 드리겠습니다.' if dispatch else
               '방문 일정을 확인해 주세요. 감사합니다.')
    text = f"{_plain(customer['name'])} 담당자님, {opening}\n\n" + '\n'.join(lines) + '\n\n' + closing
    return dict(plan_id=plan_id, request_id=p.request_id, state_revision=ws.state_revision,
                recipient=dict(id=customer['id'], name=customer['name']), text=text, requires_dispatch=dispatch,
                source='SYSTEM', template_version=VERSION,
                notice='확정된 일정의 안내 초안입니다. 수신 고객과 내용을 확인한 뒤 직접 발송하세요. 현장 작업 완료나 실제 발송을 뜻하지 않습니다.')
