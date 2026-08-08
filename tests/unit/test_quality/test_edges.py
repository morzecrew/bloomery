"""The branches the happy paths never take.

Each of these is a *decision* the lowering makes — a one-sided bound, a bound
that is not a number, an ``in_enum`` on a field with no ``enum_map``, an
extension dialect that is not a :class:`SQLGlotDialect` — and an untested
decision is one nobody notices flipping.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlglot.expressions.core import Expression

from bloomery import dialects as dialects_module
from bloomery import load_project
from bloomery.dialects import DialectFeature
from bloomery.ir import OnFail, QualityRuleIR
from bloomery.quality import lower_quality, params_of, unsupported_dialects, violation
from bloomery.spec.quality import InEnumRule
from support.compiling import load_fixture

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_overlay(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(dialects_module, "_overlay", {})
    yield


def _rule(kind: str, **params: str) -> QualityRuleIR:
    return QualityRuleIR(
        name=f"amount_{kind}",
        kind=kind,
        column="amount",
        on_fail=OnFail.FLAG,
        params=tuple(sorted(params.items())),
    )


# ....................... #
# One-sided bounds and non-numeric bounds


@pytest.mark.parametrize("kind", ["range", "length"])
def test_a_max_only_bound_lowers_to_the_upper_comparison_alone(kind: str) -> None:
    assert violation(_rule(kind, max="10")).sql() == (
        "amount > 10" if kind == "range" else "LENGTH(amount) > 10"
    )


@pytest.mark.parametrize("kind", ["range", "length"])
def test_a_min_only_bound_lowers_to_the_lower_comparison_alone(kind: str) -> None:
    assert violation(_rule(kind, min="1")).sql() == (
        "amount < 1" if kind == "range" else "LENGTH(amount) < 1"
    )


def test_a_temporal_range_bound_stays_a_string_literal() -> None:
    """Bounds arrive as text and leave as text — floats never enter an
    emission path (RFC 0003 D5), and the engine compares in the column's own
    type."""
    assert violation(_rule("range", min="2024-01-01")).sql() == "amount < '2024-01-01'"


# ....................... #
# Rule naming for two bounds on one column


BOTH_BOUNDS = """
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    quarantine: {retention: 30d}
    fields:
      order_id: {type: string, required: true}
      amount: {type: int}
"""

BOTH_BOUNDS_MAPPING = """
mapping_version: 1
source: oms__orders
target: order
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  amount:
    from: "$.amount"
    transform: [to_int]
    quality:
      - {rule: range, min: 0, on_fail: quarantine}
      - {rule: range, max: 1000000, on_fail: flag}
      - {rule: in_enum, on_fail: flag}
      - {rule: in_set, values: [1, 2], on_fail: flag}
      - {rule: unique, on_fail: flag}
      - {rule: length, min: 1, on_fail: flag}
      - {rule: range, min: 2, max: 9, on_fail: flag}
unmapped: ["$._load_id", "$._ingested_at", "$._source_row_id"]
"""


def _both_bounds() -> tuple[QualityRuleIR, ...]:
    project = load_project({"entity_model": BOTH_BOUNDS, "mapping": BOTH_BOUNDS_MAPPING})
    return lower_quality(project.entity_model.entities["order"], project.mappings[0], ())


def test_two_bounds_with_different_dispositions_get_distinct_names() -> None:
    """§5.3's worked example: ``min: 0`` quarantines, ``max: 1000000`` flags —
    two rules, two names, both readable in ``failed_rules``."""
    names = {rule.name for rule in _both_bounds()}
    assert {"amount_range_min", "amount_range_max"} <= names


def test_in_enum_on_a_chain_with_no_enum_map_has_an_empty_admissible_set() -> None:
    """The set *is* the chain's mapping, so a chain with no ``enum_map`` step
    admits nothing — the rule fires on every non-null value, which is what an
    author who wrote it on the wrong field will notice immediately."""
    rule = next(rule for rule in _both_bounds() if rule.kind == "in_enum")
    assert params_of(rule) == {}


def test_in_set_carries_its_literal_members_and_unique_its_slice() -> None:
    """``in_set`` restates its members inline (it has no chain to read them
    off); ``unique``'s slice is the entity's partition — empty here, so the
    window covers the whole table (D5).

    The members here are declared as YAML integers, so each carries its
    ``numeric_NNNN`` type flag beside its text: the IR's params are strings,
    and a member whose declared type is lost renders as a string literal —
    which DuckDB and Postgres coerce and Trino refuses.
    """
    by_kind = {rule.kind: rule for rule in _both_bounds()}
    assert params_of(by_kind["in_set"]) == {
        "numeric_0000": "true",
        "numeric_0001": "true",
        "value_0000": "1",
        "value_0001": "2",
    }
    assert params_of(by_kind["unique"]) == {}
    assert params_of(by_kind["length"]) == {"min": "1"}


def test_a_two_sided_bound_keeps_the_plain_rule_name() -> None:
    """Only a one-sided bound needs the ``_min``/``_max`` suffix to stay
    distinguishable."""
    names = {rule.name for rule in _both_bounds()}
    assert "amount_range" in names


def test_a_recipe_field_has_no_enum_chain_to_read() -> None:
    """A recipe binds aliases, not a transform chain — there is no
    ``enum_map`` step to read an admissible set off, so the admissible set is
    empty rather than guessed."""
    project, _catalog = load_fixture("semi_additive_inventory")
    entity = project.entity_model.entities["inventory_level"]
    mapping = project.mappings[0]
    recipe_field = mapping.fields["stock_level"]
    patched = mapping.model_copy(
        update={
            "fields": {
                "stock_level": recipe_field.model_copy(
                    update={"quality": (InEnumRule(rule="in_enum", on_fail="flag"),)}
                )
            }
        }
    )
    rule = next(rule for rule in lower_quality(entity, patched, ()) if rule.kind == "in_enum")
    assert params_of(rule) == {}


def test_a_rule_pair_that_would_share_a_name_is_disambiguated() -> None:
    """Two identically shaped rules on one column would otherwise share a
    name, and a shared name in ``failed_rules`` is an unreadable reject row."""
    documents = {
        "entity_model": BOTH_BOUNDS,
        "mapping": BOTH_BOUNDS_MAPPING.replace(
            "      - {rule: in_enum, on_fail: flag}\n",
            "      - {rule: not_null, on_fail: flag}\n      - {rule: not_null, on_fail: fail}\n",
        ),
    }
    project = load_project(documents)
    rules = lower_quality(project.entity_model.entities["order"], project.mappings[0], ())
    names = sorted(rule.name for rule in rules if rule.kind == "not_null")
    assert names == ["amount_not_null", "amount_not_null_2"]


# ....................... #
# Extension dialects in the pattern check


def test_a_non_sqlglot_dialect_is_probed_under_its_own_name() -> None:
    class Bespoke:
        name = "bespoke"

        def render(self, node: Expression) -> str:  # pragma: no cover — never called
            return node.sql()

        def physical_type(self, t: object) -> str:  # pragma: no cover — never called
            return "TEXT"

        def supports(self, feature: DialectFeature) -> bool:
            return True

    dialects_module.register_dialect(Bespoke())
    # SQLGlot has no ``bespoke`` generator, so the round-trip refuses rather
    # than silently rendering something the engine may not mean. The caller
    # supplies the dialect set — registering one never changes a verdict
    # (RFC 0016 D56).
    assert unsupported_dialects("^[A-Z]{3}$", dialects=(Bespoke(),)) == ("bespoke",)
    assert unsupported_dialects("^[A-Z]{3}$") == ()
