"""Bounded normal-delivery / delayed-pickup planning, without model or DB access.

All returned complete candidates pass the independent validator. A search miss
is never an impossibility proof. Operational IDs and approvals come from B.
"""

from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
from itertools import chain
from time import monotonic

from rentwise.contracts.v2.normalize import normalize_operation
from rentwise.contracts.v2.schema import ContractError, check_contract, timestamp
from rentwise.contracts.v2.serialization import solver_input_hash
from rentwise.contracts.v2.types import SolverInput, SolverResult

from . import execution
from .common import FROZEN, check_references, interval, overlaps, route_fits
from .validate import validate

SOLVER_VERSION = "rental-solver-normal-delay-v2"
ASSET_EDGES = {"READY_DELIVERY", "PREPARATION_DEPENDENCY", "ASSET_READY"}
INTERNAL_TABLES = ("jobs", "plan_items", "rentals", "reservations", "dependencies")
EMPLOYEE_CODES = {"EMPLOYEE_BREAK", "EMPLOYEE_OVERLAP", "EMPLOYEE_TRAVEL_GAP", "SHIFT_RETURN", "OUTSIDE_SHIFT", "EMPLOYEE_SKILL"}


class _StopSearch(Exception):
    pass


class _Review(Exception):
    def __init__(self, code, job_id=None, details=None, status="NEEDS_REVIEW"):
        self.code, self.job_id, self.details, self.status = code, job_id, details or {}, status


def solve(input: SolverInput) -> SolverResult:
    started = monotonic()
    supplied_hash = input.get("input_hash", "") if isinstance(input, dict) else ""
    result = dict(schema_version="rental.solver-result.v2", status="NO_SOLUTION_FOUND",
                  candidate_plan=None, candidate_items=[], reservation_changes=[], affected_job_ids=[],
                  impact_edges=[], violations=[], unresolved=[], objective=[],
                  search_stats=dict(elapsed_ms=0, candidates_examined=0, limit_reached=False),
                  input_hash=supplied_hash if isinstance(supplied_hash, str) else "", solver_version=SOLVER_VERSION)
    search = None
    try:
        check_contract("SolverInput", input)
        ix, travel = check_references(input["snapshot"])
        if solver_input_hash(input) != input["input_hash"]:
            raise ContractError(["input.input_hash"])
        stale = execution.stale_jobs(input["snapshot"], input["snapshot"]["as_of"])
        if stale:
            raise _Review("EXECUTION_STATUS_REQUIRED", stale[0], {"job_ids": stale})
        search = _Search(input, ix, travel, result, started)
        proof = search.proof()
        if proof is not None:
            raise proof
        try:
            search.visit(0, {})
        except _StopSearch:
            result["search_stats"]["limit_reached"] = True
        if search.best is not None:
            candidate, objective = search.best
            search.explain(candidate)
            result.update(status="FEASIBLE", candidate_plan=candidate,
                          candidate_items=deepcopy(candidate["plan_items"]), objective=objective,
                          reservation_changes=search.reservation_changes(candidate),
                          affected_job_ids=sorted(search.affected), impact_edges=search.impact_edges(candidate))
        else:
            result["violations"] = search.last_violations
            result["unresolved"] = [dict(job_id=None, code="SEARCH_LIMIT" if result["search_stats"]["limit_reached"] else "NO_VALID_CANDIDATE", details={"scope": "normal_delivery_delayed_pickup"})]
    except ContractError as exc:
        unconfirmed = all(path.endswith(".confirmed") for path in exc.paths)
        result.update(status="NEEDS_REVIEW" if unconfirmed else "DATA_MISSING",
                      unresolved=[dict(job_id=None, code="UNCONFIRMED_OPERATION" if unconfirmed else "INVALID_INPUT", details={"fields": exc.paths})])
    except _Review as exc:
        result.update(status=exc.status, unresolved=[dict(job_id=exc.job_id, code=exc.code, details=exc.details)])
    result["search_stats"]["elapsed_ms"] = max(0, int((monotonic() - started) * 1000))
    check_contract("SolverResult", result, "result")
    return result


class _Search:
    def __init__(self, input, ix, travel, result, started):
        self.input, self.snapshot, self.ix, self.travel = input, input["snapshot"], ix, travel
        self.result, self.started, self.best, self.best_key = result, started, None, None
        self.last_violations = []
        self.warehouse = next(x["id"] for x in self.snapshot["locations"] if x["kind"] == "WAREHOUSE")
        self.old_plans = {p["job_id"]: p for p in self.snapshot["plan_items"]}
        if (len(self.old_plans) != len(self.snapshot["plan_items"])
                or any(j["status"] in (FROZEN | {"ASSIGNED"}) and j["id"] not in self.old_plans for j in self.snapshot["jobs"])
                or any(ix["jobs"][p["job_id"]]["status"] == "CANCELLED" for p in self.snapshot["plan_items"])):
            raise ContractError(["snapshot.plan_items.coverage"])
        self.customers = {c["location_id"]: c for c in self.snapshot["customers"]}
        self.candidate = {k: deepcopy(self.snapshot[k]) for k in INTERNAL_TABLES}
        self.candidate["reservations"] = [r for r in self.candidate["reservations"] if r["status"] == "ACTIVE"]
        self.candidate.update(schema_version="rental.candidate.v2", bundle_version=input["bundle_version"],
                              base_state_revision=input["base_state_revision"], plan_id=input["plan_id"],
                              approved_job_ids=deepcopy(input["approved_job_ids"]))
        self.jobs = {j["id"]: j for j in self.candidate["jobs"]}
        self.operations = {}
        self._check_metadata()
        for op in input["operations"]:
            jid = op["job"]["id"]
            if jid in self.operations:
                raise ContractError(["input.operations.duplicate_job"])
            if (op["operation"], op["job"]["kind"]) not in (("CREATE", "DELIVERY"), ("RESCHEDULE", "PICKUP")):
                raise _Review("UNSUPPORTED_OPERATION", jid)
            if op["job"]["quantity"] != 1:
                raise _Review("MULTI_ASSET_NOT_SUPPORTED", jid)
            if jid not in input["approved_job_ids"]:
                raise _Review("CUSTOMER_APPROVAL_REQUIRED", jid)
            if op["target_job_id"] in ix["jobs"] and ix["jobs"][op["target_job_id"]]["status"] in FROZEN:
                raise _Review("FIXED_JOB_CHANGED", jid)
            normalized = normalize_operation(self.snapshot, op["operation"], op["target_job_id"], op["job"],
                                             confirmed=op["confirmed"], rental_id=op["rental_id"],
                                             return_policy=op["return_policy"], prep_job=op["prep_job"])
            if normalized != op:
                raise ContractError(["operations.normalized_payload"])
            if not (timestamp(input["horizon_start"]) <= timestamp(op["job"]["window_start"]) < timestamp(op["job"]["window_end"]) <= timestamp(input["horizon_end"])):
                raise _Review("OUT_OF_HORIZON", jid)
            if op["job"]["status"] not in ("ASSIGNED", "UNASSIGNED"):
                raise _Review("EXECUTION_STATE_CHANGED", jid)
            self.operations[jid] = op
            self.jobs[jid] = deepcopy(op["job"])
            if op["prep_job"] is not None:
                prep = op["prep_job"]
                # New pickup/PREP relationships need a separate, explicit ID contract.
                if prep["id"] not in ix["jobs"] or ix["jobs"][prep["id"]]["kind"] != "PREP":
                    raise _Review("NEW_PREPARATION_NOT_SUPPORTED", jid)
                self.jobs[prep["id"]] = deepcopy(prep)
        self.overrides = {x["job_id"]: x for x in input["overrides"]}
        if len(self.overrides) != len(input["overrides"]) or not self.overrides.keys() <= self.jobs.keys():
            raise _Review("INVALID_OVERRIDE")
        for jid, override in self.overrides.items():
            if self.jobs[jid]["status"] in FROZEN:
                raise _Review("FIXED_JOB_CHANGED", jid)
            if self.jobs[jid]["kind"] == "PREP" and ("employee_id" in override or "asset_ids" in override):
                raise _Review("INVALID_OVERRIDE", jid)
            old_service = next((s for s in self.old_plans.get(jid, {}).get("segments_json", []) if s["kind"] == "SERVICE"), None)
            if "start_at" in override and old_service and timestamp(override["start_at"]) != timestamp(old_service["start_at"]) and jid not in input["approved_job_ids"]:
                raise _Review("CUSTOMER_APPROVAL_REQUIRED", jid)
            if "employee_id" in override and override["employee_id"] not in ix["employees"]:
                raise _Review("INVALID_OVERRIDE", jid)
            if "asset_ids" in override and (len(override["asset_ids"]) != 1 or override["asset_ids"][0] not in ix["assets"] or ix["assets"][override["asset_ids"][0]]["item_id"] != self.jobs[jid]["item_id"]):
                raise _Review("INVALID_OVERRIDE", jid)
        self.affected, self.order = self._impact_order()
        self.result["affected_job_ids"] = sorted(self.affected)
        if len(self.order) > 3:
            raise _Review("SEARCH_SCOPE_LIMIT", details={"max_changed_jobs": 3}, status="NO_SOLUTION_FOUND")
        for jid in self.order:
            j = self.jobs[jid]
            if j["kind"] not in ("DELIVERY", "PICKUP", "PREP") or j["quantity"] != 1:
                raise _Review("UNSUPPORTED_AFFECTED_JOB", jid)
            if j["kind"] == "PICKUP" and jid not in self.operations:
                raise _Review("UNSUPPORTED_AFFECTED_PICKUP", jid)
        self.candidate["jobs"] = sorted(self.jobs.values(), key=lambda j: j["id"])
        self.allocations = self._allocations()
        for p in self.candidate["plan_items"]:
            p.update(id=self.allocations["plan_items"][p["job_id"]], plan_id=input["plan_id"])
        if len(set(input["approved_job_ids"])) != len(input["approved_job_ids"]) or not set(input["approved_job_ids"]) <= self.jobs.keys():
            raise ContractError(["input.approved_job_ids"])
        self.kept = [p for p in self.candidate["plan_items"] if p["job_id"] not in self.order]
        self._check_rental_bindings()

    def _check_metadata(self):
        i, s = self.input, self.snapshot
        if i["base_state_revision"] != s["state_revision"]:
            raise _Review("STALE_SNAPSHOT")
        for key in ("dataset_version", "travel_version", "policy_version", "horizon_start", "horizon_end"):
            if i[key] != s[key]:
                raise ContractError(["input." + key])
        plan_ids = {p["plan_id"] for p in s["plan_items"]}
        if (plan_ids and plan_ids != {i["base_plan_id"]}) or (not plan_ids and i["base_plan_id"] is not None):
            raise _Review("STALE_PLAN")
        if i["plan_id"] == i["base_plan_id"]:
            raise ContractError(["input.plan_id"])

    def _impact_order(self):
        graph, indegree = defaultdict(list), {jid: 0 for jid in self.jobs}
        for edge in self.candidate["dependencies"]:
            a, b = edge["predecessor_job_id"], edge["successor_job_id"]
            graph[a].append(b)
            indegree[b] += 1
        pending = sorted(j for j, degree in indegree.items() if degree == 0)
        ordered = []
        while pending:
            j = pending.pop(0)
            ordered.append(j)
            for child in sorted(graph[j]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    pending.append(child)
                    pending.sort()
        if len(ordered) != len(self.jobs):
            raise ContractError(["snapshot.dependencies.cycle"])
        affected = set(self.operations) | set(self.overrides)
        stack = list(affected)
        while stack:
            for following in graph[stack.pop()]:
                if following not in affected:
                    affected.add(following)
                    stack.append(following)
        if any(self.jobs[j]["status"] in FROZEN for j in affected):
            raise _Review("FIXED_DEPENDENT_JOB")
        return affected, [j for j in ordered if j in affected]

    def _allocations(self):
        result = {}
        for name, key in (("plan_items", "job_id"), ("reservations", "rental_id"), ("dependencies", "job_id")):
            rows = self.input["id_allocations"][name]
            mapping = {r[key]: r["id"] for r in rows}
            if len(mapping) != len(rows) or len(set(mapping.values())) != len(rows):
                raise ContractError(["input.id_allocations." + name])
            old_ids = {r["id"] for r in self.snapshot[name]}
            if set(mapping.values()) & old_ids:
                raise ContractError(["input.id_allocations." + name + ".reused_id"])
            result[name] = mapping
        required_jobs = {j for j, row in self.jobs.items() if row["status"] != "CANCELLED"}
        required_rentals = {r["rental_id"] for r in self.candidate["reservations"]}
        required_rentals.update(op["rental_id"] for op in self.operations.values() if op["operation"] == "CREATE")
        required_edges = {j for j in self.order if self.jobs[j]["kind"] == "DELIVERY"}
        for name, required in (("plan_items", required_jobs), ("reservations", required_rentals), ("dependencies", required_edges)):
            if not required <= result[name].keys():
                raise ContractError(["input.id_allocations." + name + ".missing"])
        return result

    def _check_rental_bindings(self):
        for jid, op in self.operations.items():
            if op["operation"] == "CREATE":
                if op["rental_id"] in self.ix["rentals"]:
                    raise ContractError(["operations.rental_id.already_exists"])
            else:
                rid = op["rental_id"]
                rental = self.ix["rentals"].get(rid)
                j = self.jobs[jid]
                if rental is None or rental["status"] != "ACTIVE" or rental["asset_id"] not in j["asset_ids"] or self.ix["customers"][rental["customer_id"]]["location_id"] != j["from_id"]:
                    raise ContractError(["operations.rental_id"])
                prep = [d["successor_job_id"] for d in self.candidate["dependencies"] if d["predecessor_job_id"] == jid and self.jobs[d["successor_job_id"]]["kind"] == "PREP"]
                if len(prep) != 1:
                    raise ContractError(["snapshot.pickup.preparation_dependency"])

    def proof(self):
        for jid in self.order:
            j = self.jobs[jid]
            if j["kind"] == "PREP":
                continue
            item = self.ix["items"][j["item_id"]]
            if not any(e["active"] and {"task_kind": j["kind"], "item_category": item["category"]} in e["skills"] for e in self.snapshot["employees"]):
                return _Review("NO_QUALIFIED_EMPLOYEE", jid, {"scope": "all_registered_employees"}, "PROVEN_INFEASIBLE")
            if not any(a["item_id"] == j["item_id"] and a["physical_state"] != "RETIRED" for a in self.snapshot["assets"]):
                return _Review("NO_REGISTERED_ASSET", jid, {"scope": "same_item_non_retired_inventory"}, "PROVEN_INFEASIBLE")
            earliest = max(timestamp(j["window_start"]), timestamp(self.snapshot["as_of"]))
            end = earliest + timedelta(minutes=item["service_minutes_by_kind"][j["kind"]])
            if j["kind"] == "PICKUP":
                end += timedelta(minutes=self.travel[j["from_id"], j["to_id"]])
            if end > timestamp(j["due_at"]):
                return _Review("TIME_LOWER_BOUND", jid, {"earliest_completion": end.isoformat(), "due_at": j["due_at"], "scope": "ignores_employee_and_preparation_constraints"}, "PROVEN_INFEASIBLE")
        return None

    def budget(self, count=False):
        stats = self.result["search_stats"]
        if stats["candidates_examined"] >= self.input["max_candidates"] or (monotonic() - self.started) * 1000 >= self.input["max_search_ms"]:
            raise _StopSearch
        if count:
            stats["candidates_examined"] += 1

    def visit(self, depth, selected):
        if depth == len(self.order):
            if not self.order:
                self.budget(count=True)
            if (monotonic() - self.started) * 1000 >= self.input["max_search_ms"]:
                raise _StopSearch
            candidate = self.assemble(selected)
            validation = validate(self.snapshot, candidate)
            if validation["status"] == "DATA_MISSING":
                raise ContractError(validation["missing_fields"])
            if validation["status"] != "VALID":
                self.last_violations = validation["violations"]
                return
            objective, stable = self.objective(candidate)
            key = tuple(objective), stable
            if self.best_key is None or key < self.best_key:
                self.best, self.best_key = (candidate, objective), key
            return
        self.budget()
        jid = self.order[depth]
        for p in self.options(jid, selected):
            self.budget(count=True)
            if p["employee_id"] is not None and not self.employee_fits(p, selected):
                continue
            self.visit(depth + 1, {**selected, jid: p})

    def options(self, jid, selected):
        j, override = self.jobs[jid], self.overrides.get(jid, {})
        item = self.ix["items"][j["item_id"]]
        if j["kind"] == "PREP":
            predecessors = [d for d in self.candidate["dependencies"] if d["successor_job_id"] == jid]
            starts = [timestamp(j["window_start"]), timestamp(self.snapshot["as_of"])]
            for d in predecessors:
                p = selected.get(d["predecessor_job_id"], self.old_plans.get(d["predecessor_job_id"]))
                if p is None:
                    raise ContractError(["snapshot.predecessor.plan_item"])
                starts.append(timestamp(p["end_at"]) + timedelta(minutes=d["minimum_gap_minutes"]))
            start = timestamp(override["start_at"]) if "start_at" in override else max(starts)
            yield self.plan(jid, None, j["asset_ids"], [self.segment("PREP", self.warehouse, self.warehouse, start, start + timedelta(minutes=item["prep_minutes"]))])
            return
        for assets in self.asset_options(jid):
            for employee in self.employees(j):
                if "employee_id" in override and employee["id"] != override["employee_id"]:
                    continue
                for service_start in self.service_starts(j, override):
                    self.budget()
                    inbound = self.warehouse
                    service_location = j["to_id"] if j["kind"] == "DELIVERY" else j["from_id"]
                    start = service_start - timedelta(minutes=self.travel[inbound, service_location])
                    service_end = service_start + timedelta(minutes=item["service_minutes_by_kind"][j["kind"]])
                    end = service_end + timedelta(minutes=self.travel[service_location, self.warehouse])
                    segments = [self.segment("TRAVEL", inbound, service_location, start, service_start),
                                self.segment("SERVICE", service_location, service_location, service_start, service_end),
                                self.segment("TRAVEL", service_location, self.warehouse, service_end, end)]
                    if start < timestamp(self.snapshot["as_of"]):
                        continue
                    valid = True
                    for d in self.candidate["dependencies"]:
                        if d["successor_job_id"] != jid:
                            continue
                        prev = selected.get(d["predecessor_job_id"], self.old_plans.get(d["predecessor_job_id"]))
                        if prev is None:
                            raise ContractError(["snapshot.predecessor.plan_item"])
                        if self.asset_edge(d) and not set(prev["asset_ids"]) & set(assets):
                            continue
                        if timestamp(prev["end_at"]) + timedelta(minutes=d["minimum_gap_minutes"]) > start:
                            valid = False
                    if valid:
                        yield self.plan(jid, employee["id"], assets, segments)

    def asset_options(self, jid):
        j, override = self.jobs[jid], self.overrides.get(jid, {})
        if "asset_ids" in override:
            return [override["asset_ids"]]
        if j["kind"] != "DELIVERY" or (jid in self.operations and self.operations[jid]["job"]["asset_ids"]):
            return [j["asset_ids"]]
        eligible = [a["id"] for a in self.snapshot["assets"] if a["item_id"] == j["item_id"] and a["physical_state"] not in ("REPAIR", "RETIRED", "UNAVAILABLE", "IN_TRANSIT")]
        return [[a] for a in sorted(eligible, key=lambda a: (a not in j["asset_ids"], a))]

    def employees(self, j):
        location = j["to_id"] if j["kind"] == "DELIVERY" else j["from_id"]
        preferred = self.customers.get(location, {}).get("preferred_employee_id")
        category = self.ix["items"][j["item_id"]]["category"]
        return sorted((e for e in self.snapshot["employees"] if e["active"] and {"task_kind": j["kind"], "item_category": category} in e["skills"]), key=lambda e: (e["id"] != preferred, e["id"]))

    def service_starts(self, j, override):
        if "start_at" in override:
            yield timestamp(override["start_at"])
            return
        old = self.old_plans.get(j["id"])
        old_service = next((s for s in old["segments_json"] if s["kind"] == "SERVICE"), None) if old else None
        if old_service is not None and j["id"] not in self.operations and j["id"] not in self.input["approved_job_ids"]:
            yield timestamp(old_service["start_at"])
            return
        minutes = self.ix["items"][j["item_id"]]["service_minutes_by_kind"][j["kind"]]
        if timestamp(j["window_end"]) - timestamp(j["window_start"]) == timedelta(minutes=minutes):
            yield timestamp(j["window_start"])
            return
        low = max(timestamp(j["window_start"]), timestamp(self.snapshot["as_of"]))
        high = min(timestamp(j["window_end"]), timestamp(j["due_at"])) - timedelta(minutes=minutes)
        # Round automatic choices to five minutes; explicit overrides remain exact.
        low = low.replace(second=0, microsecond=0) + timedelta(minutes=(-low.minute) % 5)
        if low < timestamp(j["window_start"]):
            low += timedelta(minutes=5)
        cursor = low
        if old_service and low <= timestamp(old_service["start_at"]) <= high:
            yield timestamp(old_service["start_at"])
        while cursor <= high:
            self.budget()
            if old_service is None or cursor != timestamp(old_service["start_at"]):
                yield cursor
            cursor += timedelta(minutes=5)

    def employee_fits(self, p, selected):
        employee = p["employee_id"]
        plans = sorted(chain((x for x in self.kept if x["employee_id"] == employee),
                             (x for x in selected.values() if x["employee_id"] == employee), [p]), key=lambda x: timestamp(x["start_at"]))
        shifts = [s for s in self.snapshot["shifts"] if s["employee_id"] == employee]
        for row in plans:
            matching = [s for s in shifts if timestamp(s["start_at"]) <= timestamp(row["start_at"]) and timestamp(row["end_at"]) <= timestamp(s["end_at"])]
            if not matching or any(overlaps(interval(row["start_at"], row["end_at"]), interval(w["start"], w["end"])) for w in matching[0]["break_windows"]):
                return False
        for shift in shifts:
            cursor, location = timestamp(shift["start_at"]), shift["start_location_id"]
            for row in plans:
                if not (timestamp(shift["start_at"]) <= timestamp(row["start_at"]) < timestamp(shift["end_at"])):
                    continue
                if not row["segments_json"] or not route_fits(cursor, timestamp(row["start_at"]), location, row["segments_json"][0]["from_id"], shift, self.travel):
                    return False
                cursor, location = timestamp(row["end_at"]), row["segments_json"][-1]["to_id"]
            if not route_fits(cursor, timestamp(shift["end_at"]), location, shift["end_location_id"], shift, self.travel):
                return False
        return True

    def segment(self, kind, source, destination, start, end):
        return dict(kind=kind, from_id=source, to_id=destination, start_at=start.isoformat(), end_at=end.isoformat())

    def plan(self, jid, employee, assets, segments):
        return dict(id=self.allocations["plan_items"][jid], plan_id=self.input["plan_id"], job_id=jid,
                    employee_id=employee, asset_ids=deepcopy(assets), start_at=segments[0]["start_at"],
                    end_at=segments[-1]["end_at"], segments_json=segments, reason_codes=[])

    def asset_edge(self, d):
        return (d["reason"] in ASSET_EDGES and self.jobs[d["predecessor_job_id"]]["kind"] == "PREP"
                and self.jobs[d["successor_job_id"]]["kind"] == "DELIVERY")

    def assemble(self, selected):
        c = deepcopy(self.candidate)
        plans = {p["job_id"]: p for p in c["plan_items"]}
        plans.update(deepcopy(selected))
        jobs = {j["id"]: j for j in c["jobs"]}
        for jid, p in selected.items():
            jobs[jid]["asset_ids"] = deepcopy(p["asset_ids"])
        rentals = {r["id"]: r for r in c["rentals"]}
        bookings = {r["rental_id"]: r for r in c["reservations"]}
        if len(bookings) != len(c["reservations"]):
            raise _Review("MULTIPLE_RESERVATIONS_PER_RENTAL")
        for jid in self.order:
            j, p = jobs[jid], plans[jid]
            service = [s for s in p["segments_json"] if s["kind"] == "SERVICE"]
            if j["kind"] == "DELIVERY":
                if jid in self.operations:
                    rid = self.operations[jid]["rental_id"]
                    if j["to_id"] not in self.customers:
                        raise ContractError(["operations.job.to_id"])
                    rentals[rid] = dict(id=rid, asset_id=p["asset_ids"][0], customer_id=self.customers[j["to_id"]]["id"],
                                        actual_start=None, actual_end=None, expected_return_at=j["rental_end_at"], status="PLANNED")
                    bookings[rid] = dict(id=self.allocations["reservations"][rid], asset_id=p["asset_ids"][0], rental_id=rid,
                                         start_at=p["start_at"], end_at=None, release_job_id=None,
                                         plan_id=c["plan_id"], status="ACTIVE", review_required=False)
                else:
                    oldj, oldp = self.ix["jobs"][jid], self.old_plans[jid]
                    matched = [r for r in self.candidate["reservations"] if r["asset_id"] in oldj["asset_ids"] and timestamp(r["start_at"]) == timestamp(oldp["start_at"]) and self.ix["customers"][self.ix["rentals"][r["rental_id"]]["customer_id"]]["location_id"] == oldj["to_id"]]
                    if len(matched) != 1:
                        raise ContractError(["snapshot.delivery.reservation_binding"])
                    rid = matched[0]["rental_id"]
                    if rentals[rid]["status"] != "PLANNED":
                        raise _Review("FIXED_RENTAL_CUSTODY", jid)
                    rentals[rid]["asset_id"] = p["asset_ids"][0]
                    bookings[rid].update(asset_id=p["asset_ids"][0], start_at=p["start_at"])
            elif j["kind"] == "PICKUP":
                rid = self.operations[jid]["rental_id"]
                rentals[rid]["expected_return_at"] = service[0]["end_at"]
                prep = next(d["successor_job_id"] for d in self.candidate["dependencies"]
                            if d["predecessor_job_id"] == jid and jobs[d["successor_job_id"]]["kind"] == "PREP")
                if rid not in bookings:
                    raise ContractError(["snapshot.pickup.reservation_binding"])
                bookings[rid]["release_job_id"] = prep
        for r in bookings.values():
            release = r["release_job_id"]
            if release in selected and jobs[release]["kind"] == "PREP":
                r["end_at"] = plans[release]["end_at"]
            r.update(id=self.allocations["reservations"][r["rental_id"]], plan_id=c["plan_id"])
        edges = [d for d in c["dependencies"] if not (self.asset_edge(d) and not set(jobs[d["predecessor_job_id"]]["asset_ids"]) & set(jobs[d["successor_job_id"]]["asset_ids"]))]
        for jid in self.order:
            if jobs[jid]["kind"] != "DELIVERY":
                continue
            aid, departure = plans[jid]["asset_ids"][0], timestamp(plans[jid]["start_at"])
            predecessors = [j["id"] for j in c["jobs"] if j["kind"] == "PREP" and aid in j["asset_ids"] and j["id"] in plans and timestamp(plans[j["id"]]["end_at"]) <= departure]
            if predecessors:
                predecessor = max(predecessors, key=lambda j: timestamp(plans[j]["end_at"]))
                if not any(d["predecessor_job_id"] == predecessor and d["successor_job_id"] == jid for d in edges):
                    edges.append(dict(id=self.allocations["dependencies"][jid], predecessor_job_id=predecessor,
                                      successor_job_id=jid, minimum_gap_minutes=0, reason="READY_DELIVERY"))
        c.update(plan_items=sorted(plans.values(), key=lambda p: p["job_id"]), rentals=sorted(rentals.values(), key=lambda r: r["id"]),
                 reservations=sorted(bookings.values(), key=lambda r: r["id"]), dependencies=sorted(edges, key=lambda d: d["id"]))
        return c

    def objective(self, c):
        promises, as_wait, missed, travel = 0, 0, 0, 0
        stable = []
        for p in c["plan_items"]:
            jid, j = p["job_id"], self.jobs[p["job_id"]]
            service = [s for s in p["segments_json"] if s["kind"] == "SERVICE"]
            old = self.old_plans.get(jid)
            old_service = [s for s in old["segments_json"] if s["kind"] == "SERVICE"] if old else []
            if old_service and [(timestamp(s["start_at"]), timestamp(s["end_at"])) for s in service] != [(timestamp(s["start_at"]), timestamp(s["end_at"])) for s in old_service]:
                promises += 1
            if j["kind"] == "AS" and service:
                as_wait += max(0, int((timestamp(service[0]["start_at"]) - timestamp(j["window_start"])).total_seconds() / 60))
            if j["kind"] == "DELIVERY" and jid in self.operations:
                preferred = self.customers.get(j["to_id"], {}).get("preferred_employee_id")
                missed += int(preferred is not None and p["employee_id"] != preferred)
            travel += sum(int((timestamp(s["end_at"]) - timestamp(s["start_at"])).total_seconds() / 60) for s in p["segments_json"] if s["kind"] == "TRAVEL")
            stable.append((p["employee_id"] or "", tuple(p["asset_ids"]), timestamp(p["start_at"]).isoformat(), jid))
        return [0, promises, as_wait, missed, travel], tuple(sorted(stable))

    def explain(self, c):
        for p in c["plan_items"]:
            jid, j = p["job_id"], self.jobs[p["job_id"]]
            if jid not in self.affected:
                continue
            old = self.old_plans.get(jid)
            if j["kind"] == "PICKUP" and old and timestamp(p["start_at"]) != timestamp(old["start_at"]):
                p["reason_codes"].append("RETURN_DELAY")
            if j["kind"] == "PREP":
                p["reason_codes"].append("PREPARATION_DEPENDENCY")
            if old and p["asset_ids"] != old["asset_ids"]:
                p["reason_codes"].append("SAME_MODEL_SUBSTITUTE")
            location = j["to_id"] if j["kind"] == "DELIVERY" else j["from_id"]
            preferred = self.customers.get(location, {}).get("preferred_employee_id")
            if p["employee_id"] is not None and preferred and p["employee_id"] != preferred:
                alternate = deepcopy(c)
                changed = next(x for x in alternate["plan_items"] if x["job_id"] == jid)
                changed["employee_id"] = preferred
                v = validate(self.snapshot, alternate)
                if any(x["code"] in EMPLOYEE_CODES and (preferred in x["employee_ids"] or jid in x["job_ids"]) for x in v["violations"]):
                    p["reason_codes"].append("PREFERRED_EMPLOYEE_CONFLICT")
            p["reason_codes"] = sorted(set(p["reason_codes"]))

    def reservation_changes(self, c):
        old = {r["rental_id"]: r for r in self.candidate["reservations"]}
        return [dict(action="REPLACE" if r["rental_id"] in old else "CREATE", old_id=old[r["rental_id"]]["id"] if r["rental_id"] in old else None, reservation=deepcopy(r)) for r in c["reservations"]]

    def impact_edges(self, c):
        plans = {p["job_id"]: p for p in c["plan_items"]}
        result = []
        edges = {(d["predecessor_job_id"], d["successor_job_id"], d["reason"]): d
                 for d in chain(self.candidate["dependencies"], c["dependencies"])}
        for d in edges.values():
            a, b = d["predecessor_job_id"], d["successor_job_id"]
            if a not in self.affected and b not in self.affected:
                continue
            reason = "SAME_MODEL_SUBSTITUTE" if self.asset_edge(d) and self.old_plans.get(b, {}).get("asset_ids") != plans.get(b, {}).get("asset_ids") else d["reason"]
            result.append(dict(from_job_id=a, to_job_id=b, reason=reason,
                               old_time=self.old_plans.get(b, {}).get("start_at"), new_time=plans.get(b, {}).get("start_at")))
        return sorted(result, key=lambda e: (e["from_job_id"], e["to_job_id"], e["reason"]))
