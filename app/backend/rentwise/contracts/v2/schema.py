"""Validate the small JSON Schema vocabulary used by this bundle.

No external packages. This is deliberately not a general JSON Schema engine;
adding schema keywords requires extending this checker and its contract tests.
Validation errors contain paths only, never caller values or request text.
"""

import json
import math
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path


class ContractError(ValueError):
    def __init__(self, paths: list[str]):
        self.paths = sorted(set(paths))
        super().__init__("Invalid rental contract: " + ", ".join(self.paths))


def timestamp(value: str) -> datetime:
    value = datetime.fromisoformat(value)
    if value.utcoffset() is None:
        raise ValueError("Timezone offset required")
    return value


@lru_cache(maxsize=1)
def _schema() -> dict:
    return json.loads((Path(__file__).parent / "schemas" / "bundle.json").read_text())


def check_contract(name: str, value: object, path: str = "input") -> None:
    definitions = _schema()["$defs"]

    def walk(rule: dict, data: object, where: str) -> list[str]:
        if not rule:
            return []
        if "$ref" in rule:
            return walk(definitions[rule["$ref"].split("/")[-1]], data, where)
        if "anyOf" in rule:
            return [] if any(not walk(r, data, where) for r in rule["anyOf"]) else [where]
        kind = rule.get("type")
        matches = {
            "object": isinstance(data, dict), "array": isinstance(data, list),
            "string": isinstance(data, str), "integer": type(data) is int,
            "number": type(data) is int or (type(data) is float and math.isfinite(data)),
            "boolean": type(data) is bool, "null": data is None,
        }
        if not matches[kind]:
            return [where]
        if "enum" in rule and data not in rule["enum"]:
            return [where]
        if "const" in rule and data != rule["const"]:
            return [where]
        if kind in ("integer", "number"):
            if data < rule.get("minimum", -math.inf) or data > rule.get("maximum", math.inf):
                return [where]
        if kind == "string":
            if len(data) < rule.get("minLength", 0):
                return [where]
            if "pattern" in rule and re.search(rule["pattern"], data) is None:
                return [where]
            if rule.get("format") == "date-time":
                try:
                    timestamp(data)
                except (ValueError, TypeError, OverflowError):
                    return [where]
        if kind == "array":
            if len(data) < rule.get("minItems", 0) or len(data) > rule.get("maxItems", math.inf):
                return [where]
            return [p for i, x in enumerate(data) for p in walk(rule["items"], x, f"{where}.{i}")]
        if kind == "object":
            keys = rule.get("properties", {})
            errors = [f"{where}.{k}" for k in rule.get("required", []) if k not in data]
            if rule.get("additionalProperties") is False:
                errors += [where + ".<unknown-field>" for k in data if k not in keys]
            for k in keys.keys() & data.keys():
                errors.extend(walk(keys[k], data[k], f"{where}.{k}"))
            return errors
        return []

    errors = walk(definitions[name], value, path)
    if errors:
        raise ContractError(errors)
