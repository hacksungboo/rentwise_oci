"""Status-only execution fences shared by B v1 and the v2 pickup core.

COMPLETED means the entire plan block, including travel, has finished. No
predicted end releases an IN_PROGRESS employee. Without actual completion
order, all completed endpoints in the shift are possible current positions.
"""
from datetime import timedelta

from rentwise.contracts.v2.schema import timestamp

FROZEN = {'IN_PROGRESS', 'COMPLETED', 'FAILED'}


def stale_jobs(snapshot, as_of):
    now = timestamp(as_of)
    jobs = {j['id']: j for j in snapshot['jobs']}
    return sorted(p['job_id'] for p in snapshot['plan_items']
        if jobs[p['job_id']]['status'] not in FROZEN | {'CANCELLED'} and timestamp(p['start_at']) < now)


def _signature(p, segments):
    return (p['employee_id'], tuple(p['asset_ids']), timestamp(p['start_at']), timestamp(p['end_at']),
        tuple((s['kind'], s['from_id'], s['to_id'], timestamp(s['start_at']), timestamp(s['end_at']))
            for s in p[segments]))


def violations(snapshot, rows, as_of, *, segments='segments'):
    """Yield (code, job_id, employee_id); inputs have already passed shape checks."""
    now = timestamp(as_of)
    jobs = {j['id']: j for j in snapshot['jobs']}
    old = {p['job_id']: p for p in snapshot['plan_items']}
    for jid in stale_jobs(snapshot, as_of):
        yield 'EXECUTION_STATUS_REQUIRED', jid, old[jid]['employee_id']
    travel = {(t['from_id'], t['to_id']): t['minutes'] for t in snapshot['travel_times']}
    for loc in snapshot['locations']:
        travel.setdefault((loc['id'], loc['id']), 0)
    for p in rows:
        jid, eid = p['job_id'], p['employee_id']
        previous = old.get(jid)
        changed = previous is None or _signature(p, segments) != _signature(previous, segments)
        if not changed:
            continue
        if previous is not None and (jobs[jid]['status'] in FROZEN or timestamp(previous['start_at']) < now):
            yield 'EXECUTION_FIXED_JOB_CHANGED', jid, eid
        if timestamp(p['start_at']) < now:
            yield 'EXECUTION_START_PASSED', jid, eid
        if eid is None or not p[segments]:
            continue
        history = [r for r in old.values() if r['employee_id'] == eid]
        if any(jobs[r['job_id']]['status'] == 'IN_PROGRESS' for r in history):
            yield 'EMPLOYEE_EXECUTION_IN_PROGRESS', jid, eid
            continue
        shifts = [s for s in snapshot['shifts'] if s['employee_id'] == eid
            and timestamp(s['start_at']) <= timestamp(p['start_at']) < timestamp(s['end_at'])]
        if len(shifts) != 1:
            continue  # The ordinary validator reports missing/overlapping shifts.
        shift = shifts[0]
        history = [r for r in history if timestamp(r['end_at']) >= timestamp(shift['start_at'])
            and timestamp(r['start_at']) < timestamp(shift['end_at'])]
        if any(jobs[r['job_id']]['status'] == 'FAILED' for r in history):
            yield 'EMPLOYEE_POSITION_UNCONFIRMED', jid, eid
            continue
        # A preceding future block provides a planned anchor; normal whole-path
        # validation checks its continuity. Historical travel cannot pay for a
        # newly inserted departure after now.
        preceding = [r for r in rows if r['employee_id'] == eid and r['job_id'] != jid
            and jobs.get(r['job_id'], {}).get('status') not in FROZEN | {'CANCELLED'}
            and now <= timestamp(r['start_at']) and timestamp(r['end_at']) <= timestamp(p['start_at'])]
        if preceding:
            continue
        origins = {r[segments][-1]['to_id'] for r in history
            if jobs[r['job_id']]['status'] == 'COMPLETED' and r[segments]}
        if not origins:
            origins = {shift['start_location_id']}
        departure_to = p[segments][0]['from_id']
        for loc in sorted(origins):
            depart = timestamp(p['start_at']) - timedelta(minutes=travel[loc, departure_to])
            breaks = [(timestamp(w.get('start_at', w.get('start'))), timestamp(w.get('end_at', w.get('end'))))
                for w in shift['break_windows']]
            if depart < max(now, timestamp(shift['start_at'])) or any(
                    depart < b and a < timestamp(p['start_at']) for a, b in breaks if depart < timestamp(p['start_at'])):
                yield 'EMPLOYEE_CURRENT_TRAVEL_GAP', jid, eid
                break
