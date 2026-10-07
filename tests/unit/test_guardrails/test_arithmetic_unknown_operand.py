"""An operand the catalog does not describe is the ``unknown`` the tax rule
poisons on (S-0090/D-1, S-0023/D-3): money beside a field no canonical entry
can vouch for is refused, not passed.

The regression this pins: resolution validates a *metric's* ``requires``
against canonical fields but not a recipe's ``requires``, so a recipe operand
naming no canonical field reaches the guardrail stage. It was dropped from the
operand lookup and left invisible to ``_summarize``, so ``unit_price -
supplier_cost`` compiled clean while ``pages/docs/concepts/guardrails.md``
documents the ``TaxBasisMismatch``.
"""

from __future__ import annotations

import pytest

from bloomery import load_catalog
from bloomery.errors import TaxBasisMismatch
from bloomery.guardrails.arithmetic import check_arithmetic
from bloomery.guardrails.operands import Derivation

pytestmark = pytest.mark.unit

CATALOG = load_catalog(
    """\
catalog_version: 1
vertical: v
canonical_fields:
  unit_price: {entity: item, type: "decimal(12,4)", unit: currency, tax_basis: net}
"""
)


def _derivation(expr: str, *operands: str) -> Derivation:
    return Derivation(
        source_path="entity_model: entities.order_item.fields.margin",
        source="s",
        cleaned=False,
        entity="order_item",
        field="margin",
        expr=expr,
        operands=operands,
        direct=None,
    )


def test_a_monetary_operand_beside_one_with_no_catalog_entry_is_refused() -> None:
    (violation,) = check_arithmetic(
        (_derivation("unit_price - supplier_cost", "unit_price", "supplier_cost"),),
        (),
        CATALOG,
    )
    assert isinstance(violation, TaxBasisMismatch)
    assert "'supplier_cost' (tax_basis: unknown)" in str(violation)


def test_arithmetic_among_unresolved_operands_alone_still_passes() -> None:
    # Nothing monetary to poison: the rule is scoped to arithmetic with a
    # monetary operand (S-0023/metadata-provenance-unit-tax-basis-currency).
    assert (
        check_arithmetic(
            (_derivation("a - b", "a", "b"),),
            (),
            CATALOG,
        )
        == []
    )