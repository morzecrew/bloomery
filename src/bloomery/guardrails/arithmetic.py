"""Unit, tax-basis, and currency coherence (RFC 0006 §5.2).

Walks every derivation and metric expression AST; at each ``+``/``-`` node
the unit and tax-basis rules apply, at *any* arithmetic node the currency
rule applies (multiplication and division are unit-exempt — currency × count
is how extensive quantities work):

- **Unit** (:class:`~bloomery.errors.UnitMismatch`): both sides carry a
  declared unit and the units differ — currency + count is the bug.
- **Tax basis** (:class:`~bloomery.errors.TaxBasisMismatch`): ``net`` and
  ``gross`` may not meet; any operand with an *unknown* basis in additive
  arithmetic with a monetary operand is refused — unknown poisons monetary
  arithmetic rather than silently passing (RFC 0006 D3, worked example §5.7).
- **Currency** (:class:`~bloomery.errors.CurrencyMismatch`): both sides
  declare distinct ISO-4217 codes and neither carries an explicit ``convert``
  marker. Absent codes are compatible — opt-in by design (RFC 0006 D4).

Each rule reports at most once per expression (the first offending node in
walk order — deterministic, SQLGlot's walk is syntactic); violations across
expressions batch at the stage (RFC 0006 D2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sqlglot import exp, parse_one
from sqlglot.expressions.core import Expression

from bloomery.errors import CurrencyMismatch, GuardrailError, TaxBasisMismatch, UnitMismatch
from bloomery.guardrails.operands import OperandMeta, operand_meta
from bloomery.ir import Unit

if TYPE_CHECKING:
    from bloomery.guardrails.operands import Derivation
    from bloomery.ir import MetricIR
    from bloomery.spec.catalog import Catalog

__all__ = [
    "check_arithmetic",
]

#: The explicit-conversion marker the ``convert`` transform lowers to
#: (RFC 0004 D3); its presence on a side satisfies the currency rule.
_CONVERT_MARKER = "CONVERT_CURRENCY"

# Keyed by ``exp.Expr`` — sqlglot's static base of ``Binary`` (the runtime
# mro injects ``Expression``, but ``type(node)`` is ``type[Binary]`` to mypy).
_OPS: dict[type[exp.Expr], str] = {
    exp.Add: "+",
    exp.Sub: "-",
    exp.Mul: "*",
    exp.Div: "/",
}


@dataclass(frozen=True, slots=True)
class _Side:
    """One operand side of an arithmetic node: its resolved leaf metadata (in
    syntactic order, deduplicated) and whether the subtree carries an explicit
    ``convert`` marker."""

    metas: tuple[OperandMeta, ...]
    converted: bool


def _summarize(node: Expression, lookup: dict[str, OperandMeta]) -> _Side:
    names = dict.fromkeys(col.name for col in node.find_all(exp.Column) if col.name in lookup)
    converted = any(
        str(call.this).upper() == _CONVERT_MARKER for call in node.find_all(exp.Anonymous)
    )
    return _Side(metas=tuple(lookup[name] for name in names), converted=converted)


def _declared_units(side: _Side) -> set[str]:
    return {meta.unit for meta in side.metas if meta.unit is not None}


def _declared_currencies(side: _Side) -> set[str]:
    return {meta.currency for meta in side.metas if meta.currency is not None}


def _described(metas: tuple[OperandMeta, ...], attribute: str) -> str:
    return ", ".join(
        f"{meta.name!r} ({attribute}: {getattr(meta, attribute) or 'unknown'})" for meta in metas
    )


def _check_units(op: str, left: _Side, right: _Side, source_path: str) -> UnitMismatch | None:
    left_units, right_units = _declared_units(left), _declared_units(right)
    if len(left_units) != 1 or len(right_units) != 1 or left_units == right_units:
        return None
    metas = left.metas + right.metas
    msg = (
        f"{op!r} combines {_described(metas, 'unit')}; operands of '+'/'-' must share a "
        "unit (RFC 0006 §5.2). Fix: derive a shared-unit operand first (e.g. multiply "
        "the count by a per-unit amount), or move the derivation to where the units agree"
    )
    return UnitMismatch(msg, source_path=source_path)


def _check_tax(op: str, left: _Side, right: _Side, source_path: str) -> TaxBasisMismatch | None:
    # The rule is scoped to monetary arithmetic (RFC 0006 §5.2): operands with
    # a declared non-currency unit (a count is not money) carry no basis by
    # nature and are not the "unknown" the rule poisons on.
    metas = tuple(
        meta for meta in left.metas + right.metas if meta.unit is None or meta.unit == Unit.CURRENCY
    )
    if not any(meta.unit == Unit.CURRENCY for meta in metas):
        return None
    described = _described(metas, "tax_basis")
    if any(meta.tax_basis is None for meta in metas):
        msg = (
            f"{op!r} combines {described}; an unknown basis means the canonical field "
            "declares none, so nothing propagates, and arithmetic combining unknown "
            "with a monetary operand is refused (RFC 0006 D3: unknown poisons). Fix: "
            "declare tax_basis on the operand's canonical field, or link the operand "
            "to a canonical field that carries one"
        )
        return TaxBasisMismatch(msg, source_path=source_path)
    if {meta.tax_basis for meta in metas} >= {"net", "gross"}:
        msg = (
            f"{op!r} combines {described}; net and gross may not meet in '+'/'-' "
            "(RFC 0006 §5.2). Fix: convert one operand to the other basis explicitly "
            "before combining"
        )
        return TaxBasisMismatch(msg, source_path=source_path)
    return None


def _check_currency(
    op: str, left: _Side, right: _Side, source_path: str
) -> CurrencyMismatch | None:
    left_codes, right_codes = _declared_currencies(left), _declared_currencies(right)
    if len(left_codes) != 1 or len(right_codes) != 1 or left_codes == right_codes:
        return None
    if left.converted or right.converted:
        return None
    metas = left.metas + right.metas
    msg = (
        f"{op!r} combines {_described(metas, 'currency')} with no explicit convert step; "
        "distinct declared codes require one (RFC 0006 D4). Fix: apply the convert "
        "transform to one operand so the conversion is a recorded, auditable decision"
    )
    return CurrencyMismatch(msg, source_path=source_path)


def _walk(sql: str, lookup: dict[str, OperandMeta], source_path: str) -> list[GuardrailError]:
    """One expression's violations — at most one per rule (first offending
    node in deterministic walk order)."""
    found: dict[type[GuardrailError], GuardrailError] = {}
    tree = cast("Expression", parse_one(sql))
    for node in tree.find_all(exp.Add, exp.Sub, exp.Mul, exp.Div):
        op = _OPS[type(node)]
        left = _summarize(node.this, lookup)
        right = _summarize(node.expression, lookup)
        if isinstance(node, (exp.Add, exp.Sub)):
            unit_hit = _check_units(op, left, right, source_path)
            if unit_hit is not None and UnitMismatch not in found:
                found[UnitMismatch] = unit_hit
            if unit_hit is None and TaxBasisMismatch not in found:
                tax_hit = _check_tax(op, left, right, source_path)
                if tax_hit is not None:
                    found[TaxBasisMismatch] = tax_hit
        if CurrencyMismatch not in found:
            currency_hit = _check_currency(op, left, right, source_path)
            if currency_hit is not None:
                found[CurrencyMismatch] = currency_hit
    return list(found.values())


def check_arithmetic(
    derivations: tuple[Derivation, ...],
    metrics: tuple[MetricIR, ...],
    catalog: Catalog | None,
) -> list[GuardrailError]:
    """Every unit/tax/currency violation across all derivation and metric
    expressions, in walk order (the stage sorts before raising)."""
    violations: list[GuardrailError] = []
    for derivation in derivations:
        if derivation.expr is None:
            continue
        lookup = {
            name: meta
            for name in derivation.operands
            if (meta := operand_meta(name, catalog)) is not None
        }
        violations.extend(_walk(derivation.expr, lookup, derivation.source_path))
    for metric in metrics:
        if metric.expr is None:
            continue
        lookup = {
            name: meta
            for name in metric.depends_on
            if (meta := operand_meta(name, catalog)) is not None
        }
        violations.extend(_walk(metric.expr.sql, lookup, f"metrics: metrics.{metric.name}"))
    return violations
