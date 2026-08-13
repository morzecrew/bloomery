"""One reconcile project whose key is NULL on both sides (RFC 0016 §5.3).

Two tiers need the same specs and the same seed — DuckDB for the semantics
(``tests/execution/test_reconcile_null_keys.py``) and PostgreSQL for the
engine's willingness to run the query at all
(``tests/engines/test_postgres_reconcile.py``) — and a claim about NULL keys is
only worth stating if both tiers are asking it of *identical* data.

It lives here rather than under ``tests/fixtures/`` for the reason
:mod:`support.steps` gives: ``fixtures/`` is a corpus several suites sweep whole
(golden artifacts, the dbt parse tier, the compile properties), so adding a
project there is a claim on all of them. This one is a specimen for two named
tests, not a project the corpus should carry.
"""

from __future__ import annotations

from decimal import Decimal

__all__ = ["LINES", "ORDERS", "SOURCES"]

#: Two entities and one reconcile between them: the sum of a line-level amount
#: by ``order_id`` against the order-level total. ``line.order_id`` is not
#: ``required``, which is the whole point — nothing in the spec layer forces a
#: key or a ``by`` column to be non-nullable, so a NULL group is reachable from
#: an ordinary, valid project.
SOURCES = {
    "entity_model": """\
spec_version: 1
entities:
  line:
    grain: one row per order line
    key: [line_id]
    fields:
      line_id: {type: string, required: true}
      order_id: {type: string}
      amount: {type: "decimal(12,2)"}
  order_total:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      amount: {type: "decimal(12,2)"}
reconcile:
  - {name: lines_match_total, left: "sum(line.amount) by order_id",
     right: "order_total.amount", tolerance: "0.01", on_fail: flag}
""",
    "mapping_line": """\
mapping_version: 1
source: src__lines
target: line
key: {line_id: {from: "$.id", transform: [to_string]}}
fields:
  order_id: {from: "$.order_id", transform: [to_string]}
  amount: {from: "$.amount", transform: [{to_decimal: [12, 2]}]}
""",
    "mapping_order": """\
mapping_version: 1
source: src__orders
target: order_total
key: {order_id: {from: "$.id", transform: [to_string]}}
fields:
  amount: {from: "$.amount", transform: [{to_decimal: [12, 2]}]}
""",
}

#: Four groups, one per case the comparison has to get right.
#:
#: - ``o1`` — matched and agreeing.
#: - ``o2`` — left only (lines with no order row).
#: - ``o3`` — right only (an order with no lines).
#: - ``NULL`` — matched *and agreeing*, through a key that is NULL on both
#:   sides. The case that was reported as two failures.
LINES = [
    ("l1", "o1", Decimal("10.00")),
    ("l2", "o1", Decimal("5.00")),
    ("l3", "o2", Decimal("3.00")),
    ("l4", None, Decimal("7.00")),
]
ORDERS = [
    ("o1", Decimal("15.00")),
    ("o3", Decimal("9.00")),
    (None, Decimal("7.00")),
]
