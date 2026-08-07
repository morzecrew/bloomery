"""Spec → IR lowering of the quality surface (RFC 0016 §5.3–§5.6) and the
per-dialect ``pattern`` validation (§5.3).

The lowering's job is to *resolve* what the author did not restate — the
implicit ``coercible`` rule, ``in_enum``'s admissible set, ``referential``'s
join — and to keep every collection canonically ordered so the same spec
always yields the same IR.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from support.compiling import load_fixture

from bloomery import build_project_ir, load_project
from bloomery import dialects as dialects_module
from bloomery.dialects import DialectFeature, SQLGlotDialect, register_dialect
from bloomery.ir import OnFail, quality_sort_key
from bloomery.quality import (
    PIPELINE_STAGES,
    lower_quality,
    opts_in,
    params_of,
    payload_key,
    unsupported_dialects,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clean_overlay(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The dialect registry is process-global and ``pattern`` validation reads
    it, so a leaked extension dialect would silently change another test's
    verdict. Isolate the overlay, exactly as the dialect tests do."""
    monkeypatch.setattr(dialects_module, "_overlay", {})
    yield


def _entity(name: str = "inventory_level"):  # type: ignore[no-untyped-def]
    project, _catalog = load_fixture("semi_additive_inventory")
    entity = project.entity_model.entities[name]
    mapping = next(m for m in project.mappings if m.target == name)
    return project, entity, mapping


# ....................... #
# The fixed pipeline order (D7)


def test_the_pipeline_order_is_declared_once() -> None:
    assert PIPELINE_STAGES == (
        "extract",
        "transform",
        "dedupe",
        "field_rules",
        "row_rules",
        "route",
    )
    # Dedupe sits *before* the rules deliberately: validating first silently
    # replaces a corrupt latest row with a stale-but-clean older one.
    assert PIPELINE_STAGES.index("dedupe") < PIPELINE_STAGES.index("field_rules")


# ....................... #
# Opt-in and the implicit coercible rule


def test_the_fixture_opts_in_and_gets_one_coercible_rule_per_mapped_field() -> None:
    _project, entity, mapping = _entity()
    assert opts_in(entity, mapping)
    rules = lower_quality(entity, mapping, ())
    coercible = [rule.column for rule in rules if rule.kind == "coercible"]
    assert coercible == ["stock_date", "stock_level", "warehouse_id"]
    assert all(rule.on_fail is OnFail.QUARANTINE for rule in rules if rule.kind == "coercible")


def test_a_quality_free_entity_gets_no_rules_at_all() -> None:
    """An entity that never heard of data quality keeps the shipped
    produce-or-raise lowering — the opt-in resolution recorded in
    ``quality/lower.py``'s docstring."""
    project, _catalog = load_fixture("minimal")
    entity = project.entity_model.entities["event"]
    mapping = project.mappings[0]
    assert not opts_in(entity, mapping)
    assert lower_quality(entity, mapping, ()) == ()


def test_rules_are_canonically_sorted_and_uniquely_named() -> None:
    _project, entity, mapping = _entity()
    rules = lower_quality(entity, mapping, ())
    assert list(rules) == sorted(rules, key=quality_sort_key)
    assert len({rule.name for rule in rules}) == len(rules)


def test_the_coercible_rule_carries_the_sources_its_marker_needs() -> None:
    _project, entity, mapping = _entity()
    rule = next(
        r
        for r in lower_quality(entity, mapping, ())
        if r.column == "stock_level" and r.kind == "coercible"
    )
    assert params_of(rule) == {"source_0000": "on_hand"}


def test_range_rules_with_one_bound_are_named_for_that_bound() -> None:
    _project, entity, mapping = _entity()
    names = {rule.name for rule in lower_quality(entity, mapping, ())}
    assert "stock_level_range_min" in names


def test_the_entity_blocks_reach_the_ir() -> None:
    project, catalog = load_fixture("semi_additive_inventory")
    ir = build_project_ir(project, catalog)
    (entity,) = ir.entities
    assert entity.dedupe is not None
    assert entity.dedupe.field == "_ingested_at"
    assert entity.dedupe.tie_break == ("_load_id",)
    assert entity.quarantine is not None
    assert entity.quarantine.retention == "90d"
    assert entity.quarantine.redact == ("$.operator_note",)
    assert entity.source.mapping_version == 1
    assert "$.operator_note" in entity.source.unmapped


def test_the_transform_chain_lowers_try_cast_shaped() -> None:
    """Stage 2 changes from produce-or-raise to produce-a-marker (§5.2, D3)."""
    project, catalog = load_fixture("semi_additive_inventory")
    ir = build_project_ir(project, catalog)
    (entity,) = ir.entities
    assert all("TRY_CAST" in column.expr.sql for column in entity.columns)


def test_a_quality_free_project_keeps_plain_casts() -> None:
    project, catalog = load_fixture("minimal")
    ir = build_project_ir(project, catalog)
    (entity,) = ir.entities
    assert all("TRY_CAST" not in column.expr.sql for column in entity.columns)


# ....................... #
# Resolved settings: in_enum and referential


ENUM_PROJECT = {
    "entity_model": """
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    quarantine: {retention: 30d}
    fields:
      order_id: {type: string, required: true}
      status: {type: string}
""",
    "mapping": """
mapping_version: 1
source: oms__orders
target: order
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  status:
    from: "$.state"
    transform: [{enum_map: [PAID, paid, SHIPPED, shipped]}]
    quality:
      - {rule: in_enum, on_fail: quarantine}
unmapped: ["$._load_id", "$._ingested_at", "$._source_row_id"]
""",
}


def test_in_enum_reads_its_admissible_set_off_the_chain() -> None:
    """The set *is* the chain's mapping (RFC 0016 §5.2): restating it in the
    rule would let the two drift."""
    project = load_project(ENUM_PROJECT)
    entity = project.entity_model.entities["order"]
    rule = next(r for r in lower_quality(entity, project.mappings[0], ()) if r.kind == "in_enum")
    assert params_of(rule) == {"value_0000": "paid", "value_0001": "shipped"}


def test_referential_resolves_the_relationship_at_lowering() -> None:
    project, catalog = load_fixture("ecom_basic")
    entity = project.entity_model.entities["order_item"]
    mapping = next(m for m in project.mappings if m.target == "order_item")
    relationships = project.entity_model.relationships
    # The fixture declares no referential rule; lower one against its
    # relationship by hand to assert what emission may rely on.
    from bloomery.spec.quality import ReferentialRule

    entity = entity.model_copy(
        update={
            "quality": (
                ReferentialRule(rule="referential", via="item_of_order", on_missing="flag"),
            )
        }
    )
    rule = next(r for r in lower_quality(entity, mapping, relationships) if r.kind == "referential")
    assert rule.on_fail is None  # on_missing is not an OnFail
    assert params_of(rule) == {
        "on_missing": "flag",
        "relationship": "item_of_order",
        "to_entity": "order",
        "via_0000": "order_id=order_id",
    }
    assert catalog is not None


# ....................... #
# Payload keys and pattern portability


def test_payload_key_is_the_top_level_bronze_column() -> None:
    assert payload_key("$.a") == "a"
    assert payload_key("$.a.b") == "a"


def test_a_portable_pattern_is_expressible_everywhere() -> None:
    assert unsupported_dialects("^[A-Z]{3}$") == ()


def test_a_dialect_without_a_regex_surface_is_named() -> None:
    class NoRegexDialect(SQLGlotDialect):
        name: str = "noregex"
        sqlglot_dialect: str = "duckdb"
        features = frozenset(DialectFeature) - {DialectFeature.REGEXP_EXTRACT}

    register_dialect(NoRegexDialect())
    assert unsupported_dialects("^[A-Z]{3}$") == ("noregex",)
