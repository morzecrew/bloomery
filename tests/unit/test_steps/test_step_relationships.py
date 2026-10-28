"""A relationship may name a step output (#362, S-0034/D-59).

A step output is an entity (S-0034/D-36), and a mart may be built over one, but
a relationship could not point at it: the reference check knew only authored
entities. So a step could compute an attribute of an existing grain, a
customer's segment, and no mart over another entity could flatten it: no
revenue by the buyer's segment.

The name is the spec layer's to check; the columns are the manifest's, so a
``via`` naming a step output is checked where the step lowers, as its
``canonical:`` links are (D49).
"""

from __future__ import annotations

import pytest

from bloomery import Target, build_project_ir, compile_project, load_project
from bloomery.errors import GuardrailError, MissingReference, StepError
from bloomery.ir import ProjectIR
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.unit

ENTITY_MODEL = """spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {{type: string, required: true}}
      customer_id: {{type: string}}
{quality}relationships:
{relationships}"""

MAPPING = (
    "mapping_version: 1\nsource: shop__orders\ntarget: order\n"
    'key:\n  order_id: {from: "$.id"}\n'
    'fields:\n  customer_id: {from: "$.customer_id"}\n'
    "unmapped: ['$._ingested_at', '$._load_id', '$._source_row_id']\n"
)

TO_SEGMENT = (
    "  - name: order_of_segment\n    from: order\n    to: customer_segment\n"
    "    via: {customer_id: customer_id}\n    cardinality: many_to_one\n"
)

STEPS = (
    "steps_version: 1\nsteps:\n  - use: customer_segments@1\n"
    "    inputs: {{orders: {reads}}}\n"
    "    outputs: {{segment: silver.customer_segment}}\n"
)

ORDERS_MART = (
    "marts_version: 1\nmarts:\n  orders:\n    grain: order\n    base: order\n"
    "    flatten:\n      - {via: order_of_segment, prefix: buyer_}\n    measures: []\n"
)

SEGMENTS = StepManifest.model_validate(
    {
        "ref": "customer_segments",
        "version": 1,
        "kind": "sql_model",
        "determinism": "pure",
        "runtime_lock": "sha256:x",
        "inputs": {"orders": {"grain": "order", "requires": ["customer_id"]}},
        "outputs": {
            "segment": {
                "grain": "one row per customer",
                "key": ["customer_id"],
                "produces": {
                    "customer_id": {"type": "string"},
                    "last_order_id": {"type": "string"},
                    "segment": {"type": "string"},
                },
            }
        },
    }
)

BODY = (
    "SELECT customer_id, MAX(order_id) AS last_order_id, "
    "CASE WHEN COUNT(*) > 1 THEN 'repeat' ELSE 'new' END AS segment "
    'FROM silver."order" GROUP BY customer_id'
)

#: A second step, reading the first one's output: the transitive case.
LABELS = StepManifest.model_validate(
    {
        "ref": "segment_labels",
        "version": 1,
        "kind": "sql_model",
        "determinism": "pure",
        "runtime_lock": "sha256:y",
        "inputs": {"segments": {"grain": "customer"}},
        "outputs": {
            "label": {
                "grain": "one row per customer",
                "key": ["customer_id"],
                "produces": {"customer_id": {"type": "string"}, "label": {"type": "string"}},
            }
        },
    }
)

LABELS_WIRING = (
    "  - use: segment_labels@1\n    inputs: {segments: silver.customer_segment}\n"
    "    outputs: {label: silver.customer_label}\n"
)

LABELS_BODY = "SELECT customer_id, UPPER(segment) AS label FROM silver.customer_segment"


def registry() -> StepRegistry:
    return StepRegistry(
        {("customer_segments", 1): SEGMENTS, ("segment_labels", 1): LABELS},
        sql_bodies={("customer_segments", 1): BODY, ("segment_labels", 1): LABELS_BODY},
    )


def documents(
    relationships: str = TO_SEGMENT,
    *,
    marts: str | None = ORDERS_MART,
    quality: str = "",
    reads: str = "silver.order",
    steps: str = "",
) -> dict[str, str]:
    docs = {
        "entity_model": ENTITY_MODEL.format(quality=quality, relationships=relationships),
        "mapping_orders": MAPPING,
        "steps": STEPS.format(reads=reads) + steps,
    }
    if marts is not None:
        docs["marts"] = marts
    return docs


def build(*args: str, **kwargs: str | None) -> ProjectIR:
    return build_project_ir(load_project(documents(*args, **kwargs)), steps=registry())  # type: ignore[arg-type]


# ....................... #
# The relationship, and the mart that flattens it


def test_a_mart_flattens_a_step_output_through_a_relationship() -> None:
    """The issue's case: the order mart carries the buyer's segment."""
    (mart,) = build().marts

    flattened = {c.name: c.source_entity for c in mart.columns if c.name.startswith("buyer_")}
    assert flattened == {
        "buyer_customer_id": "customer_segment",
        "buyer_last_order_id": "customer_segment",
        "buyer_segment": "customer_segment",
    }


def test_a_step_output_may_be_the_dependent_side() -> None:
    """The other direction: a mart over the step output reaches back to an
    authored entity, the segment's last order."""
    back = (
        "  - name: segment_last_order\n    from: customer_segment\n    to: order\n"
        "    via: {last_order_id: order_id}\n    cardinality: many_to_one\n"
    )
    marts = (
        "marts_version: 1\nmarts:\n  segments:\n    grain: customer_segment\n"
        "    base: customer_segment\n"
        "    flatten:\n      - {via: segment_last_order, prefix: last_order_}\n"
        "    measures: []\n"
    )
    (mart,) = build(back, marts=marts).marts

    assert "last_order_order_id" in [c.name for c in mart.columns]


def test_the_emitted_mart_joins_the_relation_the_step_writes() -> None:
    """Run as emitted: the mart's query over the two relations the models
    write, on DuckDB."""
    duckdb = pytest.importorskip("duckdb")
    project = load_project(documents())
    artifacts = compile_project(project, target=Target.SQLMESH, dialect="duckdb", steps=registry())
    model = next(a.content for a in artifacts if a.path == "models/gold/mart_orders.sql")
    query = model.partition(");")[2]

    connection = duckdb.connect()
    connection.execute("CREATE SCHEMA silver")
    connection.execute(
        'CREATE TABLE silver."order" AS SELECT * FROM '
        "(VALUES ('o1', 'c1'), ('o2', 'c1'), ('o3', 'c2'), ('o4', NULL)) AS t(order_id, customer_id)"
    )
    connection.execute(f"CREATE TABLE silver.customer_segment AS {BODY}")
    rows = connection.execute(f"SELECT order_id, buyer_segment FROM ({query}) ORDER BY 1").fetchall()

    assert rows == [("o1", "repeat"), ("o2", "repeat"), ("o3", "new"), ("o4", None)]


def test_dbt_reads_the_step_output_by_ref() -> None:
    project = load_project(documents())
    artifacts = compile_project(project, target=Target.DBT, dialect="duckdb", steps=registry())
    model = next(a.content for a in artifacts if a.path == "models/gold/mart_orders.sql")

    assert "LEFT JOIN {{ ref('customer_segment') }} AS buyer_" in model


# ....................... #
# The columns, checked against the manifest


def test_a_via_column_the_step_does_not_produce_is_refused() -> None:
    relationship = TO_SEGMENT.replace("{customer_id: customer_id}", "{customer_id: buyer_id}")
    with pytest.raises(MissingReference) as excinfo:
        build(relationship)

    assert "unknown column 'buyer_id' of entity 'customer_segment'" in str(excinfo.value)
    assert excinfo.value.source_path == "entity_model: relationships[0].via.customer_id"


def test_both_sides_of_one_relationship_are_reported_together() -> None:
    """The authored side of a relationship to a step output is checked with
    the step side, at lowering: checking it at resolve would report one side,
    and the other only on the author's next run."""
    relationship = TO_SEGMENT.replace("{customer_id: customer_id}", "{buyer: buyer_id}")
    with pytest.raises(StepError) as excinfo:
        build(relationship)

    leaves = sorted(str(leaf) for leaf in excinfo.value.collected)
    assert len(leaves) == 2
    assert "unknown column 'buyer' of entity 'order'" in leaves[0]
    assert "unknown column 'buyer_id' of entity 'customer_segment'" in leaves[1]


def test_a_relationship_to_an_unknown_step_s_output_reports_only_the_step() -> None:
    """Its columns are nobody's to know, so the column check passes it by
    rather than reading a manifest that is not there."""
    from bloomery.errors import UnknownStep

    project = load_project(documents(marts=None))
    with pytest.raises(UnknownStep, match="customer_segments"):
        build_project_ir(project, steps=StepRegistry({}))


def test_a_name_neither_declared_nor_written_is_still_unknown() -> None:
    relationship = TO_SEGMENT.replace("to: customer_segment", "to: customer_tier")
    with pytest.raises(MissingReference, match="unknown entity 'customer_tier'"):
        build(relationship, marts=None)


# ....................... #
# A check inside the dependent's model, of a relation built from it


REFERENTIAL = (
    "    quarantine: {retention: 90d}\n"
    "    quality:\n      - {rule: referential, via: order_of_segment, on_missing: flag}\n"
)

COVERAGE = "coverage:\n  - {name: has_order, relationship: order_of_segment, min: 1, on_fail: flag}\n"


def _refusal(**kwargs: str) -> str:
    with pytest.raises(GuardrailError) as excinfo:
        build(**kwargs)
    (leaf,) = excinfo.value.collected
    return str(leaf)


def test_a_referential_rule_into_a_step_built_from_the_entity_is_refused() -> None:
    """The rule is a LEFT JOIN inside ``order``'s own model, and the step reads
    ``order``: each model would wait on the other."""
    message = _refusal(quality=REFERENTIAL)

    assert "relationship 'order_of_segment'" in message
    assert "step 'customer_segments@1' computes 'customer_segment' from 'order'" in message


def test_a_coverage_check_into_a_step_built_from_the_entity_is_refused() -> None:
    """The audit hangs off ``order``'s model and declares the referenced side
    in its ``depends_on``: the same cycle."""
    message = _refusal(quality=COVERAGE)

    assert "coverage check 'has_order'" in message
    assert "computes 'customer_segment' from 'order'" in message


def test_the_cycle_is_found_through_a_second_step() -> None:
    to_label = TO_SEGMENT.replace("customer_segment", "customer_label")
    referential = REFERENTIAL.replace("order_of_segment", "order_of_label")
    with pytest.raises(GuardrailError) as excinfo:
        build(
            to_label.replace("order_of_segment", "order_of_label"),
            marts=None,
            quality=referential,
            steps=LABELS_WIRING,
        )

    (leaf,) = excinfo.value.collected
    assert "step 'segment_labels@1' computes 'customer_label' from 'order'" in str(leaf)


def test_a_referential_rule_into_a_step_built_from_elsewhere_compiles() -> None:
    """The guard is the cycle, not the step: a segment computed from a relation
    kept outside bloomery is a parent like any other."""
    ir = build(quality=REFERENTIAL, reads="silver.crm_orders")

    (order,) = [entity for entity in ir.entities if entity.name == "order"]
    assert [rule.name for rule in order.quality if "referential" in rule.name] == [
        "order_of_segment_referential"
    ]
