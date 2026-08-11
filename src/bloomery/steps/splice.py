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

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from sqlglot import exp

from bloomery.errors import StepError

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
        # emission path. But *checked* here rather than trusted from the caller
        # (RFC 0017 D53): a numeric literal renders unquoted, so text that is
        # not a number reaches the SQL as syntax. `factor: "1 OR 1=1"` on a
        # Tier 1 call site emitted `amt * 1 OR 1 = 1` — a predicate spliced
        # into a projection, through the very function whose docstring calls
        # itself the injection boundary. The string branch was always safe
        # because a string literal is quoted; this one had nothing making it so.
        _refuse_non_numeric(value, declared)
        return exp.Literal.number(value)
    return exp.Literal.string(value)


def _refuse_non_numeric(value: str, declared: str) -> None:
    """``value`` must be a number, because it is about to render as one.

    The check lives *below* both tiers deliberately. Tier 2 validates its
    parameters at the registry and Tier 1 did not, and the fix for that shape
    of bug is not to add the missing call at the second call site — it is to
    put the guarantee where the rendering happens, so a third caller cannot
    reintroduce it.
    """
    try:
        Decimal(value.strip())
    except (InvalidOperation, ValueError) as exc:
        msg = (
            f"step parameter value {value!r} is declared {declared!r} but is not a number. "
            "A numeric parameter renders as an unquoted SQL literal, so a non-numeric value "
            "would reach the emitted SQL as syntax rather than as data "
            "(feature: steps). Fix: give the parameter a numeric value, or declare it "
            "'string' so it renders as a quoted literal"
        )
        raise StepError(msg) from exc


def placeholders(body: Expression) -> frozenset[str]:
    """Every ``:name`` the body refers to.

    What the body *refers to* — not the macro's signature, which the manifest
    declares in ``accepts`` (D51). The distinction matters because the caller
    of this function compares the two: ``_refuse_body_disagreement`` reads the
    body's placeholders and checks them against the declaration, so a body that
    quietly grew a ``:name`` its manifest never mentioned is a compile error
    rather than a new implicit parameter.

    This docstring used to say the signature was "read off the body rather than
    declared beside it", which is the design D51 explicitly rejected.
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
