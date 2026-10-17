"""Capacity and independent validation boundaries for dispatch alternatives."""
from copy import deepcopy
from datetime import timedelta

import pytest

from rentwise.engine import quick, staff, validate
from tests.engine.sample import candidate, snapshot, t


@pytest.mark.parametrize('case,expected', [('available', True), ('off_grid', True), ('shift_closed', False),
                                         ('no_skill', False), ('no_visit', None), ('too_short', None)])
def test_capacity_distinguishes_staff_from_invalid_customer_constraints(case, expected):
    s = snapshot()
    job = {**s['jobs'][2], 'window_start': t('17:00'), 'window_end': t('17:15'), 'due_at': t('17:15')}
    if case == 'off_grid':
        job.update(window_start=t('17:02'), window_end=t('17:17'), due_at=t('17:17'))
    if case == 'shift_closed':
        for shift in s['shifts']:
            shift['end_at'] = t('17:00')
    if case == 'no_skill':
        for e in s['employees']:
            e['skills'] = [sk for sk in e['skills'] if sk['task_kind'] != 'DELIVERY']
    if case == 'no_visit':
        s['customers'][1]['visit_windows'][0]['end'] = t('16:00')
    if case == 'too_short':
        job['window_end'] = t('17:05')
    before = deepcopy(s)
    assert staff.available(s, job) is expected
    assert s == before


def test_downstream_staff_check_keeps_exact_customer_promise():
    from rentwise.services.dispatch_fallback import _staff_job
    s = snapshot()
    job = {**s['jobs'][2], 'window_end': t('18:00'), 'due_at': t('18:00')}
    for sh in s['shifts']:
        sh['break_windows'] = [dict(start=t('11:30'), end=t('12:45'))]
    assert staff.available(s, job) is True  # A later slot exists, but it is not approved.
    fixed = _staff_job(dict(snapshot=s, approved_job_ids=['PICK']), job)
    assert staff.available(s, fixed) is False


@pytest.mark.parametrize('target,kind', [('OTHER', 'DELIVERY'), ('PICK', 'PICKUP'), ('DEL', 'AS')])
def test_quick_resource_cannot_be_reused_even_with_forged_skills(target, kind):
    s = snapshot()
    c = candidate(s)
    eid = quick.resource_id(target)
    s['employees'].append({**deepcopy(s['employees'][0]), 'id': eid})
    s['shifts'].append({**deepcopy(s['shifts'][0]), 'id': 'QS-test', 'employee_id': eid})
    jid = 'PICK' if kind == 'PICKUP' else 'DEL'
    next(p for p in c['plan_items'] if p['job_id'] == jid)['employee_id'] = eid
    if kind == 'AS':
        next(j for j in c['jobs'] if j['id'] == jid)['kind'] = kind
    result = validate(s, c)
    assert result['status'] == 'INVALID'
    assert 'QUICK_RESOURCE_SCOPE' in {v['code'] for v in result['violations']}


@pytest.mark.parametrize('case', ['approved', 'unapproved', 'active', 'historical', 'unbound'])
def test_only_approved_unstarted_bound_delivery_can_move_booking_start(case):
    s = snapshot()
    c = candidate(s)
    c['approved_job_ids'] = [] if case == 'unapproved' else ['DEL']
    c['jobs'][2].update(window_start=t('17:00'), window_end=t('17:15'), due_at=t('17:15'))
    p = c['plan_items'][2]
    from rentwise.contracts.v2.schema import timestamp
    delta = timedelta(hours=5)
    for row in [p, *p['segments_json']]:
        for k in ('start_at', 'end_at'):
            row[k] = (timestamp(row[k]) + delta).isoformat()
    c['reservations'][1]['start_at'] = p['start_at']
    if case == 'active':
        s['rentals'][1]['status'] = c['rentals'][1]['status'] = 'ACTIVE'
        s['rentals'][1]['actual_start'] = c['rentals'][1]['actual_start'] = t('11:40')
    if case == 'historical':
        s['reservations'][1]['start_at'] = '2026-10-15T11:40:00+09:00'
        s['plan_items'][2]['start_at'] = '2026-10-15T11:40:00+09:00'
    if case == 'unbound':
        s['reservations'][1]['start_at'] = t('11:35')
    result = validate(s, c)
    if case == 'approved':
        assert result['status'] == 'VALID', result
    else:
        assert result['status'] == 'INVALID'
        assert 'RESERVATION_START_TRUNCATED' in {v['code'] for v in result['violations']}
