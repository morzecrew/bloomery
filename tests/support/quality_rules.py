"""One :class:`QualityRuleIR` per catalogue kind, built the way the lowering
builds them — the fixture the RFC 0016 §6 matrix iterates.

Kept in ``tests/support/`` rather than inline because three test modules need
the same rules (the lowering matrix, the three-valued semantics, and the
emitter shape tests), and a second hand-rolled copy is exactly how a rule
ships lowered-but-untested.
"""

from __future__ import annotations

from sqlglot.expressions.core import Expression

from bloomery.ir import OnFail, QualityRuleIR, SqlExpr
from bloomery.quality import branch_violation, branched, violation

__all__ = [
    "BRANCH_ENUM_VALUES",
    "BRANCH_SOURCES",
    "ON_MISSING_RULES",
    "predicate_of",
    "rule_of_kind",
]

#: The branch facts the two :data:`~bloomery.quality.BRANCH_KINDS` rules read
#: (RFC 0024 D32). They live beside the rules rather than inside them because
#: that is where the lowering puts them: on the per-source node, not on the
#: rule, so that one rule evaluated over a union reads each branch's own.
BRANCH_SOURCES = ("raw_amount",)
BRANCH_ENUM_VALUES = ("a", "b")


def rule_of_kind(kind: str, on_fail: OnFail = OnFail.FLAG) -> QualityRuleIR:
    """A representative rule of ``kind`` carrying ``on_fail``.

    ``referential`` ignores ``on_fail`` — it carries ``on_missing`` instead
    (its ``unknown_member`` value is not an :class:`OnFail`); use
    :data:`ON_MISSING_RULES` for that axis.
    """
    params: dict[str, str] = {}
    column: str | None = "amount"
    if kind == "range":
        params = {"min": "0", "max": "1000000"}
    elif kind == "length":
        params = {"min": "1", "max": "8"}
    elif kind == "pattern":
        params = {"regex": "^[A-Z]{3}$"}
    elif kind == "in_set":
        params = {"value_0000": "a", "value_0001": "b"}
    elif kind == "normalize":
        params = {"form": "nfc"}
    elif kind == "charset":
        # The forbid side: U+200B ZERO WIDTH SPACE. The allow side lowers
        # through the same TRANSLATE and has its own assertions.
        params = {"forbid_0000": "U+200B"}
    elif kind == "unique":
        params = {"slice_0000": "order_date"}
    elif kind == "expression":
        column = None
        params = {"expr": "discount <= unit_price * quantity"}
    elif kind == "referential":
        return referential_rule("flag")
    return QualityRuleIR(
        name=f"amount_{kind}" if column else "discount_not_exceeding_gross",
        kind=kind,
        column=column,
        on_fail=on_fail,
        params=tuple(sorted(params.items())),
    )


def referential_rule(on_missing: str) -> QualityRuleIR:
    """The ``referential`` rule under one ``on_missing`` disposition."""
    return QualityRuleIR(
        name="item_of_order_referential",
        kind="referential",
        column=None,
        on_fail=None,
        params=(
            ("on_missing", on_missing),
            ("relationship", "item_of_order"),
            ("to_entity", "order"),
            ("via_0000", "order_id=order_id"),
        ),
    )


#: The ``referential`` axis: one rule per ``on_missing`` value (RFC 0016 §6).
ON_MISSING_RULES = {
    name: referential_rule(name) for name in ("flag", "quarantine", "unknown_member")
}


def predicate_of(rule: QualityRuleIR, *, table: str | None = None) -> Expression:
    """``rule``'s violation predicate, whichever side of the union it is built
    from.

    A branched rule has no predicate without a branch's facts, so a test that
    called :func:`~bloomery.quality.violation` on every kind would raise on two
    of them. Routing here keeps the RFC 0016 §6 matrix iterating *every* kind
    rather than skipping the two, which is the property that matrix exists for.
    """
    if branched(rule):
        return branch_violation(
            rule,
            sources=[SqlExpr(path).ast() for path in BRANCH_SOURCES],
            enum_values=BRANCH_ENUM_VALUES,
            table=table,
        )

    return violation(rule, table=table)
