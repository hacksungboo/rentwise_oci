"""Shared calendar checks for solver candidates and dispatch fallback decisions."""
from datetime import timedelta

from rentwise.contracts.v2.schema import timestamp
from .common import interval, overlaps, route_fits
from .quick import is_quick


def fits(employee, plans, shifts, travel):
    plans = sorted((p for p in plans if p['employee_id'] == employee), key=lambda p: timestamp(p['start_at']))
    shifts = [s for s in shifts if s['employee_id'] == employee]
    for row in plans:
        matching = [s for s in shifts if timestamp(s['start_at']) <= timestamp(row['start_at'])
                    and timestamp(row['end_at']) <= timestamp(s['end_at'])]
        if not matching or any(overlaps(interval(row['start_at'], row['end_at']), interval(w['start'], w['end']))
                               for w in matching[0]['break_windows']):
            return False
    for shift in shifts:
        cursor, location = timestamp(shift['start_at']), shift['start_location_id']
        for row in plans:
            if not timestamp(shift['start_at']) <= timestamp(row['start_at']) < timestamp(shift['end_at']):
                continue
            if not row['segments_json'] or not route_fits(cursor, timestamp(row['start_at']), location,
                    row['segments_json'][0]['from_id'], shift, travel):
                return False
            cursor, location = timestamp(row['end_at']), row['segments_json'][-1]['to_id']
        if not route_fits(cursor, timestamp(shift['end_at']), location, shift['end_location_id'], shift, travel):
            return False
    return True


def available(snapshot, job):
    """True/False for internal capacity; None if the request itself has no legal visit slot."""
    item = next(i for i in snapshot['items'] if i['id'] == job['item_id'])
    employees = [e for e in snapshot['employees'] if e['active'] and not is_quick(e['id'])
                 and {'task_kind': job['kind'], 'item_category': item['category']} in e['skills']]
    warehouse = next(l['id'] for l in snapshot['locations'] if l['kind'] == 'WAREHOUSE')
    location = job['to_id'] if job['kind'] == 'DELIVERY' else job['from_id']
    customer = next((c for c in snapshot['customers'] if c['location_id'] == location), None)
    if customer is None:
        return None
    travel = {(t['from_id'], t['to_id']): t['minutes'] for t in snapshot['travel_times']}
    minutes = item['service_minutes_by_kind'][job['kind']]
    start = max(timestamp(job['window_start']), timestamp(snapshot['as_of']))
    end = min(timestamp(job['window_end']), timestamp(job['due_at']))
    if timestamp(job['window_end']) - timestamp(job['window_start']) != timedelta(minutes=minutes):
        rounded = start.replace(second=0, microsecond=0) + timedelta(minutes=(-start.minute) % 5)
        start = rounded if rounded >= start else rounded + timedelta(minutes=5)
    kept = [p for p in snapshot['plan_items'] if p['job_id'] != job['id']]
    legal_slot = False
    while start + timedelta(minutes=minutes) <= end:
        service_end = start + timedelta(minutes=minutes)
        depart = start - timedelta(minutes=travel[warehouse, location])
        returned = service_end + timedelta(minutes=travel[location, warehouse])
        if (depart >= timestamp(snapshot['as_of']) and (job['kind'] != 'PICKUP' or returned <= timestamp(job['due_at']))
                and any(timestamp(w['start']) <= start and service_end <= timestamp(w['end']) for w in customer['visit_windows'])):
            legal_slot = True
            segments = [dict(kind='TRAVEL', from_id=warehouse, to_id=location, start_at=depart.isoformat(), end_at=start.isoformat()),
                        dict(kind='SERVICE', from_id=location, to_id=location, start_at=start.isoformat(), end_at=service_end.isoformat()),
                        dict(kind='TRAVEL', from_id=location, to_id=warehouse, start_at=service_end.isoformat(), end_at=returned.isoformat())]
            for employee in employees:
                p = dict(employee_id=employee['id'], start_at=depart.isoformat(), end_at=returned.isoformat(), segments_json=segments)
                if fits(employee['id'], [*kept, p], snapshot['shifts'], travel):
                    return True
        start += timedelta(minutes=5)
    return False if legal_slot else None
