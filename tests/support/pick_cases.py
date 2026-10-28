"""The lists S-0095 measured, plus three found in review and a numeric match
field, with what `{pick: [name, a, value]}` must read from each on every port
that ships it (S-0095/D-1, D-4). One table, so DuckDB's execution test and the
engine differential cannot hold different answers."""

from __future__ import annotations

__all__ = ["CASES", "NUMERIC_FIELD"]

#: `(name, a, value)` over each list.
CASES: dict[str, tuple[str | None, str | None]] = {
    "scalar": ('[{"name": "a", "value": "x"}]', "x"),
    "numeric value": ('[{"name": "a", "value": 5}]', "5"),
    "no match": ('[{"name": "b", "value": "x"}]', None),
    "empty list": ("[]", None),
    "missing key": ('[{"value": "x"}]', None),
    "not a list": ('{"name": "a", "value": "x"}', None),
    "duplicates, the first wins": ('[{"name": "a", "value": "x"}, {"name": "a", "value": "y"}]', "x"),
    "non-object element skipped": ('[5, {"name": "a", "value": "x"}]', "x"),
    "null value": ('[{"name": "a", "value": null}]', None),
    "non-scalar value": ('[{"name": "a", "value": {"deep": 1}}]', None),
    "text that is not json": ("not json", None),
    "composite match field": ('[{"name": {"a": 1}, "value": "x"}]', None),
    "null list": (None, None),
}

#: `(name, 5, value)`: a numeric field matches the text of its number.
NUMERIC_FIELD = ('[{"name": 5, "value": "x"}]', "x")
