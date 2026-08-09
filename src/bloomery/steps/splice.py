"""Tier 1 splicing: a macro body as an expression (RFC 0017 §5.1, D50).

A ``sql_macro`` is the one tier that emits no artifact of its own. Its body is
a single SQL *expression* with ``:name`` placeholders, and it is substituted
into the consuming column's expression at **lowering** — so the model stays
one query and column-level lineage sees straight through it, which is the
whole reason the tier exists.

It lives here rather than in ``emit`` because lowering is where the splice
now happens: ``bloomery.steps`` sits below ``resolve``, and ``emit`` sits
above it, so a splice the emitter owned could not be reached from the stage
that needs it. Putting it below both is what keeps the layering contract
honest instead of routed around.

Substitution is over an **AST**, never over text. That is what keeps Tier 1
inside the SQLGlot-only discipline (RFC 0004 D7) and what makes an argument
data rather than syntax — the same boundary D25/D32 had to close twice on the
generated wrapper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlglot.expressions.core import Expression

__all__ = [
    "parameter_literal",
    "placeholders",
    "splice",
]


def parameter_literal(value: str, declared: str) -> Expression:
    """A resolved parameter as a SQL *literal node*, typed per the manifest.

    Shared by both SQL tiers — Tier 2 substitutes into a model body at emit,
    Tier 1 into a column expression at lowering — and it sits below both so
    neither has to reach across the layering to the other.

    A value authored in a spec reaches emitted SQL here, so it is built as an
    AST literal and never interpolated as text. That is what makes
    ``x\' OR 1=1 --`` a string containing an apostrophe rather than a
    predicate (RFC 0013's injection boundary; RFC 0004 D7's SQLGlot-only rule).

    The *declared* type decides the spelling rather than the shape of the
    digits — the guessing game D20 refused on the Python side, where ``"0.9"``
    and ``"09"`` cannot be told apart by looking. ``date`` and ``timestamp``
    render as string literals the engine compares in the column's own type,
    the convention ``_bound_literal`` established for RFC 0016's range bounds
    (D57); no ``CAST`` spelling is invented here.
    """
    base = declared.split("(", 1)[0].strip()
    if base == "bool":
        return exp.Boolean(this=value.strip().lower() in {"true", "1"})
    if base in {"int", "decimal"}:
        # The text, not a parsed float: RFC 0003 D5 keeps floats out of every
        # emission path, and the value arrived validated at lowering.
        return exp.Literal.number(value)
    return exp.Literal.string(value)


def placeholders(body: Expression) -> frozenset[str]:
    """Every ``:name`` the body refers to.

    The macro's *signature*, read off the body rather than declared beside it:
    a manifest's ``inputs`` are relation-shaped (grain and required columns),
    which a macro has none of — it consumes columns, in an expression. The
    body is therefore the only honest statement of what it needs, and reading
    it is what lets the call site be checked against it (D50).
    """
    return frozenset(
        node.this for node in body.find_all(exp.Placeholder) if isinstance(node.this, str)
    )


def splice(body: Expression, arguments: Mapping[str, Expression]) -> Expression:
    """The body with each placeholder replaced by its argument.

    An argument the body does not mention is ignored rather than refused, and
    the caller is where that is decided: the *call site* checks agreement
    (D50), because only it knows whether an unused name is a typo or a column
    the site legitimately has in scope.

    Each argument is copied on substitution — one placeholder may appear more
    than once (``COALESCE(:x, :x)``), and sharing a node between two positions
    gives one tree two parents.
    """

    def _substitute(node: Expression) -> Expression:
        if isinstance(node, exp.Placeholder) and isinstance(node.this, str):
            replacement = arguments.get(node.this)
            if replacement is not None:
                return replacement.copy()
        return node

    return body.transform(_substitute)
