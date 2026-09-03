"""Unit / tax-basis / currency coherence (RFC 0006 §5.2): every rule's
trigger, its nearest non-trigger, and the one-report-per-rule-per-expression
dedup — over both derivation and metric expressions."""

from __future__ import annotations

import pytest

from bloomery import load_catalog
from bloomery.errors import CurrencyMismatch, TaxBasisMismatch, UnitMismatch
from bloomery.guardrails.arithmetic import check_arithmetic
from bloomery.guardrails.operands import Derivation
from bloomery.ir import Additivity, MetricIR, SqlExpr
from bloomery.spec import Catalog
from bloomery.spec.catalog import FxRates
from bloomery.transforms import CONVERT_MARKER

pytestmark = pytest.mark.unit

# One metadata carrier per interesting state; entities are irrelevant here
# (grain is test_grain's subject — every field lives on `item`).
CATALOG = load_catalog(
    """\
catalog_version: 1
vertical: v
canonical_fields:
  net_eur: {entity: item, type: "decimal(12,4)", unit: currency, tax_basis: net, currency: EUR}
  net_usd: {entity: item, type: "decimal(12,4)", unit: currency, tax_basis: net, currency: USD}
  other_eur: {entity: item, type: "decimal(12,4)", unit: currency, tax_basis: net, currency: EUR}
  net_price: {entity: item, type: "decimal(12,4)", unit: currency, tax_basis: net}
  gross_price: {entity: item, type: "decimal(12,4)", unit: currency, tax_basis: gross}
  bare_money: {entity: item, type: "decimal(12,4)", unit: currency}
  qty: {entity: item, type: int, unit: count}
  packs: {entity: item, type: int, unit: count}
"""
)


def _derivation(expr: str, *operands: str) -> Derivation:
    return Derivation(
        source_path="mapping[s->item]: fields.f",
        source="s",
        entity="item",
        field="f",
        expr=expr,
        operands=operands,
        direct=None,
    )


def _check(expr: str, *operands: str, catalog: Catalog | None = CATALOG) -> list[Exception]:
    return list(check_arithmetic((_derivation(expr, *operands),), (), catalog))


# ....................... #
# Unit coherence


def test_currency_plus_count_is_a_unit_mismatch() -> None:
    (violation,) = _check("net_price + qty", "net_price", "qty")
    assert isinstance(violation, UnitMismatch)
    assert violation.source_path == "mapping[s->item]: fields.f"
    assert "'net_price' (unit: currency)" in str(violation)
    assert "'qty' (unit: count)" in str(violation)
    assert "Fix:" in str(violation)


def test_shared_unit_passes() -> None:
    assert _check("net_price + other_eur", "net_price", "other_eur") == []


def test_multiplication_is_unit_exempt() -> None:
    # currency × count is how extensive quantities work (RFC 0006 §5.2).
    assert _check("net_price * qty", "net_price", "qty") == []


def test_count_plus_count_passes() -> None:
    assert _check("qty + packs", "qty", "packs") == []


def test_unit_mismatch_reports_once_per_expression() -> None:
    violations = _check("(net_price + qty) - (net_price + qty)", "net_price", "qty")
    assert [type(v) for v in violations] == [UnitMismatch]


# ....................... #
# Tax basis


def test_net_minus_gross_is_a_tax_basis_mismatch() -> None:
    (violation,) = _check("net_price - gross_price", "net_price", "gross_price")
    assert isinstance(violation, TaxBasisMismatch)
    assert "'net_price' (tax_basis: net)" in str(violation)
    assert "'gross_price' (tax_basis: gross)" in str(violation)


def test_unknown_basis_with_a_monetary_operand_is_refused() -> None:
    """RFC 0006 D3 / worked example §5.7: absent metadata on a monetary
    operand poisons additive arithmetic — a TaxBasisMismatch, not a pass."""
    (violation,) = _check("net_price - bare_money", "net_price", "bare_money")
    assert isinstance(violation, TaxBasisMismatch)
    assert "'bare_money' (tax_basis: unknown)" in str(violation)
    assert "unknown poisons" in str(violation)
    assert "declare tax_basis" in str(violation)


def test_shared_basis_passes() -> None:
    assert _check("net_price + other_eur", "net_price", "other_eur") == []


def test_unknown_basis_without_any_monetary_operand_passes() -> None:
    # Neither operand is declared monetary: nothing to poison (RFC 0006 §5.2
    # scopes the rule to arithmetic with a monetary operand).
    assert _check("qty + packs", "qty", "packs") == []


def test_unit_mismatch_subsumes_the_tax_check_at_the_same_node() -> None:
    # qty carries no basis; without the subsumption this would double-report.
    violations = _check("net_price + qty", "net_price", "qty")
    assert [type(v) for v in violations] == [UnitMismatch]


def test_tax_mismatch_reports_once_per_expression() -> None:
    violations = _check(
        "(net_price - gross_price) + (net_price - gross_price)", "net_price", "gross_price"
    )
    assert [type(v) for v in violations] == [TaxBasisMismatch]


# ....................... #
# Currency


def test_distinct_declared_codes_without_convert_are_refused() -> None:
    (violation,) = _check("net_eur + net_usd", "net_eur", "net_usd")
    assert isinstance(violation, CurrencyMismatch)
    assert "'net_eur' (currency: EUR)" in str(violation)
    assert "'net_usd' (currency: USD)" in str(violation)
    assert "convert" in str(violation)


def test_currency_applies_to_any_arithmetic_not_just_additive() -> None:
    (violation,) = _check("net_eur / net_usd", "net_eur", "net_usd")
    assert isinstance(violation, CurrencyMismatch)


def test_same_declared_codes_pass() -> None:
    assert _check("net_eur + other_eur", "net_eur", "other_eur") == []


def test_absent_codes_are_compatible() -> None:
    # Opt-in by design (RFC 0006 D4): declared ≠ declared is the bug worth
    # refusing; net_price declares no code and combines with either.
    assert _check("net_eur + net_price", "net_eur", "net_price") == []


def test_the_convert_marker_no_longer_satisfies_the_rule() -> None:
    # RFC 0023 D5. The marker used to be the escape hatch: its presence on
    # either side permitted the arithmetic. It bought a compile-time "yes"
    # whose only outcome was a run-time failure, and removing it did not come
    # back when conversion shipped (§5.4): a converted amount satisfies this
    # rule by being *declared* in the target currency, not by carrying a token
    # that waives it. A marker sitting in an expression still proves nothing.
    expr = f"{CONVERT_MARKER}(net_eur, 'EUR', 'USD', 'paid_at') + net_usd"
    (violation,) = _check(expr, "net_eur", "net_usd")
    assert isinstance(violation, CurrencyMismatch)
    assert "declares no 'fx_rates:' relation" in str(violation)


def test_the_fix_the_mismatch_names_depends_on_whether_rates_are_declared() -> None:
    """The rule never moves; the advice does.

    Telling an author to derive upstream when a rate relation is right there
    sends them to rebuild what bloomery would do for them. Telling them to
    convert when nothing declares rates sends them to a refusal. Both were one
    message until conversion shipped, and only one of them was ever true.
    """
    without = _check("net_eur + net_usd", "net_eur", "net_usd")
    assert "declares no 'fx_rates:' relation" in str(without[0])
    assert "convert transform" not in str(without[0])

    convertible = CATALOG.model_copy(
        update={
            "fx_rates": FxRates.model_validate(
                {
                    "relation": "fx_rate",
                    "from": "from_ccy",
                    "to": "to_ccy",
                    "rate": "rate",
                    "valid_from": "valid_from",
                    "valid_to": "valid_to",
                }
            )
        }
    )
    (with_rates,) = _check("net_eur + net_usd", "net_eur", "net_usd", catalog=convertible)
    assert "Fix: convert one operand with the convert transform" in str(with_rates)
    assert "declares no" not in str(with_rates)


def test_currency_mismatch_reports_once_per_expression() -> None:
    violations = _check("(net_eur + net_usd) * (net_eur + net_usd)", "net_eur", "net_usd")
    assert [type(v) for v in violations] == [CurrencyMismatch]


# ....................... #
# Walk surface


def test_identity_derivations_and_plain_references_are_skipped() -> None:
    assert _check("net_price", "net_price") == []
    identity = Derivation(
        source_path="mapping[s->item]: fields.f",
        source="s",
        entity="item",
        field="f",
        expr=None,
        operands=("net_price",),
        direct=None,
    )
    assert check_arithmetic((identity,), (), CATALOG) == []


def test_metric_expressions_are_walked_with_the_same_rules() -> None:
    metric = MetricIR(
        name="broken",
        grain="item",
        additivity=Additivity.ADDITIVE,
        agg="sum",
        expr=SqlExpr("net_price - gross_price"),
        ratio=None,
        semi_additive=None,
        depends_on=("gross_price", "net_price"),
    )
    (violation,) = check_arithmetic((), (metric,), CATALOG)
    assert isinstance(violation, TaxBasisMismatch)
    assert violation.source_path == "metrics: metrics.broken"


def test_metrics_without_an_expression_are_skipped() -> None:
    ratio_only = MetricIR(
        name="aov",
        grain="",
        additivity=Additivity.NON_ADDITIVE,
        agg=None,
        expr=None,
        ratio=None,
        semi_additive=None,
        depends_on=(),
    )
    assert check_arithmetic((), (ratio_only,), CATALOG) == []
