# Bundle changes

## rental.bundle.v2 additive solver contracts — 2026-10-16, TEL-046

- Adds the previously undefined SolverInput/Result DTOs and schemas; existing
  Snapshot/CandidatePlan/NormalizedOperation requirements remain unchanged.
- Defines B-issued plan/PlanItem/Reservation/dependency IDs and the shared
  canonical solver input hash. Candidate generation does not issue DB IDs.
- SolverResult has full candidate, matching row/delta views, impact, bounded
  search statistics, and explicit unsuccessful/proof statuses.
- Validator compares customer service instants across UTC/offset encodings and
  rejects a rental end at/before customer delivery completion.
- This is local A implementation; B/C review and service integration pending.

## rental.bundle.v2 — 2026-10-16, TEL-045

- Defines CandidatePlan as a full effective view, not a list of changed rows.
- Defines reviewed NormalizedOperation and B-owned ID issuance/overlay rules.
- Adds destination visit window and explicit per-stop TRANSFER service times.
- Adds snapshot metadata and explicit as_of for deterministic replay.
- Rejects v1 bundle mixing. Intent v1 and result envelope v1 remain unchanged.
- Initial shared files created in the user-authorized A startup session; B owns
  subsequent contract maintenance. B/C review and service integration are pending.
