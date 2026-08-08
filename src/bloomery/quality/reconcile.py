"""The ``reconcile:`` side grammar (RFC 0016 §5.3) — a **closed** two-shape
language, parsed here and nowhere else.

A reconcile check is "the check that catches a *correct formula over wrong
data*": it compares an aggregate of one entity against a value on another and
alerts when the two disagree beyond ``tolerance``. The RFC states the two
sides as spec strings::

    left:  "sum(order_item.line_total) by order_id"
    right: "order.total_amount"

and says nothing more about their language. Settled here, deliberately
narrow (an RFC ambiguity resolved):

``<agg>(<entity>.<column>) by <column>[, <column>…]``
    the **aggregate-by** shape. Keys are the ``by`` columns; the value is the
    aggregate over the named entity's column.

``<entity>.<column>``
    the **plain column** shape. Keys are the referenced entity's declared key
    — a value at one row per key is only meaningful *per key*, and the entity
    already declares which columns that is.

Nothing else parses. The closed aggregate vocabulary is
:data:`RECONCILE_AGGREGATES`. The alternative — accepting arbitrary SQL text
and handing it to the engine — was rejected for the reason every other
"specs never contain implementations" decision in RFC 0016 was: an authored
SQL fragment cannot be diffed by ``plan()``, cannot be validated against the
declared model, and renders differently per dialect. A shape outside the
grammar is refused at compile time with :data:`SUPPORTED_SHAPES` in the
message, so the author reads what *is* accepted rather than what is not.

This module is pure parsing — no IR, no SQL. Resolution against the model
(does the entity exist, does the column, do the two sides agree on keys) is
the guardrail stage's, and building the comparison AST is emission's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "RECONCILE_AGGREGATES",
    "RECONCILE_SUFFIX",
    "SUPPORTED_SHAPES",
    "ReconcileSide",
    "parse_side",
]

#: The relation suffix a check's own model takes, mirroring ``__reject``: one
#: ``<check>__reconcile`` per check, in the silver namespace it compares
#: within (RFC 0016 §5.3 — "reconcile emits its own model plus a non-blocking
#: audit").
RECONCILE_SUFFIX = "__reconcile"

#: The closed aggregate vocabulary of the aggregate-by shape. Every member has
#: a dialect-neutral SQLGlot node that renders on all three shipped dialects;
#: extending it is an RFC amendment, not config (the RFC 0016 D5 doctrine
#: applied to the reconcile grammar).
RECONCILE_AGGREGATES: tuple[str, ...] = ("avg", "count", "max", "min", "sum")

#: The prose every refusal carries — what the grammar *does* accept.
SUPPORTED_SHAPES = (
    "supported shapes are '<agg>(<entity>.<column>) by <column>[, <column>…]' "
    f"(agg one of {', '.join(RECONCILE_AGGREGATES)}) and '<entity>.<column>'"
)

_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_AGGREGATE = re.compile(
    rf"^\s*(?P<agg>{_NAME})\s*\(\s*(?P<entity>{_NAME})\s*\.\s*(?P<column>{_NAME})\s*\)"
    rf"\s+by\s+(?P<by>{_NAME}(?:\s*,\s*{_NAME})*)\s*$"
)
_COLUMN = re.compile(rf"^\s*(?P<entity>{_NAME})\s*\.\s*(?P<column>{_NAME})\s*$")


@dataclass(frozen=True, slots=True)
class ReconcileSide:
    """One parsed side of a reconcile check.

    ``agg`` is ``None`` for the plain-column shape, and ``by`` is empty there:
    its keys are the referenced entity's declared key, which only the model
    knows — the parser deliberately does not guess, so the two shapes stay
    distinguishable downstream.
    """

    entity: str
    column: str
    agg: str | None = None
    by: tuple[str, ...] = ()

    @property
    def aggregated(self) -> bool:
        return self.agg is not None


def parse_side(text: str) -> ReconcileSide | None:
    """Parse one ``left:``/``right:`` string, or ``None`` if it is outside the
    grammar.

    Total by design — it returns rather than raises, because its caller is the
    guardrail stage, which batches every refusal in a project into one
    aggregate error (RFC 0006 D2) instead of stopping at the first.
    """
    match = _AGGREGATE.match(text)
    if match is not None:
        agg = match.group("agg").lower()
        if agg not in RECONCILE_AGGREGATES:
            return None
        by = tuple(name.strip() for name in match.group("by").split(","))
        return ReconcileSide(
            entity=match.group("entity"), column=match.group("column"), agg=agg, by=by
        )
    match = _COLUMN.match(text)
    if match is None:
        return None
    return ReconcileSide(entity=match.group("entity"), column=match.group("column"))
