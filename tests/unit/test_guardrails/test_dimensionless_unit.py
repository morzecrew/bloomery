"""A dimensionless factor declares `unit: ratio` and carries no tax basis (#367,
S-0023/D-14).

A discount percentage, a VAT rate, a ±1 sign or a 0/1 flag only scales money.
With no unit it was the `unknown` the tax rule poisons on, and the only unit a
catalog could declare for it was `count`, which is wrong for a percentage and
trips the unit rule where the money beside it is unbound.
"""

from __future__ import annotations

import pytest

from bloomery import load_catalog
from bloomery.errors import SpecParseError, TaxBasisMismatch, UnitMismatch
from bloomery.guardrails.arithmetic import check_arithmetic
from bloomery.guardrails.operands import Derivation
from bloomery.ir import Additivity, MetricIR, SqlExpr, Unit

pytestmark = pytest.mark.unit

CATALOG = """\
catalog_version: 1
vertical: v
canonical_fields:
  line_price: {{entity: item, type: int, unit: currency, tax_basis: gross, currency: RUB}}
  line_cost: {{entity: item, type: int, unit: currency, tax_basis: gross, currency: RUB}}
  line_quantity: {{entity: item, type: int, unit: count}}
  line_discount: {{entity: item, type: "decimal(5,2)"{discount}}}
  is_sale: {{entity: item, type: int{flag}}}
  is_return: {{entity: item, type: int{flag}}}
"""


def _check(expr: str, *, discount: str = ", unit: ratio", flag: str = ", unit: ratio") -> list[Exception]:
    catalog = load_catalog(CATALOG.format(discount=discount, flag=flag))
    operands = ("line_price", "line_cost", "line_quantity", "line_discount", "is_sale", "is_return")
    derivation = Derivation(
        source_path="mapping[s->item]: fields.f",
        source="s",
        cleaned=False,
        entity="item",
        field="f",
        expr=expr,
        operands=operands,
        direct=None,
    )
    return list(check_arithmetic((derivation,), (), catalog))


GROSS_PROFIT = "(line_price * (100 - line_discount) / 100 - line_cost) * line_quantity"


def test_the_issue_s_percentage_was_refused_as_an_unknown_basis() -> None:
    """Undeclared, the factor still poisons: nothing about this case changed."""
    (violation,) = _check(GROSS_PROFIT, discount="")

    assert isinstance(violation, TaxBasisMismatch)
    assert "'line_discount' (tax_basis: unknown)" in str(violation)


def test_a_declared_ratio_scales_money_with_no_basis_of_its_own() -> None:
    assert _check(GROSS_PROFIT) == []


def test_a_sign_of_flags_scales_money_too() -> None:
    """The issue's second shape, with the cost bound."""
    assert _check("line_price - line_cost * (is_sale - is_return)") == []


def test_the_issue_s_template_passes_as_a_metric() -> None:
    """The metric path reads the same rule, over its `requires:`."""
    metric = MetricIR(
        name="gross_profit",
        grain="item",
        additivity=Additivity.ADDITIVE,
        agg="sum",
        expr=SqlExpr(GROSS_PROFIT),
        ratio=None,
        semi_additive=None,
        depends_on=("line_cost", "line_discount", "line_price", "line_quantity"),
    )
    catalog = load_catalog(CATALOG.format(discount=", unit: ratio", flag=""))

    assert check_arithmetic((), (metric,), catalog) == []


def test_a_ratio_added_to_money_is_still_a_unit_mismatch() -> None:
    """Dimensionless is a unit: adding a rate to a price is the bug the unit
    rule exists for, as adding a count is."""
    (violation,) = _check("line_price + line_discount")

    assert isinstance(violation, UnitMismatch)
    assert "'line_discount' (unit: ratio)" in str(violation)


def test_two_ratios_add() -> None:
    assert _check("is_sale - is_return") == []


def test_a_ratio_beside_a_count_is_a_unit_mismatch() -> None:
    (violation,) = _check("line_quantity + line_discount")

    assert isinstance(violation, UnitMismatch)


def test_the_catalog_refuses_any_other_unit() -> None:
    with pytest.raises(SpecParseError, match="'currency', 'count' or 'ratio'"):
        load_catalog(CATALOG.format(discount=", unit: percent", flag=""))


def test_the_ir_unit_is_the_catalog_s() -> None:
    assert Unit("ratio") is Unit.RATIO


@pytest.mark.parametrize("declared", ["currency: EUR", "tax_basis: net"])
def test_a_ratio_declares_no_currency_and_no_tax_basis(declared: str) -> None:
    """A dimensionless number is not money. A currency on one would make the
    currency rule read `price_usd * vat_rate` as two currencies meeting, and
    a tax basis would be a declaration no rule reads."""
    with pytest.raises(SpecParseError, match="unit: ratio") as refused:
        load_catalog(CATALOG.format(discount=f", unit: ratio, {declared}", flag=""))

    assert "canonical_fields.line_discount" in (refused.value.source_path or "")
