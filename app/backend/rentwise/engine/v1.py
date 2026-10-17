"""B's unchanged v1 planning boundary.

Only staff changes and AS service moves inside existing promises are writable
by this solver. No candidate requires B to update rentals or dependencies.
B retains human review, revision/locking, and persistence responsibility.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from time import monotonic

from pydantic import ValidationError

from rentwise.contracts import types as c
from rentwise.contracts.v2.schema import ContractError, timestamp

from . import execution, quick

VERSION = 'rental-solver-b-v1-4'
TABLES = ('locations', 'customers', 'items', 'assets', 'rentals', 'reservations',
          'employees', 'shifts', 'jobs', 'plan_items', 'dependencies', 'travel_times')
FROZEN = {'IN_PROGRESS', 'COMPLETED', 'FAILED'}


def overlap(a, b, x, y):
    return (y is None or a < y) and (b is None or x < b)


def span(row):
    a, b = timestamp(row['start_at']), timestamp(row['end_at'])
    if b < a:
        raise ContractError(['interval'])
    return a, b


def signature(p, *, employee=True, assets=True):
    return ((p['employee_id'],) if employee else ()) + ((tuple(p['asset_ids']),) if assets else ()) + (
        timestamp(p['start_at']), timestamp(p['end_at']),
        tuple((s['kind'],s['from_id'],s['to_id'],*span(s)) for s in p['segments']))


def inspect(snapshot):
    """Check B data in place conceptually; never fill missing business records."""
    if not isinstance(snapshot,dict) or any(k not in snapshot or not isinstance(snapshot[k],list) for k in TABLES):
        raise ContractError(['snapshot.tables'])
    ix = {}
    for name in TABLES[:-1]:
        ix[name] = {r['id']:r for r in snapshot[name]}
        if len(ix[name]) != len(snapshot[name]):
            raise ContractError(['snapshot.'+name+'.duplicate_id'])
    travel = {}
    for r in snapshot['travel_times']:
        key = r['from_id'],r['to_id']
        if key in travel or any(k not in ix['locations'] for k in key) or type(r['minutes']) is not int or r['minutes']<0:
            raise ContractError(['snapshot.travel_times'])
        travel[key] = r['minutes']
    for a in ix['locations']:
        travel.setdefault((a,a),0)
        if travel[a,a] != 0:
            raise ContractError(['snapshot.travel_times.diagonal'])
    if set(travel) != {(a,b) for a in ix['locations'] for b in ix['locations']}:
        raise ContractError(['snapshot.travel_times.complete_directed_matrix'])
    warehouses = [l['id'] for l in snapshot['locations'] if l['kind']=='WAREHOUSE']
    if len(warehouses)!=1:
        raise ContractError(['snapshot.warehouse'])
    def fk(table,value,nullable=False):
        if not (nullable and value is None) and value not in ix[table]:
            raise ContractError(['snapshot.reference.'+table])
    for a in snapshot['assets']:
        fk('items',a['item_id']); fk('locations',a['location_id'],True); fk('employees',a['custody_employee_id'],True)
        if a['physical_state'] not in {'READY_WAREHOUSE','AT_CUSTOMER','IN_TRANSIT','PREP_REQUIRED','REPAIR','UNAVAILABLE','RETIRED'}:
            raise ContractError(['snapshot.assets.physical_state'])
        if a['physical_state']=='IN_TRANSIT' and a['custody_employee_id'] is None:
            raise ContractError(['snapshot.assets.custody_employee_id'])
    for r in snapshot['rentals']:
        fk('assets',r['asset_id']); fk('customers',r['customer_id'])
    for r in snapshot['reservations']:
        fk('assets',r['asset_id']); fk('rentals',r['rental_id'],True); fk('jobs',r['release_job_id'],True)
        a=timestamp(r['start_at'])
        if r['end_at'] is not None and timestamp(r['end_at'])<=a:
            raise ContractError(['snapshot.reservations.interval'])
        if r['status']=='ACTIVE' and r['rental_id'] is not None and ix['rentals'][r['rental_id']]['asset_id']!=r['asset_id']:
            raise ContractError(['snapshot.reservations.rental_asset'])
    for item in snapshot['items']:
        if type(item['prep_minutes']) is not int or item['prep_minutes']<0 or any(type(item['service_minutes_by_kind'][k]) is not int or item['service_minutes_by_kind'][k]<=0 for k in ('DELIVERY','PICKUP','AS','TRANSFER')):
            raise ContractError(['snapshot.items.durations'])
    for j in snapshot['jobs']:
        if type(j['quantity']) is not int or j['quantity']<1: raise ContractError(['snapshot.jobs.quantity'])
        fk('items',j['item_id']); fk('locations',j['from_id']); fk('locations',j['to_id'])
        for a in j['asset_ids']: fk('assets',a)
        if timestamp(j['window_end'])<timestamp(j['window_start']):
            raise ContractError(['snapshot.jobs.window'])
        timestamp(j['due_at'])
    for p in snapshot['plan_items']:
        c.PlanItem.model_validate(p)
        fk('jobs',p['job_id']); fk('employees',p['employee_id'],True)
    for s in snapshot['shifts']:
        fk('employees',s['employee_id']); fk('locations',s['start_location_id']); fk('locations',s['end_location_id'])
        a,b=span(s)
        for w in s['break_windows']:
            x,y=span(w)
            if not a<=x<y<=b: raise ContractError(['snapshot.shifts.break_windows'])
    for customer in snapshot['customers']:
        fk('locations',customer['location_id']); fk('employees',customer['preferred_employee_id'],True)
        for w in customer['visit_windows']: span(w)
    for d in snapshot['dependencies']:
        fk('jobs',d['predecessor_job_id']); fk('jobs',d['successor_job_id'])
        if type(d['minimum_gap_minutes']) is not int or d['minimum_gap_minutes']<0:
            raise ContractError(['snapshot.dependencies.minimum_gap_minutes'])
    return ix,travel,warehouses[0]


def validate(snapshot, candidate, *, new_jobs=(), movable_jobs=(), replaceable_jobs=(), as_of=None):
    """new_jobs is internal: declare only after rebuilding approved job creates."""
    try:
        ix,travel,warehouse = inspect(snapshot)
        rows=[p.model_dump() if isinstance(p,c.PlanItem) else c.PlanItem.model_validate(p).model_dump() for p in candidate]
        by_job={p['job_id']:p for p in rows}
        required={j['id'] for j in snapshot['jobs'] if j['status']!='CANCELLED'}
        if len(by_job)!=len(rows) or set(by_job)!=required:
            raise ContractError(['plan_items.coverage'])
        old={p['job_id']:p for p in snapshot['plan_items']}
        errors=[]
        def fail(code,jid=None,eid=None):
            errors.append(c.Violation(code=code,job_ids=[jid] if jid else [],employee_ids=[eid] if eid else []))
        if as_of is not None:
            for code,jid,eid in execution.violations(snapshot, rows, as_of):
                fail(code,jid,eid)
        customer_at={r['location_id']:r for r in snapshot['customers']}
        services={}
        for p in rows:
            j=ix['jobs'][p['job_id']]; jid=j['id']; kind=j['kind']; item=ix['items'][j['item_id']]
            if p['asset_ids']!=j['asset_ids'] or len(set(p['asset_ids']))!=j['quantity']:
                fail('ASSET_CHANGE_UNSUPPORTED',jid)
            if any(a not in ix['assets'] or ix['assets'][a]['item_id']!=j['item_id'] for a in p['asset_ids']):
                fail('ASSET_ITEM_MISMATCH',jid)
            for key in ('start_at','end_at'): timestamp(p[key])
            segs=p['segments']
            if not segs or span(p)!=(span(segs[0])[0],span(segs[-1])[1]):
                fail('SEGMENT_BOUNDS',jid); continue
            if jid in old:
                if j['status'] in FROZEN and signature(p)!=signature(old[jid]):
                    fail('FIXED_JOB_CHANGED',jid)
                if kind!='AS' and jid not in movable_jobs and signature(p,employee=False,assets=jid not in replaceable_jobs)!=signature(old[jid],employee=False,assets=jid not in replaceable_jobs):
                    fail('B_V1_TIME_CHANGE_UNSUPPORTED',jid)
            elif jid not in new_jobs:
                fail('NEW_JOB_UNSUPPORTED',jid)
            for prev,nxt in zip(segs,segs[1:]):
                if span(prev)[1]>span(nxt)[0] or prev['to_id']!=nxt['from_id']:
                    fail('SEGMENT_CONTINUITY',jid)
            for s in segs:
                if s['from_id'] not in ix['locations'] or s['to_id'] not in ix['locations']:
                    raise ContractError(['plan_items.segments.location'])
                if s['kind']=='TRAVEL':
                    if (span(s)[1]-span(s)[0]).total_seconds()<60*travel[s['from_id'],s['to_id']]:
                        fail('TRAVEL_TOO_SHORT',jid)
                elif s['from_id']!=s['to_id']:
                    fail('SERVICE_LOCATION',jid)
            if kind=='PREP':
                if p['employee_id'] is not None or len(segs)!=1 or segs[0]['kind']!='PREP' or segs[0]['from_id']!=warehouse:
                    fail('PREP_STRUCTURE',jid)
                if (span(p)[1]-span(p)[0]).total_seconds()<60*item['prep_minutes']:
                    fail('PREPARATION_TOO_SHORT',jid)
                if not timestamp(j['window_start'])<=span(p)[0]<=span(p)[1]<=min(timestamp(j['window_end']),timestamp(j['due_at'])):
                    fail('PREP_WINDOW',jid)
                continue
            eid=p['employee_id']
            if not quick.allowed(eid,kind,jid):
                fail('QUICK_RESOURCE_SCOPE',jid,eid)
            if eid not in ix['employees']:
                fail('EMPLOYEE_REQUIRED',jid); continue
            emp=ix['employees'][eid]
            if not emp['active'] or {'task_kind':kind,'item_category':item['category']} not in emp['skills']:
                fail('EMPLOYEE_SKILL',jid,eid)
            sv=[s for s in segs if s['kind']=='SERVICE']; services[jid]=sv
            if len(sv)!=(2 if kind=='TRANSFER' else 1) or any(s['kind']=='PREP' for s in segs):
                fail('SERVICE_STRUCTURE',jid); continue
            locations=[j['from_id'],j['to_id']] if kind=='TRANSFER' else [j['to_id'] if kind=='DELIVERY' else j['from_id']]
            if kind=='TRANSFER' and not item['direct_transfer_allowed']: fail('DIRECT_TRANSFER_DISABLED',jid)
            if (kind=='DELIVERY' and j['from_id']!=warehouse or kind=='PICKUP' and j['to_id']!=warehouse
                    or kind=='AS' and j['from_id']!=j['to_id']): fail('JOB_ROUTE',jid)
            for stop,(s,loc) in enumerate(zip(sv,locations)):
                a,b=span(s)
                if s['from_id']!=loc or (b-a).total_seconds()<60*item['service_minutes_by_kind'][kind]:
                    fail('SERVICE_DURATION_OR_LOCATION',jid)
                low,high=j['window_start'],j['window_end']
                if kind=='TRANSFER' and stop==1:
                    # B v1 stores the source window only. Match the existing v2
                    # bridge: preserve the recorded destination visit through due_at.
                    # Non-AS time/segment changes remain forbidden above.
                    baseline=[x for x in old.get(jid,{}).get('segments',[]) if x['kind']=='SERVICE']
                    if len(baseline)!=2:
                        raise ContractError(['snapshot.plan_items.TRANSFER.destination_window'])
                    low,high=baseline[1]['start_at'],j['due_at']
                if not timestamp(low)<=a<b<=timestamp(high): fail('VISIT_WINDOW',jid)
                customer=customer_at.get(loc)
                if customer is None or not any(span(w)[0]<=a and b<=span(w)[1] for w in customer['visit_windows']):
                    fail('CUSTOMER_VISIT_WINDOW',jid)
            completion=span(p)[1] if kind=='PICKUP' else span(sv[-1])[1]
            if completion>timestamp(j['due_at']): fail('DUE_AT',jid)
            if kind=='PICKUP' and segs[-1]['to_id']!=warehouse: fail('PICKUP_RETURN_REQUIRED',jid)
        for eid in ix['employees']:
            ps=sorted((p for p in rows if p['employee_id']==eid),key=lambda p:span(p)[0])
            shifts=sorted((s for s in snapshot['shifts'] if s['employee_id']==eid),key=lambda s:span(s)[0])
            for a,b in zip(shifts,shifts[1:]):
                if span(a)[1]>span(b)[0]: fail('SHIFT_OVERLAP',eid=eid)
            for a,b in zip(ps,ps[1:]):
                if span(a)[1]>span(b)[0]: fail('EMPLOYEE_OVERLAP',b['job_id'],eid)
            for p in ps:
                matching=[s for s in shifts if span(s)[0]<=span(p)[0] and span(p)[1]<=span(s)[1]]
                if len(matching)!=1: fail('OUTSIDE_SHIFT',p['job_id'],eid)
                elif any(overlap(*span(p),*span(w)) for w in matching[0]['break_windows']): fail('EMPLOYEE_BREAK',p['job_id'],eid)
            for s in shifts:
                cursor,loc=span(s)[0],s['start_location_id']
                for p in (p for p in ps if span(s)[0]<=span(p)[0] and span(p)[1]<=span(s)[1] and p['segments']):
                    departure=span(p)[0]-timedelta(minutes=travel[loc,p['segments'][0]['from_id']])
                    if departure<cursor or (departure<span(p)[0] and any(overlap(departure,span(p)[0],*span(w)) for w in s['break_windows'])):
                        fail('EMPLOYEE_TRAVEL_GAP',p['job_id'],eid)
                    cursor,loc=span(p)[1],p['segments'][-1]['to_id']
                departure=span(s)[1]-timedelta(minutes=travel[loc,s['end_location_id']])
                if cursor>departure or (departure<span(s)[1] and any(overlap(departure,span(s)[1],*span(w)) for w in s['break_windows'])):
                    fail('SHIFT_RETURN',eid=eid)
        graph=defaultdict(list); indegree={j:0 for j in ix['jobs']}
        for d in snapshot['dependencies']:
            a,b=d['predecessor_job_id'],d['successor_job_id']; graph[a].append(b); indegree[b]+=1
            if a not in by_job or b not in by_job or span(by_job[a])[1]+timedelta(minutes=d['minimum_gap_minutes'])>span(by_job[b])[0]:
                fail('DEPENDENCY_ORDER',b)
        pending=[j for j,n in indegree.items() if n==0]; visited=0
        while pending:
            j=pending.pop(); visited+=1
            for child in graph[j]:
                indegree[child]-=1
                if indegree[child]==0: pending.append(child)
        if visited!=len(indegree): fail('DEPENDENCY_CYCLE')
        booked=defaultdict(list)
        for r in snapshot['reservations']:
            if r['status']=='ACTIVE':
                booked[r['asset_id']].append(r)
                if r['review_required']: fail('RESERVATION_REVIEW_REQUIRED')
                if r['release_job_id'] is not None:
                    p=by_job.get(r['release_job_id'])
                    release_kind=ix['jobs'][r['release_job_id']]['kind']
                    release_services=[s for s in p['segments'] if s['kind']=='SERVICE'] if p else []
                    expected=span(release_services[0])[1] if release_kind=='TRANSFER' and release_services else span(p)[1] if p and release_kind=='PREP' else None
                    if expected is None or r['end_at'] is None or timestamp(r['end_at'])!=expected:
                        fail('RESERVATION_RELEASE',r['release_job_id'])
        for rs in booked.values():
            rs=sorted(rs,key=lambda r:timestamp(r['start_at']))
            for a,b in zip(rs,rs[1:]):
                if a['end_at'] is None or timestamp(a['end_at'])>timestamp(b['start_at']): fail('ASSET_RESERVATION_OVERLAP')
        for aid,asset in ix['assets'].items():
            state,loc=asset['physical_state'],asset['location_id']; free=None
            actions=[]
            for p in rows:
                j=ix['jobs'][p['job_id']]
                if aid not in p['asset_ids'] or j['status'] in FROZEN: continue
                sv=services.get(j['id'],[])
                if j['kind']!='PREP' and not sv: continue
                at=span(p)[0] if j['kind'] in ('PREP','DELIVERY') else span(sv[0])[0]
                actions.append((at,j['id'],j,p,sv))
            ongoing=any(j['status']=='IN_PROGRESS' and aid in j['asset_ids'] for j in snapshot['jobs'])
            for at,jid,j,p,sv in sorted(actions):
                if ongoing: fail('EXECUTION_IN_PROGRESS',jid)
                kind=j['kind']
                if free is not None and at<free: fail('ASSET_NOT_READY_OR_OVERLAP',jid)
                if state in ('REPAIR','UNAVAILABLE','IN_TRANSIT','RETIRED'): fail('ASSET_UNAVAILABLE',jid)
                if kind=='PREP':
                    if state!='PREP_REQUIRED' or loc!=warehouse: fail('PREP_REQUIRES_RETURN',jid)
                    state,loc,free='READY_WAREHOUSE',warehouse,span(p)[1]
                elif kind=='DELIVERY':
                    if state!='READY_WAREHOUSE' or loc!=j['from_id']: fail('DELIVERY_REQUIRES_READY',jid)
                    if not any(timestamp(r['start_at'])==span(p)[0] and (r['rental_id'] is None or ix['customers'][ix['rentals'][r['rental_id']]['customer_id']]['location_id']==j['to_id']) for r in booked[aid]):
                        fail('DELIVERY_RESERVATION_COVERAGE',jid)
                    state,loc,free='AT_CUSTOMER',j['to_id'],span(sv[-1])[1]
                else:
                    if state!='AT_CUSTOMER' or loc!=j['from_id']: fail('ASSET_LOCATION',jid)
                    if kind=='PICKUP': state,loc,free='PREP_REQUIRED',warehouse,span(p)[1]
                    elif kind=='TRANSFER': state,loc,free='AT_CUSTOMER',j['to_id'],span(sv[-1])[1]
                    else: free=span(sv[0])[1]
        return c.ValidationResult(status='INVALID' if errors else 'VALID',violations=errors,missing_fields=[])
    except ContractError as exc:
        return c.ValidationResult(status='DATA_MISSING',violations=[],missing_fields=exc.paths)
    except (KeyError,TypeError,ValueError,ValidationError):
        return c.ValidationResult(status='DATA_MISSING',violations=[],missing_fields=['snapshot/plan_items'])


def availability(inp, as_of):
    try:
        if inp.bundle_version!=c.BUNDLE_VERSION: raise ContractError(['bundle_version'])
        ix,travel,warehouse=inspect(inp.snapshot)
        start,end=max(timestamp(inp.from_at),timestamp(as_of)),timestamp(inp.to_at)
        if start>=end: raise ContractError(['from_at/to_at'])
        check=validate(inp.snapshot,inp.snapshot['plan_items'],as_of=as_of)
        if check.status=='DATA_MISSING': raise ContractError(check.missing_fields)
        blocked={aid for j in inp.snapshot['jobs'] if j['status']=='IN_PROGRESS' for aid in j['asset_ids']}
        for violation in check.violations:
            if not violation.job_ids: blocked.update(ix['assets'])
            for jid in violation.job_ids:
                blocked.update(ix['jobs'][jid]['asset_ids'])
        counts=Counter((a['item_id'],a['physical_state']) for a in inp.snapshot['assets'] if a['physical_state']!='RETIRED')
        rs=[r for r in inp.snapshot['reservations'] if r['status']=='ACTIVE']
        cuts={start,end}
        for r in rs:
            for at in (r['start_at'],r['end_at']):
                if at is not None and start<timestamp(at)<end: cuts.add(timestamp(at))
        plans={p['job_id']:p for p in inp.snapshot['plan_items']}
        windows=[]
        for a,b in zip(sorted(cuts),sorted(cuts)[1:]):
            for item in sorted(ix['items']):
                ready=[]; conditional=[]; unavailable=[]
                for asset in sorted(inp.snapshot['assets'],key=lambda r:r['id']):
                    if asset['item_id']!=item or asset['physical_state']=='RETIRED': continue
                    bookings=[r for r in rs if r['asset_id']==asset['id']]
                    if asset['id'] in blocked or any(overlap(a,b,timestamp(r['start_at']),timestamp(r['end_at']) if r['end_at'] else None) for r in bookings):
                        unavailable.append(asset['id']); continue
                    releases=[r for r in bookings if r['end_at'] is not None and timestamp(as_of)<timestamp(r['end_at'])<=a]
                    if asset['physical_state']=='READY_WAREHOUSE' and asset['location_id']==warehouse and not releases:
                        ready.append(asset['id']); continue
                    usable=[]
                    for r in releases:
                        p=plans.get(r['release_job_id']); job=ix['jobs'].get(r['release_job_id'])
                        if p and job and job['kind']=='PREP' and job['status']=='ASSIGNED' and asset['id'] in p['asset_ids']:
                            usable.append((timestamp(r['end_at']),p))
                    if usable and asset['physical_state'] not in ('REPAIR','UNAVAILABLE','IN_TRANSIT'):
                        _,p=max(usable,key=lambda x:x[0])
                        conditional.append(c.ConditionalAsset(asset_id=asset['id'],expected_ready_at=p['end_at'],
                            dependency_job_ids=[p['job_id']]))
                    else: unavailable.append(asset['id'])
                windows.append(c.AvailabilityWindow(item_id=item,from_at=a.isoformat(),to_at=b.isoformat(),
                    ready_asset_ids=ready,conditional_assets=conditional,unavailable_asset_ids=unavailable))
        return c.AvailabilityResult(status='OK',base_state_revision=inp.base_state_revision,
            physical_counts=[c.PhysicalCount(item_id=i,physical_state=s,count=n) for (i,s),n in sorted(counts.items())],
            windows=windows,missing_fields=[])
    except ContractError as exc: paths=exc.paths
    except (KeyError,TypeError,ValueError): paths=['snapshot']
    return c.AvailabilityResult(status='DATA_MISSING',base_state_revision=inp.base_state_revision,physical_counts=[],windows=[],missing_fields=paths)


def solve(inp, as_of):
    started=monotonic(); examined=0; limited=False
    def result(status,rows=(),code=None,violations=()):
        return c.SolverResult(status=status,candidate_items=[c.PlanItem(**p) for p in rows],reservation_changes=[],
            affected_job_ids=sorted({op.target_job_id for op in inp.operations if op.target_job_id} | {o['job_id'] for o in inp.overrides if isinstance(o.get('job_id'),str)}),
            impact_edges=[],violations=list(violations),unresolved=[c.Unresolved(job_id=None,code=code,details={})] if code else [],
            objective=[],search_stats=c.SearchStats(elapsed_ms=max(0,int((monotonic()-started)*1000)),candidates_examined=examined,limit_reached=limited),
            input_hash=inp.input_hash,solver_version=VERSION)
    try:
        if inp.bundle_version!=c.BUNDLE_VERSION: return result('DATA_MISSING',code='INVALID_BUNDLE')
        body=inp.model_dump(exclude={'schema_version','bundle_version','input_hash'})
        expected='sha256:'+hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if inp.input_hash!=expected: return result('DATA_MISSING',code='INVALID_INPUT_HASH')
        ix,travel,warehouse=inspect(inp.snapshot)
        if {r['version'] for r in inp.snapshot['travel_times']}!={inp.travel_version}:
            return result('DATA_MISSING',code='TRAVEL_VERSION_MISMATCH')
        check=validate(inp.snapshot,inp.snapshot['plan_items'],as_of=as_of)
        if check.status=='DATA_MISSING': return result('DATA_MISSING',code='BASE_PLAN_INVALID',violations=check.violations)
        if not 1<=inp.max_candidates<=1000 or not 1<=inp.max_search_ms<=2000:
            return result('DATA_MISSING',code='INVALID_SEARCH_LIMIT')
        if not timedelta(0)<timestamp(inp.horizon_end)-timestamp(inp.horizon_start)<=timedelta(days=7): return result('DATA_MISSING',code='INVALID_HORIZON')
        if {p['plan_id'] for p in inp.snapshot['plan_items']}!={inp.base_plan_id}: return result('NEEDS_REVIEW',code='STALE_PLAN')
        if execution.stale_jobs(inp.snapshot, as_of):
            return result('NEEDS_REVIEW',code='EXECUTION_STATUS_REQUIRED',violations=check.violations)
        jobs=deepcopy(ix['jobs']); old={p['job_id']:p for p in inp.snapshot['plan_items']}
        overrides={o['job_id']:o for o in inp.overrides}
        if len(overrides)!=len(inp.overrides): return result('NEEDS_REVIEW',code='INVALID_OVERRIDE')
        operations={}
        for op in inp.operations:
            if op.operation!='RESCHEDULE' or op.target_job_id not in jobs or op.target_job_id in operations:
                return result('NEEDS_REVIEW',code='B_V1_UNSUPPORTED_OPERATION')
            j=jobs[op.target_job_id]; raw=op.model_dump(exclude_unset=True)
            if j['kind']!=op.kind: return result('NEEDS_REVIEW',code='INVALID_OPERATION_KIND')
            for field,location in (('source_customer_id',j['from_id']),('destination_customer_id',j['to_id'])):
                customer=raw.get(field)
                if customer is not None and (customer not in ix['customers'] or ix['customers'][customer]['location_id']!=location):
                    return result('NEEDS_REVIEW',code='B_V1_PERSISTENCE_UNSUPPORTED')
            for k in ('item_id','asset_ids','quantity','from_id','to_id','rental_end_at'):
                # Intent's nullable values mean unmentioned on RESCHEDULE. B passes
                # quantity/rental_end_at null through; preserve the stored condition.
                if k in raw and raw[k] is not None and raw[k]!=j[k]: return result('NEEDS_REVIEW',code='B_V1_PERSISTENCE_UNSUPPORTED')
            if any(raw.get(k) is None for k in ('window_start','window_end','due_at')):
                return result('NEEDS_REVIEW',code='UNCONFIRMED_FIELDS')
            if not (timestamp(j['window_start'])<=timestamp(op.window_start)<timestamp(op.window_end)<=timestamp(j['window_end'])
                    and timestamp(op.due_at)<=timestamp(j['due_at'])):
                return result('NEEDS_REVIEW',code='B_V1_PERSISTENCE_UNSUPPORTED')
            j.update(window_start=op.window_start,window_end=op.window_end,due_at=op.due_at)
            operations[j['id']]=op
        affected=sorted(set(operations)|set(overrides))
        if len(affected)>3: return result('NO_SOLUTION_FOUND',code='SEARCH_SCOPE_LIMIT')
        for jid in affected:
            if jid not in jobs or jobs[jid]['status'] in FROZEN or jobs[jid]['kind']=='PREP':
                return result('NEEDS_REVIEW',code='B_V1_UNSUPPORTED_OPERATION')
            o=overrides.get(jid,{})
            if set(o)-{'job_id','employee_id','start_at','asset_ids'} or ('asset_ids' in o and o['asset_ids']!=jobs[jid]['asset_ids']):
                return result('NEEDS_REVIEW',code='B_V1_PERSISTENCE_UNSUPPORTED')
            if 'employee_id' in o and o['employee_id'] not in ix['employees']: return result('NEEDS_REVIEW',code='INVALID_OVERRIDE')
            sv=next(s for s in old[jid]['segments'] if s['kind']=='SERVICE')
            if 'start_at' in o and timestamp(o['start_at'])!=timestamp(sv['start_at']) and (jobs[jid]['kind']!='AS' or jid not in operations):
                return result('NEEDS_REVIEW',code='B_V1_PERSISTENCE_UNSUPPORTED')
        best=None; best_key=None; last=[]
        def visit(depth,selected):
            nonlocal examined,limited,best,best_key,last
            if depth==len(affected):
                rows=[selected.get(jid,deepcopy(p)) for jid,p in sorted(old.items())]
                candidate_snapshot={**inp.snapshot,'jobs':list(jobs.values())}
                checked=validate(candidate_snapshot,rows,as_of=as_of)
                if checked.status=='VALID':
                    key=(sum(p['employee_id']!=old[p['job_id']]['employee_id'] for p in rows),
                         tuple((p['employee_id'] or '',p['start_at'],p['job_id']) for p in rows))
                    if best_key is None or key<best_key: best,best_key=rows,key
                else: last=checked.violations
                return
            jid=affected[depth]; j=jobs[jid]; p=old[jid]; o=overrides.get(jid,{})
            service=next(s for s in p['segments'] if s['kind']=='SERVICE')
            starts=[timestamp(service['start_at'])]
            if j['kind']=='AS' and jid in operations:
                minutes=ix['items'][j['item_id']]['service_minutes_by_kind']['AS']
                low=max(timestamp(j['window_start']),timestamp(as_of),timestamp(inp.horizon_start)); high=min(timestamp(j['window_end']),timestamp(j['due_at']),timestamp(inp.horizon_end))-timedelta(minutes=minutes)
                starts=[]; cursor=low
                if 'start_at' in o: starts=[timestamp(o['start_at'])]
                else:
                    while cursor<=high:
                        starts.append(cursor); cursor+=timedelta(minutes=5)
            employees=sorted(ix['employees'].values(),key=lambda e:(e['id']!=p['employee_id'],e['id']))
            for emp in employees:
                if quick.is_quick(emp['id']) and o.get('employee_id')!=emp['id']: continue
                if 'employee_id' in o and emp['id']!=o['employee_id']: continue
                for start in starts:
                    if examined>=inp.max_candidates or (monotonic()-started)*1000>=inp.max_search_ms:
                        limited=True; return
                    examined+=1; option=deepcopy(p); option.update(id=None,plan_id=None,employee_id=emp['id'])
                    if j['kind']=='AS':
                        delta=start-timestamp(service['start_at'])
                        for s in option['segments']:
                            for key in ('start_at','end_at'): s[key]=(timestamp(s[key])+delta).isoformat()
                        option.update(start_at=option['segments'][0]['start_at'],end_at=option['segments'][-1]['end_at'])
                    if timestamp(option['start_at'])<timestamp(as_of) or not timestamp(inp.horizon_start)<=timestamp(option['start_at'])<timestamp(option['end_at'])<=timestamp(inp.horizon_end): continue
                    option['reason_codes']=['STAFF_REASSIGNED'] if emp['id']!=p['employee_id'] else []
                    visit(depth+1,{**selected,jid:option})
                    if limited: return
        visit(0,{})
        if best is None: return result('NO_SOLUTION_FOUND',code='SEARCH_LIMIT' if limited else 'NO_VALID_CANDIDATE',violations=last)
        for p in best: p.update(id=None,plan_id=None)
        return result('FEASIBLE',best)
    except (KeyError,TypeError,ValueError,StopIteration,ContractError):
        return result('DATA_MISSING',code='INVALID_INPUT')
