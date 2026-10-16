import json
import unittest
from copy import deepcopy

from rentwise.contracts.v2 import ContractError, check_contract
from rentwise.contracts.v2.normalize import normalize_operation
from rentwise.engine import availability, validate
from .sample import availability_input, candidate, delayed, job, plan, rental, reservation, segment, snapshot, t, transfer_case


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.s = snapshot()
        self.c = candidate(self.s)

    def codes(self, c=None, s=None):
        r = validate(self.s if s is None else s, self.c if c is None else c)
        self.assertEqual(r["status"], "INVALID", r)
        return {v["code"] for v in r["violations"]}

    def test_normal_full_candidate_and_input_immutability(self):
        before = deepcopy((self.s, self.c))
        self.assertEqual(validate(self.s, self.c)["status"], "VALID")
        self.assertEqual((self.s, self.c), before)

    def test_delay_uses_new_job_window_and_preserves_delivery(self):
        c = delayed(self.s)
        self.assertEqual(validate(self.s, c)["status"], "VALID")
        self.assertEqual(c["plan_items"][2]["segments_json"][1]["start_at"], t("12:00"))
        self.assertEqual(c["plan_items"][2]["asset_ids"], ["P02"])
        self.assertEqual(c["plan_items"][0]["employee_id"], "E2")
        self.assertEqual(c["plan_items"][1]["end_at"], t("15:00"))
        c["jobs"][0]["window_start"] = t("10:00")
        c["jobs"][0]["window_end"] = t("10:10")
        self.assertIn("VISIT_WINDOW", self.codes(c))

    def test_unapproved_customer_promise_change(self):
        c = delayed(self.s)
        c["approved_job_ids"] = []
        self.assertIn("CUSTOMER_APPROVAL_REQUIRED", self.codes(c))

    def test_preferred_employee_cannot_cross_break(self):
        c = delayed(self.s)
        c["plan_items"][0]["employee_id"] = "E1"
        self.assertIn("EMPLOYEE_BREAK", self.codes(c))

    def test_omitted_inbound_segment_cannot_hide_pre_break_repositioning(self):
        c = delayed(self.s)
        p = c["plan_items"][0]
        p["employee_id"] = "E1"
        p["segments_json"].pop(0)
        p["start_at"] = t("14:00")
        self.assertIn("EMPLOYEE_TRAVEL_GAP", self.codes(c))

    def test_stale_state_and_omitted_unchanged_job(self):
        self.c["base_state_revision"] = 6
        self.assertIn("STALE_SNAPSHOT", self.codes())
        self.c["jobs"].pop()
        self.c["plan_items"].pop()
        self.c["dependencies"].pop()
        self.assertIn("EXISTING_JOB_MISSING", self.codes())

    def test_quantity_and_same_model_constraints(self):
        self.c["jobs"][2]["quantity"] = 2
        self.assertIn("ASSET_QUANTITY", self.codes())

    def test_preparation_and_asset_overlap(self):
        c = delayed(self.s)
        c["jobs"][2]["asset_ids"] = ["P01"]
        c["plan_items"][2]["asset_ids"] = ["P01"]
        c["reservations"][1]["asset_id"] = "P01"
        c["rentals"][1]["asset_id"] = "P01"
        codes = self.codes(c)
        self.assertIn("ASSET_RESERVATION_OVERLAP", codes)
        self.assertIn("DELIVERY_REQUIRES_READY", codes)

    def test_preparation_duration_is_not_assumed_complete(self):
        p = self.c["plan_items"][1]
        p["end_at"] = p["segments_json"][0]["end_at"] = t("10:40")
        self.assertIn("PREPARATION_TOO_SHORT", self.codes())

    def test_missing_direction_is_data_missing(self):
        self.s["travel_times"] = [x for x in self.s["travel_times"] if (x["from_id"], x["to_id"]) != ("H", "W")]
        result = validate(self.s, self.c)
        self.assertEqual(result["status"], "DATA_MISSING")
        self.assertTrue(result["missing_fields"])

    def test_unknown_id_duplicate_id_and_legacy_bundle(self):
        for mutate in (lambda s: s["assets"].append(deepcopy(s["assets"][0])), lambda s: s.update(bundle_version="rental.bundle.v1"), lambda s: s["jobs"][0].update(from_id="GHOST")):
            with self.subTest(mutate=mutate):
                s = snapshot()
                mutate(s)
                self.assertEqual(validate(s, candidate(snapshot()))["status"], "DATA_MISSING")

    def test_unknown_fields_and_naive_time_rejected_without_value_echo(self):
        self.c["sensitive-unknown-field"] = "DO-NOT-ECHO"
        result = validate(self.s, self.c)
        self.assertEqual(result["status"], "DATA_MISSING")
        self.assertNotIn("DO-NOT-ECHO", json.dumps(result))
        self.s["as_of"] = "2026-10-16T09:00:00"
        self.assertEqual(validate(self.s, candidate(snapshot()))["status"], "DATA_MISSING")

    def test_employee_skill_and_shift_end_return(self):
        self.s["employees"][0]["skills"] = []
        self.assertIn("EMPLOYEE_SKILL", self.codes())
        self.s["employees"][0]["skills"] = snapshot()["employees"][0]["skills"]
        self.s["shifts"][0]["end_at"] = t("12:20")
        self.s["shifts"][0]["break_windows"] = []
        self.c["plan_items"][2]["segments_json"].pop()
        self.c["plan_items"][2]["end_at"] = t("12:15")
        self.assertIn("SHIFT_RETURN", self.codes())

    def test_employee_overlap_and_travel_gap(self):
        # Two different assets cannot make one employee serve two places at once.
        extra = deepcopy(self.c["plan_items"][2])
        extra.update(id="PI-AS", job_id="AS", asset_ids=["P02"])
        self.c["plan_items"].append(extra)
        j = job("AS", "AS", ["P02"], "S", "S")
        self.c["jobs"].append(j)
        self.assertIn("EMPLOYEE_OVERLAP", self.codes())
        # Remove explicit inbound travel so the whole route checker must account for it.
        c = candidate(self.s)
        c["plan_items"][0]["segments_json"].pop(0)
        c["plan_items"][0]["start_at"] = t("10:00")
        self.s["shifts"][0]["start_at"] = t("10:00")
        self.assertIn("EMPLOYEE_TRAVEL_GAP", self.codes(c))

    def test_due_and_travel_durations(self):
        self.c["jobs"][2]["due_at"] = t("12:00")
        self.assertIn("DUE_AT", self.codes())
        self.c["plan_items"][2]["segments_json"][0]["end_at"] = t("11:50")
        self.assertIn("TRAVEL_TOO_SHORT", self.codes())

    def test_frozen_job_reassignment(self):
        self.s["jobs"][0]["status"] = "IN_PROGRESS"
        self.c["jobs"][0]["status"] = "IN_PROGRESS"
        self.c["plan_items"][0]["employee_id"] = "E2"
        self.assertIn("FIXED_JOB_CHANGED", self.codes())

    def test_unrelated_in_progress_job_can_be_preserved(self):
        # Preserve ongoing AS at another customer, without promising its release.
        self.s["assets"][1].update(physical_state="AT_CUSTOMER", location_id="S")
        self.s["shifts"][1]["start_at"] = t("08:30")
        ongoing = job("AS", "AS", ["P02"], "S", "S")
        ongoing["status"] = "IN_PROGRESS"
        ongoing_plan = plan("AS", "E2", ["P02"], [segment("SERVICE", "S", "S", "09:00", "09:30")])
        self.s["jobs"].append(ongoing)
        self.s["plan_items"].append(ongoing_plan)
        self.c = candidate(self.s)
        self.assertEqual(validate(self.s, self.c)["status"], "VALID")

    def test_new_customer_job_requires_saved_approval(self):
        s, c = transfer_case()
        c["approved_job_ids"] = []
        self.assertIn("CUSTOMER_APPROVAL_REQUIRED", self.codes(c, s))

    def test_outside_horizon_booking_cannot_be_substituted_silently(self):
        future = reservation("RS-FUTURE", "P02", "R-FUTURE", "2026-10-24T09:00:00+09:00", None)
        self.s["rentals"].append(rental("R-FUTURE", "P02", "C-H"))
        self.s["reservations"].append(future)
        c = candidate(self.s)
        c["rentals"][-1]["asset_id"] = "P01"
        c["reservations"][-1]["asset_id"] = "P01"
        self.assertIn("OUTSIDE_RESERVATION_CHANGED", self.codes(c))

    def test_dependency_cycle(self):
        self.c["dependencies"].append(dict(id="D-CYCLE", predecessor_job_id="DEL", successor_job_id="PICK", minimum_gap_minutes=0, reason="INVALID"))
        self.assertIn("DEPENDENCY_CYCLE", self.codes())

    def test_open_reservation_and_period_external_occupancy(self):
        self.c["rentals"].append(rental("R-FUTURE", "P01", "C-H"))
        self.c["reservations"].append(reservation("RS-FUTURE", "P01", "R-FUTURE", "2026-10-24T09:00:00+09:00", None))
        self.assertIn("ASSET_RESERVATION_OVERLAP", self.codes())

    def test_removed_reservation_and_forged_actual_state(self):
        self.c["reservations"].pop()
        self.assertIn("EXISTING_RESERVATION_MISSING", self.codes())
        self.c["rentals"][0]["actual_end"] = t("10:10")
        self.c["rentals"][0]["status"] = "CLOSED"
        self.assertIn("RENTAL_ACTUAL_CHANGED", self.codes())

    def test_transfer_checks_both_service_stops_and_contiguous_rentals(self):
        s, c = transfer_case()
        self.assertEqual(validate(s, c)["status"], "VALID")
        for key, value, expected in (("destination_window_end", t("10:35"), "VISIT_WINDOW"), ("window_end", t("10:05"), "VISIT_WINDOW"), ("direct_transfer_confirmed", False, "DIRECT_TRANSFER_UNCONFIRMED")):
            changed = deepcopy(c)
            changed["jobs"][0][key] = value
            self.assertIn(expected, self.codes(changed, s))
        c["reservations"][1]["start_at"] = t("10:30")
        self.assertIn("DELIVERY_RESERVATION_COVERAGE", self.codes(c, s))

    def test_transfer_destination_customer_window_and_service_minutes(self):
        s, c = transfer_case()
        s["customers"][1]["visit_windows"] = [dict(start=t("11:00"), end=t("18:00"))]
        self.assertIn("CUSTOMER_VISIT_WINDOW", self.codes(c, s))
        s["items"][0]["transfer_service_minutes"]["delivery"] = 20
        self.assertIn("SERVICE_DURATION_OR_LOCATION", self.codes(c, s))


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.s = snapshot()

    def test_counts_reservations_and_conditional_windows(self):
        before = deepcopy(self.s)
        result = availability(availability_input(self.s))
        self.assertEqual(result["status"], "OK")
        self.assertEqual(sum(r["count"] for r in result["physical_counts"]), 2)
        window = next(w for w in result["windows"] if w["from_at"] == t("11:00"))
        self.assertEqual(window["ready_asset_ids"], ["P02"])
        self.assertEqual(window["conditional_assets"][0]["asset_id"], "P01")
        self.assertEqual(window["conditional_assets"][0]["dependency_job_ids"], ["PICK", "PREP"])
        after_departure = next(w for w in result["windows"] if w["from_at"] == t("11:40"))
        self.assertIn("P01", after_departure["unavailable_asset_ids"])
        self.assertEqual(self.s, before)

    def test_half_open_boundary_at_ready_and_departure(self):
        result = availability(availability_input(self.s, "11:00", "11:40"))
        self.assertEqual(len(result["windows"]), 1)
        self.assertEqual(len(result["windows"][0]["conditional_assets"]), 1)
        result = availability(availability_input(self.s, "11:40", "12:00"))
        self.assertIn("P01", result["windows"][0]["unavailable_asset_ids"])

    def test_open_ended_never_becomes_ready_from_expected_return(self):
        self.s["reservations"][0].update(end_at=None, release_job_id=None)
        result = availability(availability_input(self.s, "15:00", "18:00"))
        self.assertEqual(result["windows"][0]["conditional_assets"], [])
        self.assertIn("P01", result["windows"][0]["unavailable_asset_ids"])

    def test_retired_excluded_and_zero_inventory_distinguished(self):
        self.s["assets"][1]["physical_state"] = "RETIRED"
        r = availability(availability_input(self.s))
        self.assertEqual(sum(x["count"] for x in r["physical_counts"]), 1)
        self.assertFalse(any("P02" in w["unavailable_asset_ids"] or "P02" in w["ready_asset_ids"] for w in r["windows"]))
        for table in ("assets", "rentals", "reservations", "jobs", "plan_items", "dependencies"):
            self.s[table] = []
        r = availability(availability_input(self.s))
        self.assertEqual(r["status"], "OK")
        self.assertEqual(sum(x["count"] for x in r["physical_counts"]), 0)

    def test_no_silent_release_from_bad_preparation(self):
        self.s["reservations"] = self.s["reservations"][:1]
        self.s["plan_items"][1]["segments_json"][0]["kind"] = "SERVICE"
        r = availability(availability_input(self.s, "15:00", "18:00"))
        self.assertEqual(r["windows"][0]["conditional_assets"], [])

    def test_invalid_return_route_cannot_be_advertised_as_conditional(self):
        self.s["plan_items"][0]["employee_id"] = "E2"
        self.s["employees"][1]["skills"] = []
        r = availability(availability_input(self.s, "11:00", "11:40"))
        self.assertEqual(r["windows"][0]["conditional_assets"], [])
        self.assertIn("P01", r["windows"][0]["unavailable_asset_ids"])

    def test_review_required_reservation_stays_unavailable(self):
        self.s = snapshot()
        self.s["reservations"][0]["review_required"] = True
        r = availability(availability_input(self.s, "11:00", "11:40"))
        self.assertEqual(r["windows"][0]["conditional_assets"], [])

    def test_invalid_period_stale_and_missing_data_are_not_zero_stock(self):
        for change in (dict(from_at=t("18:00"), to_at=t("09:00")), dict(base_state_revision=6), dict(from_at=t("08:00"))):
            value = availability_input(self.s)
            value.update(change)
            self.assertEqual(availability(value)["status"], "DATA_MISSING")
        self.s["travel_times"].pop()
        self.assertEqual(availability(availability_input(self.s))["status"], "DATA_MISSING")


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.s = snapshot()

    def normalize(self, fields, **kwargs):
        values = dict(confirmed=True, rental_id="R-H", return_policy="NOT_APPLICABLE")
        values.update(kwargs)
        return normalize_operation(self.s, "RESCHEDULE", "PICK", fields, **values)

    def test_overlay_inherits_unmentioned_fields_without_mutation(self):
        before = deepcopy(self.s)
        result = self.normalize(dict(window_start=t("14:00"), window_end=t("14:10")))
        self.assertEqual(result["job"]["quantity"], 1)
        self.assertEqual(result["job"]["due_at"], t("17:00"))
        self.assertEqual(result["job"]["asset_ids"], ["P01"])
        self.assertEqual(self.s, before)
        check_contract("NormalizedOperation", result)

    def test_explicit_null_not_treated_as_unmentioned_and_unconfirmed_blocked(self):
        with self.assertRaises(ContractError):
            self.normalize(dict(window_end=None))
        with self.assertRaises(ContractError):
            self.normalize({}, confirmed=False)
        with self.assertRaises(ContractError):
            self.normalize(dict(quantity=True))

    def test_confirmed_non_delivery_cannot_have_unresolved_assets_or_unknown_location(self):
        for fields in (dict(asset_ids=[]), dict(asset_ids=["GHOST"]), dict(from_id="GHOST")):
            with self.subTest(fields=fields), self.assertRaises(ContractError):
                self.normalize(fields)

    def test_new_job_requires_full_fields_stable_unique_id_and_explicit_open_policy(self):
        new = deepcopy(self.s["jobs"][2])
        new.update(id="NEW", status="UNASSIGNED", asset_ids=[])
        result = normalize_operation(self.s, "CREATE", None, new, confirmed=True, rental_id="R-NEW", return_policy="OPEN_ENDED")
        self.assertEqual(result["job"]["rental_end_at"], None)
        for policy in ("FIXED", "NOT_APPLICABLE"):
            with self.assertRaises(ContractError):
                normalize_operation(self.s, "CREATE", None, new, confirmed=True, rental_id="R-NEW", return_policy=policy)
        with self.assertRaises(ContractError):
            normalize_operation(self.s, "CREATE", None, {}, confirmed=True, rental_id=None, return_policy="NOT_APPLICABLE")
        with self.assertRaises(ContractError):
            self.normalize(dict(id="FORGED"))


if __name__ == "__main__":
    unittest.main()
