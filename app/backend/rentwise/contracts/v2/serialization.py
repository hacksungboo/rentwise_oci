"""The B/API and A solver share one canonical input hash definition."""

import hashlib
import json
from copy import deepcopy


def solver_input_hash(input: dict) -> str:
    payload = deepcopy(input)
    payload.pop("input_hash", None)
    snapshot = payload.get("snapshot", {})
    for name, rows in snapshot.items():
        if isinstance(rows, list):
            if name == "travel_times":
                rows.sort(key=lambda row: (row["from_id"], row["to_id"]))
            else:
                rows.sort(key=lambda row: row["id"])
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
