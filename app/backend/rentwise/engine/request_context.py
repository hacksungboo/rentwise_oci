"""Bounded, confirmable suggestions from an explicitly referenced old visit.

This is not a general Korean date parser. Missing/duplicate anchors, multiple
clauses, or inconsistent directions leave the original confirmation questions.
"""
from datetime import datetime, timedelta
import re

from rentwise.timeutil import KST

CLOCK = r'(?:(오전|오후)\s*)?(\d{1,2})\s*시\s*(?:(반)|(\d{1,2})\s*분)?'
CHANGE = re.compile(
    r'(?P<day>오늘|내일|모레)\s*(?P<old>' + CLOCK + r')'
    r'(?P<label>[^.!?\n~～]{1,45}?)[을를]\s*'
    r'(?P<newday>오늘|내일|모레)?\s*(?P<start>' + CLOCK + r')\s*(?:~|～|부터|에서)\s*'
    r'(?P<end>' + CLOCK + r')\s*(?:사이)?\s*(?:로|까지로?|사이에)?\s*'
    r'(?P<direction>당겨|앞당겨|미뤄|늦춰|변경|옮겨|바꿔)')
CLOCK_RE = re.compile(CLOCK)
DAYS = {'오늘': 0, '내일': 1, '모레': 2}


def _clock(text):
    match = CLOCK_RE.fullmatch(text.strip())
    if not match:
        return None
    meridiem, hour, half, minute = match.groups()
    hour, minute = int(hour), 30 if half else int(minute or 0)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59 or (meridiem and not 1 <= hour <= 12):
        return None
    hours = [hour % 12 + (12 if meridiem == '오후' else 0)] if meridiem else ([hour % 12, hour % 12 + 12] if 1 <= hour <= 12 else [hour])
    return hours, minute, bool(meridiem or hour > 12 or hour == 0)


def candidates(inp, op):
    customer = op.destination_customer_id if op.kind == 'DELIVERY' else op.source_customer_id
    return [j for j in inp.existing_jobs if j['kind'] == op.kind and customer is not None
            and j.get('customer_id') == customer
            and (op.item_id is None or j.get('item_id') == op.item_id)]


def match_change(inp, op):
    if op.operation != 'RESCHEDULE':
        return None
    matches = list(CHANGE.finditer(inp.text))
    if len(matches) != 1:
        return None
    m = matches[0]
    # Several changes/times outside this bounded clause must be reviewed by a person.
    if CLOCK_RE.search(inp.text[:m.start()] + inp.text[m.end():]):
        return None
    old, start, end = (_clock(m[k]) for k in ('old', 'start', 'end'))
    if not all((old, start, end)):
        return None
    day = datetime.fromisoformat(inp.received_at).astimezone(KST).date()
    old_day = day + timedelta(days=DAYS[m['day']])
    found = []
    for job in candidates(inp, op):
        if not job.get('window_start'):
            continue
        when = datetime.fromisoformat(job['window_start']).astimezone(KST)
        if when.date() == old_day and when.hour in old[0] and when.minute == old[1]:
            found.append((job, when))
    if len(found) != 1:
        return None
    job, old_time = found[0]
    new_day = day + timedelta(days=DAYS[m['newday'] or m['day']])
    options = []
    for hour in start[0]:
        a = datetime.combine(new_day, datetime.min.time(), KST).replace(hour=hour, minute=start[1])
        # Preserve the old half-day only as a labeled suggestion, never approval.
        if not start[2] and (hour >= 12) != (old_time.hour >= 12):
            continue
        for last_hour in end[0]:
            if not end[2] and (last_hour >= 12) != (hour >= 12):
                continue
            b = a.replace(hour=last_hour, minute=end[1])
            if not a < b or b - a > timedelta(hours=12):
                continue
            if m['direction'] in ('당겨', '앞당겨') and not a < old_time:
                continue
            if m['direction'] in ('미뤄', '늦춰') and not a > old_time:
                continue
            options.append((a, b))
    if len(options) != 1:
        return None
    a, b = options[0]
    return dict(job=job, start=a.isoformat(), end=b.isoformat(), old=old_time.isoformat(),
                inferred=not start[2] or not end[2])
