"""The IR builder (RFC 0003 §12, RFC 0004/0005 integration): lowering rules,
materialization defaults, reachable-only metrics, batched typecheck failures."""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_catalog, load_project, project_fingerprint
from bloomery.errors import ResolutionError, TypeCheckError
from bloomery.ir import (
    DateDimensionIR,
    DimensionRef,
    MartJoinIR,
    Materialization,
    PartitionSpec,
    UnreachableMetric,
)
from bloomery.typing import DecimalType, StringType, TimestampType
from support.compiling import load_fixture

pytestmark = pytest.mark.unit


def test_minimal_ir_lowering() -> None:
    project, _ = load_fixture("minimal")
    ir = build_project_ir(project)
    (entity,) = ir.entities
    assert entity.name == "event"
    assert entity.materialization is Materialization.FULL
    assert [c.name for c in entity.columns] == ["event_id", "kind", "occurred_at"]
    by_name = {c.name: c for c in entity.columns}
    # The lowered expression moved to the source (RFC 0024 D26).
    lowered = {c.name: c for c in entity.sources[0].columns}
    # A chain lowers through the registry builders; a chain-less mapping is a
    # declared-type cast at extraction.
    assert lowered["event_id"].expr.sql == "CAST(id AS TEXT)"
    assert lowered["occurred_at"].expr.sql == "CAST(ts AS TIMESTAMP)"
    assert by_name["occurred_at"].type == TimestampType()
    assert entity.sources[0].relation == "raw__events"
    assert ir.metrics == ()
    assert ir.marts == ()


def test_ecom_recipe_lowering_records_the_recipe_id() -> None:
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    order_item = next(e for e in ir.entities if e.name == "order_item")
    unit_price = next(c for c in order_item.columns if c.name == "unit_price")
    lowered = next(c for c in order_item.sources[0].columns if c.name == "unit_price")
    assert lowered.expr.sql == "CAST(total / qty AS DECIMAL(12, 4))"
    assert lowered.recipe_id == "from_total"
    assert unit_price.type == DecimalType(12, 4)
    assert unit_price.canonical == "unit_price"
    assert unit_price.unit is not None and unit_price.unit.value == "currency"
    assert unit_price.tax_basis is not None and unit_price.tax_basis.value == "net"


def test_ecom_nested_jsonpath_lowering() -> None:
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    order = next(e for e in ir.entities if e.name == "order")
    customer_id = next(c for c in order.columns if c.name == "customer_id")
    lowered = next(c for c in order.sources[0].columns if c.name == "customer_id")
    assert lowered.expr.sql == "CAST(JSON_EXTRACT_SCALAR(customer, '$.id') AS TEXT)"
    assert customer_id.type == StringType()


def test_materialization_default_derives_from_partitioning() -> None:
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    by_name = {e.name: e for e in ir.entities}
    # partition_by present → incremental_by_partition (RFC 0002 D7).
    assert by_name["order_item"].materialization is Materialization.INCREMENTAL_BY_PARTITION
    assert by_name["order_item"].partition_by == (
        PartitionSpec(transform="days", column="order_date"),
    )
    # No partitioning → full.
    assert by_name["order"].materialization is Materialization.FULL


def test_explicit_materialization_wins_over_the_derived_default() -> None:
    project, _ = load_fixture("minimal")
    model = """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    partition_by: [days(occurred_at)]
    materialization: full
    fields:
      event_id: {type: string, required: true}
      kind: {type: string}
      occurred_at: {type: timestamp}
"""
    mapping = """\
mapping_version: 1
source: raw__events
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
fields:
  occurred_at: {from: "$.ts"}
"""
    ir = build_project_ir(load_project({"entity_model": model, "mapping": mapping}))
    assert ir.entities[0].materialization is Materialization.FULL


def test_only_reachable_metrics_are_lowered() -> None:
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    assert [m.name for m in ir.metrics] == [
        "average_order_value",
        "gross_revenue",
        "order_count",
    ]
    assert ir.unreachable == (UnreachableMetric(name="margin", missing=("cogs",)),)
    aov = ir.metrics[0]
    assert aov.depends_on == ("gross_revenue", "order_count")
    assert aov.ratio is not None
    gross = ir.metrics[1]
    assert gross.expr is not None and gross.expr.sql == "unit_price * quantity"
    assert gross.agg == "sum"
    assert gross.depends_on == ("quantity", "unit_price")


def test_relationships_are_lowered_sorted() -> None:
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    (rel,) = ir.relationships
    assert rel.name == "item_of_order"
    assert rel.from_entity == "order_item"
    assert rel.to_entity == "order"
    assert rel.via == (("order_id", "order_id"),)


def test_ecom_basic_mart_lowers_to_the_flattened_wide_schema() -> None:
    """ecom_basic's mart document lowers at M5 (RFC 0010 D6): base columns
    unprefixed, via-flattened columns prefixed, the ordered date role expanded
    into the five buckets, the join resolved — all collections sorted."""
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    (mart,) = ir.marts
    assert mart.name == "order_items"
    assert mart.grain == mart.base == "order_item"
    assert [c.name for c in mart.columns] == [
        "line_no",
        "order_customer_id",
        "order_date",
        "order_id",
        "order_order_id",
        "ordered_day",
        "ordered_month",
        "ordered_quarter",
        "ordered_week",
        "ordered_year",
        "quantity",
        "unit_price",
    ]
    ordered_day = next(c for c in mart.columns if c.name == "ordered_day")
    assert (ordered_day.source_entity, ordered_day.source_column) == ("order_item", "order_date")
    assert ordered_day.ref == DimensionRef(dimension="day", role="ordered")
    flattened = next(c for c in mart.columns if c.name == "order_customer_id")
    assert (flattened.source_entity, flattened.source_column) == ("order", "customer_id")
    assert flattened.ref is None
    assert mart.joins == (
        MartJoinIR(
            relationship="item_of_order",
            entity="order",
            prefix="order_",
            on=(("order_id", "order_id"),),
        ),
    )
    assert mart.measures == ("gross_revenue",)
    # RFC 0010 §10: every flattened column is a requestable dimension.
    assert [d.ref.qualified for d in mart.dimensions] == [c.name for c in mart.columns]
    assert mart.materialization is Materialization.INCREMENTAL_BY_PARTITION
    assert mart.partition_by == (PartitionSpec(transform="days", column="ordered_day"),)
    assert mart.cost_hint == 2


def test_role_playing_dates_lowers_both_roles() -> None:
    project, catalog = load_fixture("role_playing_dates")
    ir = build_project_ir(project, catalog)
    (mart,) = ir.marts
    assert mart.base == "order"
    assert mart.joins == ()
    roles = {c.ref.role: c.source_column for c in mart.columns if c.ref is not None}
    assert roles == {"ordered": "order_date", "shipped": "ship_date"}
    buckets = sorted(c.name for c in mart.columns if c.ref is not None)
    assert buckets[:5] == [
        "ordered_day",
        "ordered_month",
        "ordered_quarter",
        "ordered_week",
        "ordered_year",
    ]
    assert buckets[5:] == [
        "shipped_day",
        "shipped_month",
        "shipped_quarter",
        "shipped_week",
        "shipped_year",
    ]


def test_catalog_date_dimension_lowers_onto_the_ir() -> None:
    """One catalog definition drives dim_date and the M6 time spine
    (RFC 0008 D13); a catalog-free project carries none."""
    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog)
    assert ir.date_dimension == DateDimensionIR(
        name="dim_date", grain="day", start_year=2020, end_year=2030
    )
    minimal_project, _ = load_fixture("minimal")
    assert build_project_ir(minimal_project).date_dimension is None


def test_fingerprint_is_stable_across_builds() -> None:
    project, catalog = load_fixture("ecom_basic")
    first = project_fingerprint(build_project_ir(project, catalog))
    second = project_fingerprint(build_project_ir(project, catalog))
    assert first == second
    assert first.startswith("blm1:")


def test_typecheck_failures_are_batched_across_mappings() -> None:
    model = """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    fields:
      event_id: {type: string, required: true}
      amount: {type: "decimal(10,2)"}
      kind: {type: string}
"""
    mapping = """\
mapping_version: 1
source: raw__events
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
fields:
  amount: {from: "$.amount", transform: [{to_decimal: [12, 4]}]}
  kind: {from: "$.kind", transform: [pars_ts]}
"""
    project = load_project({"entity_model": model, "mapping": mapping})
    with pytest.raises(TypeCheckError) as excinfo:
        build_project_ir(project)
    error = excinfo.value
    assert len(error.collected) == 2
    assert "mapping[raw__events->event]: fields.amount" in str(error)
    assert "mapping[raw__events->event]: fields.kind.transform[0]" in str(error)
    assert "closest match: 'parse_ts'" in str(error)


# ....................... #
# The union merge (RFC 0024): two mappings, one entity.


_MERGE_ENTITY_MODEL = """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    fields:
      event_id: {type: string, required: true}
      kind: {type: string}
      note: {type: string}
"""


#: The mapping of ``src_a``, and the mapping of ``src_z``. Which *document*
#: carries which is varied by the callers below, because ``load_project`` reads
#: documents in sorted-name order — so a helper whose document names agree with
#: its source names cannot tell "sorted by source" from "sorted by document",
#: and every ordering assertion over it passes either way.
_SRC_A_MAPPING = """\
mapping_version: 1
source: src_a
target: event
key:
  event_id: {from: "$.identifier", transform: [to_string]}
fields:
  kind: {from: "$.type", transform: [to_string]}
"""

_SRC_Z_MAPPING = """\
mapping_version: 1
source: src_z
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
fields:
  kind: {from: "$.kind", transform: [to_string]}
  note: {from: "$.note", transform: [to_string]}
"""


def _merge_sources(**overrides: str) -> dict[str, str]:
    """Two mappings targeting ``event``, with the **later** source relation in
    the **earlier** document.

    ``mapping_a`` holds ``src_z`` and ``mapping_z`` holds ``src_a``, so
    document order and branch order disagree and an assertion about branch
    order is testing D3 rather than testing that documents happened to sort the
    right way.
    """
    sources = {
        "entity_model": _MERGE_ENTITY_MODEL,
        "mapping_a": _SRC_Z_MAPPING,
        "mapping_z": _SRC_A_MAPPING,
    }
    sources.update(overrides)
    return sources


def test_two_mappings_build_one_entity_ordered_lexicographically() -> None:
    """RFC 0024 D1/D3: the refusal this replaces kept a promise nothing else
    was scheduled to keep."""
    ir = build_project_ir(load_project(_merge_sources()))
    (entity,) = ir.entities
    assert entity.name == "event"
    # `src_z`'s mapping is in the first document and `src_a`'s in the second;
    # the branches come out the other way round. Branch order is the source
    # relation's, not the document's, or the emitted SQL would depend on what
    # somebody named a file.
    assert [source.relation for source in entity.sources] == ["src_a", "src_z"]
    # One schema, one projection per source per column.
    assert [column.name for column in entity.columns] == ["event_id", "kind", "note"]
    for source in entity.sources:
        assert [column.name for column in source.columns] == ["event_id", "kind", "note"]
    # Each branch keeps its own lowering — the whole reason `expr` moved off
    # `ColumnIR` (D26).
    lowered = {
        source.relation: {column.name: column.expr.sql for column in source.columns}
        for source in entity.sources
    }
    assert lowered["src_a"]["event_id"] != lowered["src_z"]["event_id"]
    assert "identifier" in lowered["src_a"]["event_id"]
    assert "id" in lowered["src_z"]["event_id"]


def test_a_field_no_mapping_produces_is_a_typed_null_in_every_branch() -> None:
    """RFC 0024 §5.2 rule 3. A branch missing a column is not a narrower
    branch — it is a `UNION ALL` whose arms disagree on arity."""
    ir = build_project_ir(load_project(_merge_sources()))
    (entity,) = ir.entities
    lowered = {
        source.relation: {column.name: column.expr.sql for column in source.columns}
        for source in entity.sources
    }
    # `src_z` maps `note`; `src_a` has never heard of it. Both branches project
    # it, or the arms disagree on arity and the union is invalid SQL.
    filled = lowered["src_a"]["note"].upper()
    assert "NULL" in filled
    # Cast, not a bare NULL: an untyped null makes the union's column type
    # depend on which branch the engine reads first.
    assert "CAST" in filled
    assert "NOTE" in lowered["src_z"]["note"].upper()


def test_declaration_order_cannot_move_the_ir() -> None:
    """D3's determinism claim, at the level the builder can prove it.

    The same two mappings, swapped between the two document names — so they
    reach the builder in both orders `load_project` can deliver them in. The
    IR records no document name, so the two compilations must be equal, and
    they are only equal if branch order is derived from the source relation.
    """
    forward = build_project_ir(
        load_project(
            {
                "entity_model": _MERGE_ENTITY_MODEL,
                "mapping_a": _SRC_Z_MAPPING,
                "mapping_z": _SRC_A_MAPPING,
            }
        )
    )
    swapped = build_project_ir(
        load_project(
            {
                "entity_model": _MERGE_ENTITY_MODEL,
                "mapping_a": _SRC_A_MAPPING,
                "mapping_z": _SRC_Z_MAPPING,
            }
        )
    )
    assert swapped == forward


def test_two_mappings_on_one_relation_are_refused() -> None:
    """RFC 0024 D12: lexicographic order needs a total order, and two branches
    on one relation tie."""
    sources = _merge_sources(
        mapping_z="""\
mapping_version: 1
source: src_z
target: event
key:
  event_id: {from: "$.identifier", transform: [to_string]}
""",
    )
    with pytest.raises(ResolutionError) as excinfo:
        build_project_ir(load_project(sources))
    message = str(excinfo.value)
    assert "src_z" in message
    assert "RFC 0024 D12" in message
    assert "one mapping with a filter" in message


def test_a_required_field_one_mapping_omits_is_refused() -> None:
    """RFC 0024 D4. The check is the merge's, deliberately: one bad source
    silently poisons a column the others fill correctly."""
    sources = _merge_sources(
        mapping_a="""\
mapping_version: 1
source: src_a
target: event
key:
  kind: {from: "$.type", transform: [to_string]}
""",
        entity_model="""\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [kind]
    fields:
      kind: {type: string}
      event_id: {type: string, required: true}
""",
        mapping_z="""\
mapping_version: 1
source: src_z
target: event
key:
  kind: {from: "$.kind", transform: [to_string]}
fields:
  event_id: {from: "$.id", transform: [to_string]}
""",
    )
    with pytest.raises(ResolutionError) as excinfo:
        build_project_ir(load_project(sources))
    message = str(excinfo.value)
    assert "'event_id'" in message
    assert "RFC 0024 D4" in message
    # The offending mapping, not the entity — an author needs the document to
    # open, in the message and in the source path (§6).
    assert "src_a" in message
    assert excinfo.value.source_path == "mapping[src_a->event]: fields"


def test_a_single_mapping_may_still_omit_a_required_field() -> None:
    """The converse of D4, and the reason it is scoped to a merge: the
    coverage asymmetry predates this RFC (§5.2 rule 2) and widening it here
    would be a compatibility break the RFC does not authorize."""
    sources = {
        "entity_model": _MERGE_ENTITY_MODEL,
        "mapping_z": """\
mapping_version: 1
source: src_z
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
""",
    }
    ir = build_project_ir(load_project(sources))
    (entity,) = ir.entities
    assert [column.name for column in entity.columns] == ["event_id"]


@pytest.mark.parametrize(
    ("block", "citation", "phase"),
    [
        (
            """\
    dedupe: {keep: latest_by, field: occurred_at}
""",
            "RFC 0024 D14",
            "RFC 0024 §12 P2b",
        ),
        (
            """\
    quarantine: {retention: 90d}
""",
            "RFC 0024 D14",
            "RFC 0024 §12 P2c",
        ),
        (
            """\
    quality:
      - {rule: expression, name: has_kind, expr: "kind IS NOT NULL", on_fail: flag}
""",
            "RFC 0024 D29",
            "RFC 0024 §12 P2a",
        ),
    ],
    ids=["dedupe", "quarantine", "entity_quality"],
)
def test_the_quality_system_is_refused_on_a_merged_entity(
    block: str, citation: str, phase: str
) -> None:
    """RFC 0024 D14, widened by D29. Each leg of ``opts_in`` is its own
    assertion: the predicate is a disjunction, and a test of one leg proves
    nothing about the others.

    ``phase`` is asserted separately from ``citation`` because the two answer
    different questions and only one of them was ever wrong: the citation says
    *why* the construct is refused, the phase says *where the merged form is
    designed* — and §12 puts `dedupe:` in P2b and `quarantine:` in P2c. One
    message served both blocks, so a `quarantine:` refusal routed its reader to
    the phase that restores the other block.
    """
    model = _MERGE_ENTITY_MODEL.replace(
        "      note: {type: string}\n", "      note: {type: string}\n" + block
    )
    with pytest.raises(ResolutionError) as excinfo:
        build_project_ir(load_project(_merge_sources(entity_model=model)))
    message = str(excinfo.value)
    assert citation in message
    assert phase in message


def test_a_field_level_quality_block_is_refused_on_a_merged_entity() -> None:
    """The third leg of ``opts_in`` (D29), and the one the row is really about:
    a field rule is declared on a *mapping*, so two mappings can disagree about
    whether the entity joined the quality system at all."""
    sources = _merge_sources(
        mapping_z="""\
mapping_version: 1
source: src_a
target: event
key:
  event_id: {from: "$.identifier", transform: [to_string]}
fields:
  kind:
    from: "$.type"
    transform: [to_string]
    quality:
      - {rule: not_null, on_fail: flag}
""",
    )
    with pytest.raises(ResolutionError) as excinfo:
        build_project_ir(load_project(sources))
    message = str(excinfo.value)
    assert "RFC 0024 D29" in message
    # It names the mapping's own document, not the entity model.
    assert excinfo.value.source_path is not None
    assert "fields.kind.quality" in excinfo.value.source_path


def test_a_mart_over_a_merged_entity_flattens() -> None:
    """Marts are not in RFC 0024's surface, and that is the claim being tested.

    A mart reads the base entity's *schema* — `columns`, `key` — and the silver
    relation, and the merge changes the shape of neither: the union is below the
    relation the mart selects from. Pinned because "nothing to do here" is a
    statement about the code that only a test keeps true, and because `_source`
    staying out of the flattened column set is the observable half of it not
    being a declared field.
    """
    sources = _merge_sources(
        entity_model="""\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    fields:
      event_id: {type: string, required: true}
      kind: {type: string}
      occurred_at: {type: timestamp}
""",
        mapping_a="""\
mapping_version: 1
source: src_z
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
fields:
  kind: {from: "$.kind", transform: [to_string]}
  occurred_at: {from: "$.ts", transform: [{parse_ts: ["ISO8601"]}]}
""",
        mapping_z="""\
mapping_version: 1
source: src_a
target: event
key:
  event_id: {from: "$.identifier", transform: [to_string]}
fields:
  kind: {from: "$.type", transform: [to_string]}
  occurred_at: {from: "$.at", transform: [{parse_ts: ["ISO8601"]}]}
""",
        marts="""\
marts_version: 1
marts:
  events:
    grain: event
    base: event
    flatten:
      - {date: occurred_at, role: seen}
""",
    )
    ir = build_project_ir(load_project(sources))
    (mart,) = ir.marts
    names = [column.name for column in mart.columns]
    assert "event_id" in names
    assert "seen_day" in names
    # `_source` is a generated column, not a declared field, so it is not a
    # dimension — a mart over a merged entity is a mart like any other.
    assert "_source" not in names


def test_a_mapping_lowering_a_partial_key_is_refused() -> None:
    """§5.2 rule 1, and it needs no code of its own: `resolve.refs` enforces
    full-key coverage per mapping, so it enforces it per branch. Pinned here
    because the merge is what makes a partial key meaningless rather than
    merely incomplete — a union on one is a relation whose rows cannot be told
    apart."""
    sources = _merge_sources(
        entity_model=_MERGE_ENTITY_MODEL.replace(
            "    key: [event_id]\n", "    key: [event_id, kind]\n"
        )
    )
    with pytest.raises(ResolutionError) as excinfo:
        build_project_ir(load_project(sources))
    message = str(excinfo.value)
    assert "'kind' is not lowered by the mapping's key" in message
    # Both mappings, not just the first: an author fixes the spec in one round.
    assert message.count("is not lowered by the mapping's key") == 2


def test_a_direct_path_is_refused_on_a_merged_entity() -> None:
    """RFC 0024 D28. `direct:` is per mapping, so a merged entity can have one
    on one source and none on another — which leaves the shadow NULL for the
    other's rows, indistinguishable from a genuinely NULL direct value, and the
    reconcile audit either reports a false disagreement or quietly stops
    checking."""
    sources = _merge_sources(
        entity_model="""\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    fields:
      event_id: {type: string, required: true}
      kind: {type: string, canonical: kind}
""",
        mapping_z="""\
mapping_version: 1
source: src_a
target: event
key:
  event_id: {from: "$.identifier", transform: [to_string]}
fields:
  kind:
    recipe: passthrough
    from: {value: "$.type"}
    direct: "$.kind_direct"
""",
        mapping_a="""\
mapping_version: 1
source: src_z
target: event
key:
  event_id: {from: "$.id", transform: [to_string]}
fields:
  kind: {from: "$.kind", transform: [to_string]}
""",
    )
    catalog = load_catalog("""\
catalog_version: 1
vertical: ecom_retail
canonical_fields:
  kind:
    entity: event
    type: string
    recipes:
      - {id: passthrough, requires: [value], expr: "value"}
""")
    with pytest.raises(ResolutionError) as excinfo:
        build_project_ir(load_project(sources), catalog)
    message = str(excinfo.value)
    assert "RFC 0024 D28" in message
    assert "kind__direct" in message


def test_scd_type2_is_refused_on_a_merged_entity() -> None:
    """RFC 0024 D23: the collision audit would fire on every key holding
    versions from two sources, and telling a version from a collision needs the
    audit to read the validity interval — which the union's lowering does not,
    even now that RFC 0023 §5.3 models the interval."""
    model = _MERGE_ENTITY_MODEL.replace(
        "    key: [event_id]\n", "    key: [event_id]\n    scd: type2\n"
    )
    with pytest.raises(ResolutionError) as excinfo:
        build_project_ir(load_project(_merge_sources(entity_model=model)))
    message = str(excinfo.value)
    assert "RFC 0024 D23" in message
    assert "RFC 0023" in message


def test_the_refusals_are_batched() -> None:
    """§5.2: an author sees every disagreement at once (RFC 0002 D6), rather
    than fixing one and recompiling to find the next."""
    model = _MERGE_ENTITY_MODEL.replace(
        "    key: [event_id]\n", "    key: [event_id]\n    scd: type2\n"
    ).replace(
        "      note: {type: string}\n",
        "      note: {type: string}\n"
        "    dedupe: {keep: latest_by, field: occurred_at}\n",
    )
    with pytest.raises(ResolutionError) as excinfo:
        build_project_ir(load_project(_merge_sources(entity_model=model)))
    assert len(excinfo.value.collected) >= 2


def test_a_type2_entity_may_not_carry_a_validity_column_name() -> None:
    """RFC 0023 §5.3: the target's snapshot writes `valid_from`/`valid_to` onto
    the historical relation, so an authored column of that name would leave two
    columns with one name and an as-of join comparing against whichever the
    engine resolved."""
    model = _MERGE_ENTITY_MODEL.replace(
        "    key: [event_id]\n", "    key: [event_id]\n    scd: type2\n"
    ).replace("      kind: {type: string}\n", "      valid_from: {type: timestamp}\n")
    sources = {
        "entity_model": model,
        "mapping_a": _SRC_A_MAPPING.replace(
            '  kind: {from: "$.type", transform: [to_string]}\n',
            '  valid_from: {from: "$.vf", transform: [{parse_ts: ISO8601}]}\n',
        ),
    }
    with pytest.raises(ResolutionError) as excinfo:
        build_project_ir(load_project(sources))
    assert "carries 'valid_from'" in str(excinfo.value)
    assert excinfo.value.source_path == "entity_model: entities.event.fields"


def test_a_type1_entity_may_carry_one() -> None:
    """The nearest non-trigger: on a current-view dimension the target writes
    no interval, so `valid_from` is an ordinary business column and stays
    legal. Reserving the name everywhere would refuse this."""
    model = _MERGE_ENTITY_MODEL.replace(
        "      kind: {type: string}\n", "      valid_from: {type: timestamp}\n"
    )
    sources = {
        "entity_model": model,
        "mapping_a": _SRC_A_MAPPING.replace(
            '  kind: {from: "$.type", transform: [to_string]}\n',
            '  valid_from: {from: "$.vf", transform: [{parse_ts: ISO8601}]}\n',
        ),
    }
    ir = build_project_ir(load_project(sources))
    assert "valid_from" in {column.name for column in ir.entities[0].columns}
