import json
import unittest
from copy import deepcopy
from datetime import timezone
from unittest.mock import patch

from rentwise.contracts.v2 import check_contract
from rentwise.contracts.v2.normalize import normalize_operation
from rentwise.contracts.v2.serialization import solver_input_hash
from rentwise.contracts.v2.schema import timestamp
from rentwise.engine import solve, validate
from .sample import job, plan, rental, reservation, segment, snapshot, t
from .solver_sample import delay_operation, normal_operation, solver_input


class SolverTests(unittest.TestCase):
    def setUp(self):
        self.s = snapshot()

    def run_solver(self, value, expected):
        before = deepcopy(value)
        result = solve(value)
        self.assertEqual(value, before)
        check_contract("SolverResult", result)
        self.assertEqual(result["status"], expected, result)
        self.assertEqual(result["input_hash"], value["input_hash"])
        self.assertLessEqual(result["search_stats"]["candidates_examined"], value["max_candidates"])
        if expected == "FEASIBLE":
            self.assertEqual(validate(value["snapshot"], result["candidate_plan"])["status"], "VALID")
            self.assertEqual(result["candidate_items"], result["candidate_plan"]["plan_items"])
            self.assertEqual(result["violations"], [])
        else:
            self.assertIsNone(result["candidate_plan"])
            self.assertEqual(result["candidate_items"], [])
            self.assertEqual(result["reservation_changes"], [])
        return result

    def test_normal_delivery_is_created_and_existing_promises_preserved(self):
        value = solver_input(self.s, [normal_operation(self.s)])
        r = self.run_solver(value, "FEASIBLE")
        plans = {p["job_id"]: p for p in r["candidate_items"]}
        self.assertEqual(plans["NEW-DEL"]["asset_ids"], ["P02"])
        self.assertEqual(plans["NEW-DEL"]["employee_id"], "E1")
        self.assertEqual(plans["NEW-DEL"]["segments_json"][1]["start_at"], t("11:00"))
        self.assertEqual(plans["DEL"]["segments_json"], self.s["plan_items"][2]["segments_json"])
        self.assertEqual(len(r["candidate_plan"]["rentals"]), 3)
        self.assertEqual(sum(d["action"] == "CREATE" for d in r["reservation_changes"]), 1)
        self.assertEqual(r["affected_job_ids"], ["NEW-DEL"])

    def test_delay_automatically_reassigns_staff_asset_preparation_and_reservations(self):
        r = self.run_solver(solver_input(self.s, [delay_operation(self.s)]), "FEASIBLE")
        plans = {p["job_id"]: p for p in r["candidate_items"]}
        self.assertEqual(plans["PICK"]["employee_id"], "E2")
        self.assertEqual(plans["PICK"]["segments_json"][1]["start_at"], t("14:00"))
        self.assertEqual(plans["PREP"]["end_at"], t("15:00"))
        self.assertEqual(plans["DEL"]["asset_ids"], ["P02"])
        self.assertEqual(plans["DEL"]["segments_json"][1]["start_at"], t("12:00"))
        self.assertIn("PREFERRED_EMPLOYEE_CONFLICT", plans["PICK"]["reason_codes"])
        self.assertIn("SAME_MODEL_SUBSTITUTE", plans["DEL"]["reason_codes"])
        bookings = {r["rental_id"]: r for r in r["candidate_plan"]["reservations"]}
        self.assertEqual(bookings["R-H"]["end_at"], t("15:00"))
        self.assertEqual(bookings["R-S"]["asset_id"], "P02")
        self.assertEqual(set(r["affected_job_ids"]), {"PICK", "PREP", "DEL"})
        self.assertTrue(any(e["reason"] == "SAME_MODEL_SUBSTITUTE" for e in r["impact_edges"]))

    def test_pickup_updates_an_open_booking_only_through_explicit_preparation(self):
        self.s["reservations"][0].update(end_at=None, release_job_id=None)
        r = self.run_solver(solver_input(self.s, [delay_operation(self.s)]), "FEASIBLE")
        booking = next(b for b in r["candidate_plan"]["reservations"] if b["rental_id"] == "R-H")
        self.assertEqual((booking["end_at"], booking["release_job_id"]), (t("15:00"), "PREP"))

    def test_new_delivery_can_depend_on_a_planned_return_and_exposes_new_edge(self):
        for name in ("jobs", "plan_items"):
            self.s[name] = [x for x in self.s[name] if (x["id"] if name == "jobs" else x["job_id"]) != "DEL"]
        self.s["dependencies"] = self.s["dependencies"][:1]
        self.s["rentals"] = self.s["rentals"][:1]
        self.s["reservations"] = self.s["reservations"][:1]
        op = normal_operation(self.s, start="11:30", end="11:45", due="11:45")
        op["job"]["to_id"] = "S"
        r = self.run_solver(solver_input(self.s, [op]), "FEASIBLE")
        p = next(p for p in r["candidate_items"] if p["job_id"] == "NEW-DEL")
        self.assertEqual(p["asset_ids"], ["P01"])
        self.assertTrue(any(e["from_job_id"] == "PREP" and e["to_job_id"] == "NEW-DEL" for e in r["impact_edges"]))

    def test_utc_storage_and_local_request_preserve_same_customer_promise(self):
        def utc(value):
            if isinstance(value, dict):
                return {k: utc(v) for k, v in value.items()}
            if isinstance(value, list):
                return [utc(v) for v in value]
            if isinstance(value, str) and value.startswith("2026-"):
                return timestamp(value).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            return value
        s = utc(self.s)
        r = self.run_solver(solver_input(s, [delay_operation(s)]), "FEASIBLE")
        p = next(p for p in r["candidate_items"] if p["job_id"] == "DEL")
        self.assertEqual(timestamp(p["segments_json"][1]["start_at"]), timestamp(t("12:00")))

    def test_rental_actuals_and_physical_state_are_not_modified(self):
        value = solver_input(self.s, [delay_operation(self.s)])
        r = self.run_solver(value, "FEASIBLE")
        old = {r["id"]: r for r in self.s["rentals"]}
        for row in r["candidate_plan"]["rentals"]:
            self.assertEqual((row["actual_start"], row["actual_end"], row["status"]), (old[row["id"]]["actual_start"], old[row["id"]]["actual_end"], old[row["id"]]["status"]))
        self.assertNotIn("assets", r["candidate_plan"])

    def test_no_operation_can_revalidate_a_full_plan_with_one_candidate(self):
        value = solver_input(self.s, [], max_candidates=1)
        self.run_solver(value, "FEASIBLE")

    def test_last_allowed_candidate_can_be_validated(self):
        op = normal_operation(self.s)
        op["job"]["asset_ids"] = ["P02"]
        self.run_solver(solver_input(self.s, [op], max_candidates=1), "FEASIBLE")

    def test_search_limit_is_not_impossibility(self):
        for changes in (dict(max_candidates=1), dict(max_search_ms=0), dict(max_candidates=0)):
            with self.subTest(changes=changes):
                r = self.run_solver(solver_input(self.s, [delay_operation(self.s)], **changes), "NO_SOLUTION_FOUND")
                self.assertTrue(r["search_stats"]["limit_reached"])
                self.assertEqual(r["unresolved"][0]["code"], "SEARCH_LIMIT")

    def test_monotonic_time_limit_during_search(self):
        ticks = iter(i / 1000 for i in range(10000))
        with patch("rentwise.engine.solver.monotonic", side_effect=lambda: next(ticks)):
            r = self.run_solver(solver_input(self.s, [delay_operation(self.s)], max_search_ms=3), "NO_SOLUTION_FOUND")
        self.assertTrue(r["search_stats"]["limit_reached"])

    def test_no_qualified_employee_has_scoped_proof(self):
        for e in self.s["employees"]:
            e["skills"] = []
        r = self.run_solver(solver_input(self.s, [delay_operation(self.s)]), "PROVEN_INFEASIBLE")
        self.assertEqual(r["unresolved"][0]["code"], "NO_QUALIFIED_EMPLOYEE")
        self.assertEqual(r["unresolved"][0]["details"]["scope"], "all_registered_employees")

    def test_impossible_pickup_due_uses_independent_lower_bound(self):
        r = self.run_solver(solver_input(self.s, [delay_operation(self.s, due="14:15")]), "PROVEN_INFEASIBLE")
        self.assertEqual(r["unresolved"][0]["code"], "TIME_LOWER_BOUND")
        self.assertEqual(r["unresolved"][0]["details"]["earliest_completion"], t("14:30"))

    def test_no_substitute_does_not_move_existing_delivery_promise(self):
        self.s["assets"][1]["physical_state"] = "REPAIR"
        self.run_solver(solver_input(self.s, [delay_operation(self.s)]), "NO_SOLUTION_FOUND")

    def test_open_ended_and_period_external_reservations_are_preserved(self):
        self.s["rentals"].append(rental("R-FUTURE", "P02", "C-H"))
        self.s["reservations"].append(reservation("RS-FUTURE", "P02", "R-FUTURE", "2026-10-24T09:00:00+09:00", None))
        self.run_solver(solver_input(self.s, [delay_operation(self.s)]), "NO_SOLUTION_FOUND")

    def test_manual_staff_and_asset_cannot_bypass_constraints(self):
        for override in (dict(job_id="PICK", employee_id="E1"), dict(job_id="DEL", asset_ids=["P01"])):
            with self.subTest(override=override):
                self.run_solver(solver_input(self.s, [delay_operation(self.s)], overrides=[override]), "NO_SOLUTION_FOUND")

    def test_explicit_fixed_time_and_override_are_not_rounded(self):
        r = self.run_solver(solver_input(self.s, [delay_operation(self.s, start="14:02", end="14:12")]), "FEASIBLE")
        pickup = next(p for p in r["candidate_items"] if p["job_id"] == "PICK")
        self.assertEqual(pickup["segments_json"][1]["start_at"], t("14:02"))
        op = normal_operation(self.s, start="11:00", end="11:30", due="11:30")
        r = self.run_solver(solver_input(self.s, [op], overrides=[dict(job_id="NEW-DEL", start_at=t("11:02"))]), "FEASIBLE")
        p = next(p for p in r["candidate_items"] if p["job_id"] == "NEW-DEL")
        self.assertEqual(p["segments_json"][1]["start_at"], t("11:02"))

    def test_missing_data_and_wrong_hash_fail_before_search(self):
        value = solver_input(self.s, [delay_operation(self.s)])
        value["input_hash"] = "0" * 64
        self.run_solver(value, "DATA_MISSING")
        self.s["travel_times"].pop()
        self.run_solver(solver_input(self.s, [delay_operation(self.s)]), "DATA_MISSING")

    def test_stale_and_unapproved_requests_are_reviewable(self):
        for changes in (dict(base_state_revision=6), dict(approved_job_ids=[]), dict(base_plan_id="STALE")):
            with self.subTest(changes=changes):
                self.run_solver(solver_input(self.s, [delay_operation(self.s)], **changes), "NEEDS_REVIEW")

    def test_unconfirmed_or_noncanonical_operations_are_not_used(self):
        op = delay_operation(self.s)
        op["confirmed"] = False
        self.run_solver(solver_input(self.s, [op]), "NEEDS_REVIEW")
        op = delay_operation(self.s)
        op["job"]["operation"] = "CREATE"
        self.run_solver(solver_input(self.s, [op]), "DATA_MISSING")

    def test_later_day_delivery_uses_that_days_shift_and_customer_window(self):
        op = normal_operation(self.s)
        for key in ("window_start", "window_end", "due_at"):
            op["job"][key] = op["job"][key].replace("2026-10-16", "2026-10-17")
        for row in deepcopy(self.s["shifts"]):
            row["id"] += "-NEXT"
            for key in ("start_at", "end_at"):
                row[key] = row[key].replace("2026-10-16", "2026-10-17")
            for w in row["break_windows"]:
                for key in ("start", "end"):
                    w[key] = w[key].replace("2026-10-16", "2026-10-17")
            self.s["shifts"].append(row)
        for customer in self.s["customers"]:
            customer["visit_windows"].append({k: v.replace("2026-10-16", "2026-10-17") for k, v in customer["visit_windows"][0].items()})
        r = self.run_solver(solver_input(self.s, [op]), "FEASIBLE")
        p = next(p for p in r["candidate_items"] if p["job_id"] == "NEW-DEL")
        self.assertTrue(p["start_at"].startswith("2026-10-17"))

    def test_invalid_manual_override_is_not_silently_ignored(self):
        self.run_solver(solver_input(self.s, [delay_operation(self.s)], overrides=[dict(job_id="PICK", employee_id="GHOST")]), "NEEDS_REVIEW")
        self.run_solver(solver_input(self.s, [delay_operation(self.s)], overrides=[dict(job_id="PREP", asset_ids=["P02"])]), "NEEDS_REVIEW")
        self.run_solver(solver_input(self.s, [delay_operation(self.s)], overrides=[dict(job_id="DEL", start_at=t("15:30"))]), "NEEDS_REVIEW")

    def test_duplicate_or_missing_existing_plan_rows_are_data_errors(self):
        s = deepcopy(self.s)
        extra = deepcopy(s["plan_items"][0])
        extra["id"] = "EXTRA-ROW"
        s["plan_items"].append(extra)
        self.run_solver(solver_input(s, [delay_operation(s)]), "DATA_MISSING")
        self.s["plan_items"].pop()
        self.run_solver(solver_input(self.s, [delay_operation(self.s)]), "DATA_MISSING")

    def test_return_deadline_before_delivery_completion_is_not_feasible(self):
        op = normal_operation(self.s)
        op.update(return_policy="FIXED")
        op["job"]["rental_end_at"] = t("11:10")
        self.run_solver(solver_input(self.s, [op]), "NO_SOLUTION_FOUND")

    def test_ids_are_supplied_by_b_and_missing_or_reused_allocations_fail(self):
        value = solver_input(self.s, [delay_operation(self.s)])
        value["id_allocations"]["plan_items"] = []
        value["input_hash"] = solver_input_hash(value)
        self.run_solver(value, "DATA_MISSING")
        value = solver_input(self.s, [delay_operation(self.s)])
        value["id_allocations"]["plan_items"][0]["id"] = self.s["plan_items"][0]["id"]
        value["input_hash"] = solver_input_hash(value)
        self.run_solver(value, "DATA_MISSING")

    def test_frozen_pickup_is_not_reassigned(self):
        self.s["jobs"][0]["status"] = "IN_PROGRESS"
        self.run_solver(solver_input(self.s, [delay_operation(self.s)]), "NEEDS_REVIEW")

    def test_unsupported_new_as_is_explicit(self):
        request = job("NEW-AS", "AS", ["P01"], "H", "H")
        op = normalize_operation(self.s, "CREATE", None, request, confirmed=True, rental_id=None, return_policy="NOT_APPLICABLE")
        r = self.run_solver(solver_input(self.s, [op]), "NEEDS_REVIEW")
        self.assertEqual(r["unresolved"][0]["code"], "UNSUPPORTED_OPERATION")

    def test_out_of_horizon_and_multi_asset_are_not_success(self):
        op = normal_operation(self.s)
        op["job"].update(window_start="2026-10-24T11:00:00+09:00", window_end="2026-10-24T11:15:00+09:00")
        self.run_solver(solver_input(self.s, [op]), "NEEDS_REVIEW")
        op = normal_operation(self.s)
        op["job"]["quantity"] = 2
        self.run_solver(solver_input(self.s, [op]), "NEEDS_REVIEW")

    def test_dependency_cycle_is_data_error(self):
        self.s["dependencies"].append(dict(id="CYCLE", predecessor_job_id="DEL", successor_job_id="PICK", minimum_gap_minutes=0, reason="INVALID"))
        self.run_solver(solver_input(self.s, [delay_operation(self.s)]), "DATA_MISSING")

    def test_result_and_hash_are_stable_under_snapshot_entity_order(self):
        value = solver_input(self.s, [delay_operation(self.s)])
        first = self.run_solver(value, "FEASIBLE")
        shuffled = deepcopy(value)
        for v in shuffled["snapshot"].values():
            if isinstance(v, list):
                v.reverse()
        self.assertEqual(solver_input_hash(shuffled), value["input_hash"])
        second = self.run_solver(shuffled, "FEASIBLE")
        for result in (first, second):
            result.pop("search_stats")
        self.assertEqual(first, second)

    def test_generic_ids_and_new_request_id_do_not_select_hardcoded_solution(self):
        names = {"P01": "A-55", "P02": "A-99", "PICK": "RETURN-4", "PREP": "READY-4", "DEL": "SHIP-9", "E1": "STAFF-X", "E2": "STAFF-Y", "PR-A": "ITEM-Z", "H": "SITE-K", "S": "SITE-L", "W": "DEPOT-M"}
        def rename(value, key=None):
            if isinstance(value, dict):
                return {k: rename(v, k) for k, v in value.items()}
            if isinstance(value, list):
                return [rename(v, key) for v in value]
            return names.get(value, value) if isinstance(value, str) and key not in ("kind", "task_kind") else value
        s = rename(self.s)
        r = self.run_solver(solver_input(s, [delay_operation(s)], request_id="UNRELATED-REQUEST"), "FEASIBLE")
        p = next(p for p in r["candidate_items"] if p["job_id"] == "SHIP-9")
        self.assertEqual(p["asset_ids"], ["A-99"])

    def test_reservation_delta_rebuilds_the_effective_full_view(self):
        r = self.run_solver(solver_input(self.s, [normal_operation(self.s)]), "FEASIBLE")
        effective = {row["id"]: deepcopy(row) for row in self.s["reservations"] if row["status"] == "ACTIVE"}
        for change in r["reservation_changes"]:
            if change["old_id"] is not None:
                effective.pop(change["old_id"])
            if change["reservation"] is not None:
                effective[change["reservation"]["id"]] = change["reservation"]
        self.assertEqual(sorted(effective.values(), key=lambda r: r["id"]), r["candidate_plan"]["reservations"])
        json.dumps(r, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
