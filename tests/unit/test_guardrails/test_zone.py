"""The zone guard (RFC 0074 §5.3, R018): which uses of an instant demand a
declared clock, and which do not.

The rule's surface *is* the site list, so most of what is asserted here is
where it does **not** fire. A refusal on every timestamp would be a rule
nobody can satisfy without pasting `zone_in: UTC` over a whole project, which
is the outcome §9 names as the risk — and a project full of pasted
declarations carries no more information than one with none.
"""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_project
from bloomery.errors import GuardrailError, UndeclaredZone

pytestmark = pytest.mark.unit

ENTITY_MODEL = """
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      placed_at: {type: timestamp}
      shipped_at: {type: timestamp}
      revenue: {type: "decimal(12,2)"}
"""

PARSED = 'placed_at: {from: "$.placed_at", transform: [{parse_ts: ISO8601}]}'

MAPPING = f"""
mapping_version: 1
source: shop__orders
target: order
key:
  order_id: {{from: "$.order_id", transform: [to_string]}}
fields:
  {PARSED}
  shipped_at: {{from: "$.shipped_at", transform: [{{parse_ts: ISO8601}}]}}
  revenue: {{from: "$.revenue"}}
"""

#: A mart that carries the timestamp as a plain column and buckets nothing by
#: it — the shape R018 must stay silent on.
CARRIED = """
marts_version: 1
marts:
  orders:
    grain: order
    base: order
    measures: [revenue_total]
    flatten: []
"""

METRICS = """
metrics_version: 1
metrics:
  revenue_total:
    grain: order
    additivity: additive
    agg: sum
    expr: revenue
"""


def build(
    *, mapping: str = MAPPING, marts: str = CARRIED, metrics: str = METRICS, entity: str = ""
):
    return build_project_ir(
        load_project(
            {
                "entity_model": entity or ENTITY_MODEL,
                "mapping": mapping,
                "marts": marts,
                "metrics": metrics,
            }
        )
    )


def refusals(**overrides: str) -> list[UndeclaredZone]:
    """Every `UndeclaredZone` leaf of one compile, or none if it compiles."""

    try:
        build(**overrides)
    except GuardrailError as error:
        return [leaf for leaf in error.collected if isinstance(leaf, UndeclaredZone)]

    return []


# ....................... #
# Where it does not fire


def test_a_timestamp_that_is_only_carried_is_not_refused() -> None:
    """§5.3: a value that is projected and never positioned has no boundary to
    fall the wrong side of. This is the common case in any real project, and a
    rule that refused it would be answered by pasting a declaration nobody
    thought about — which is worth less than the silence it replaced."""

    assert refusals() == []


def test_a_date_parsed_as_a_date_is_not_refused() -> None:
    """§4, non-goal: a bare date has no instant to get wrong at a boundary. The
    provenance test is `parse_ts` in the chain rather than the column's type,
    so `parse_date` never raises the question."""

    marts = CARRIED.replace("flatten: []", "flatten:\n      - {date: booked_on, role: booked}")
    entity = ENTITY_MODEL.replace(
        "      revenue:", "      booked_on: {type: date}\n      revenue:"
    )
    mapping = MAPPING.replace(
        '  revenue: {from: "$.revenue"}',
        '  booked_on: {from: "$.booked_on", transform: [{parse_date: ISO8601}]}\n'
        '  revenue: {from: "$.revenue"}',
    )

    assert refusals(mapping=mapping, marts=marts, entity=entity) == []


def test_two_timestamps_compared_with_each_other_are_not_refused() -> None:
    """Neither side is a literal, so there is no instant in some other zone for
    the column to be measured against. Both columns are wall clocks and the
    difference between them is the same number whatever clock they share."""

    metrics = METRICS.replace(
        "    expr: revenue",
        "    expr: \"CASE WHEN shipped_at > placed_at THEN revenue ELSE 0 END\"",
    )

    assert refusals(metrics=metrics) == []


# ....................... #
# The three sites


def test_a_date_role_over_a_parsed_timestamp_is_refused() -> None:
    """Site one: a bucket boundary *is* an instant, so a bucket over a wall
    clock read as UTC puts rows in the wrong bucket — which is the failure with
    every check passing."""

    marts = CARRIED.replace("flatten: []", "flatten:\n      - {date: placed_at, role: placed}")
    (refusal,) = refusals(marts=marts)

    assert "buckets it as the 'placed' date role" in str(refusal)
    assert refusal.source_path == "mapping[shop__orders->order]: fields.placed_at"


def test_a_comparison_against_a_literal_instant_is_refused() -> None:
    """Site two, and the site corpus case 011 actually fails at. The mart here
    flattens nothing, so this is the rule firing where a time-dimension-scoped
    rule would have been silent."""

    metrics = METRICS.replace(
        "    expr: revenue",
        "    expr: \"CASE WHEN placed_at >= TIMESTAMP '2025-02-01 00:00:00' "
        'THEN revenue ELSE 0 END"',
    )
    (refusal,) = refusals(metrics=metrics)

    assert "compares it against a literal instant" in str(refusal)


def test_a_bare_string_literal_compares_the_same_way() -> None:
    """The cast is the engine's to add, so `>= '2025-02-01'` is the same
    comparison with the cast left off — a rule that read only the canonical
    `CAST(… AS TIMESTAMP)` form would be one rewrite away from silent."""

    metrics = METRICS.replace(
        "    expr: revenue",
        "    expr: \"CASE WHEN placed_at >= '2025-02-01 00:00:00' THEN revenue ELSE 0 END\"",
    )

    assert len(refusals(metrics=metrics)) == 1


def test_a_comparison_nested_inside_an_expression_is_found() -> None:
    """The walk is over the whole tree: case 011's comparison sits two levels
    inside a `CASE`, and a rule that read only the top node would pass the
    fixture it was written for."""

    metrics = METRICS.replace(
        "    expr: revenue",
        '    expr: "COALESCE(CASE WHEN (placed_at BETWEEN TIMESTAMP \'2025-02-01 00:00:00\' '
        "AND TIMESTAMP '2025-03-01 00:00:00') THEN revenue END, 0)\"",
    )

    assert len(refusals(metrics=metrics)) == 1


# ....................... #
# One column, one refusal


def test_two_marts_reading_one_column_produce_one_refusal_naming_both() -> None:
    """The fix is a single key on a single field however many readers there
    are, so a refusal per reader would make an author edit one mapping twice
    and read the same sentence twice. The sites are still named: "somewhere its
    position matters" is not something an author can act on."""

    marts = """
marts_version: 1
marts:
  finance:
    grain: order
    base: order
    measures: [revenue_total]
    flatten:
      - {date: placed_at, role: booked}
  ops:
    grain: order
    base: order
    measures: [revenue_total]
    flatten:
      - {date: placed_at, role: shipped}
"""
    (refusal,) = refusals(marts=marts)
    message = str(refusal)

    assert "'booked' date role" in message
    assert "'shipped' date role" in message


# ....................... #
# Declared, by either spelling


@pytest.mark.parametrize(
    "declaration",
    [
        'placed_at: {from: "$.placed_at", transform: [{parse_ts: ISO8601}], zone_in: UTC}',
        'placed_at: {from: "$.placed_at", '
        "transform: [{parse_ts: ISO8601}, {to_utc: America/New_York}]}",
    ],
    ids=["zone_in", "to_utc"],
)
def test_either_declaration_discharges_the_obligation(declaration: str) -> None:
    """The two honest provenances of §5.3, and they are not ranked: a converted
    wall clock and a declared-UTC one are both instants somebody accounted
    for."""

    marts = CARRIED.replace("flatten: []", "flatten:\n      - {date: placed_at, role: placed}")

    assert refusals(mapping=MAPPING.replace(PARSED, declaration), marts=marts) == []


def test_a_column_that_was_never_a_wall_clock_discharges_it() -> None:
    """The third provenance: no `parse_ts` in the chain means the source
    handed over an instant, and there is no clock to name. It is the provenance
    a step output relies on too (D7, decided in logs/T-0062.md)."""

    marts = CARRIED.replace("flatten: []", "flatten:\n      - {date: placed_at, role: placed}")

    assert refusals(mapping=MAPPING.replace(PARSED, 'placed_at: {from: "$.placed_at"}'), marts=marts) == []


# ....................... #
# The as-of anchor, the filter, and the rollup


AS_OF_MODEL = """
spec_version: 1
entities:
  customer:
    grain: one row per customer
    key: [customer_id]
    scd: type2
    fields:
      customer_id: {type: string, required: true}
      segment: {type: string}
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      customer_id: {type: string}
      placed_at: {type: timestamp}
      booked_on: {type: date}
      revenue: {type: "decimal(12,2)"}
relationships:
  - name: order_of_customer
    from: order
    to: customer
    via: {customer_id: customer_id}
    cardinality: many_to_one
"""

AS_OF_MAPPING = f"""
mapping_version: 1
source: shop__orders
target: order
key:
  order_id: {{from: "$.order_id", transform: [to_string]}}
fields:
  customer_id: {{from: "$.customer_id", transform: [to_string]}}
  {PARSED}
  booked_on: {{from: "$.booked_on", transform: [{{parse_date: ISO8601}}]}}
  revenue: {{from: "$.revenue"}}
"""

CUSTOMER_MAPPING = """
mapping_version: 1
source: crm__customers
target: customer
key:
  customer_id: {from: "$.id", transform: [to_string]}
fields:
  segment: {from: "$.segment"}
"""

AS_OF_MARTS = """
marts_version: 1
marts:
  orders:
    grain: order
    base: order
    measures: [revenue_total]
    flatten:
      - {via: order_of_customer, prefix: customer_, as_of: placed_at}
      - {date: booked_on, role: booked}
"""


def test_an_as_of_anchor_over_a_parsed_timestamp_is_refused() -> None:
    """Site three: the version chosen is the one current at an instant, so an
    anchor five hours out reads the wrong version of the dimension — and the
    row it produces is a real row of a real version, which is why nothing
    downstream notices."""

    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(
            load_project(
                {
                    "entity_model": AS_OF_MODEL,
                    "mapping_orders": AS_OF_MAPPING,
                    "mapping_customers": CUSTOMER_MAPPING,
                    "marts": AS_OF_MARTS,
                    "metrics": METRICS,
                }
            )
        )

    (refusal,) = [
        leaf for leaf in excinfo.value.collected if isinstance(leaf, UndeclaredZone)
    ]

    assert "reads 'customer' as of it" in str(refusal)


def test_a_metric_filtered_on_an_instant_is_refused() -> None:
    """The filter half of site two. A `filter:` compares a column against
    authored literals exactly as an expression does — the values reach SQL as
    literals in some zone, and the column is in another."""

    marts = CARRIED.replace(
        "flatten: []", "flatten:\n      - {date: booked_on, role: booked}"
    )
    entity = ENTITY_MODEL.replace(
        "      revenue:", "      booked_on: {type: date}\n      revenue:"
    )
    mapping = MAPPING.replace(
        '  revenue: {from: "$.revenue"}',
        '  booked_on: {from: "$.booked_on", transform: [{parse_date: ISO8601}]}\n'
        '  revenue: {from: "$.revenue"}',
    )
    metrics = METRICS + """    filter:
      - {dimension: placed_at, op: gte, values: ["2025-02-01 00:00:00"]}
"""

    (refusal,) = refusals(mapping=mapping, marts=marts, metrics=metrics, entity=entity)

    assert "filters on it by a literal instant" in str(refusal)


def test_a_rollup_keeping_a_bucket_over_a_parsed_timestamp_is_refused() -> None:
    """A rollup's kept time column is a date role one relation on: the rollup
    groups by the bucket the parent computed, so a boundary that was wrong in
    the mart is wrong in every row of the rollup, aggregated."""

    marts = """
marts_version: 1
marts:
  orders:
    grain: order
    base: order
    measures: [revenue_total]
    flatten:
      - {date: placed_at, role: placed}
rollups:
  orders_monthly:
    of: orders
    keep: [placed_month]
    measures: [revenue_total]
"""
    (refusal,) = refusals(marts=marts)
    message = str(refusal)

    assert "rollup 'orders_monthly' keeps it as a bucket" in message
    assert "mart 'orders' buckets it as the 'placed' date role" in message


# ....................... #
# A merged entity answers per mapping


MERGED_LEGACY = """
mapping_version: 1
source: legacy__orders
target: order
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  placed_at: {from: "$.placed", transform: [{parse_ts: ISO8601}]}
  revenue: {from: "$.total"}
"""


def test_only_the_mapping_that_declared_nothing_is_blamed() -> None:
    """The reason the answer is per source (§5.4's shape, one RFC over): a
    merged entity is built from several mappings, and sending the author of the
    one that *did* declare to fix something would cost the refusal its
    credibility — there is nothing to change in that file.
    """

    marts = CARRIED.replace("flatten: []", "flatten:\n      - {date: placed_at, role: placed}")
    declared = MAPPING.replace(
        PARSED,
        'placed_at: {from: "$.placed_at", transform: [{parse_ts: ISO8601}], zone_in: UTC}',
    )

    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(
            load_project(
                {
                    "entity_model": ENTITY_MODEL,
                    "mapping_shop": declared,
                    "mapping_legacy": MERGED_LEGACY,
                    "marts": marts,
                    "metrics": METRICS,
                }
            )
        )

    (refusal,) = [
        leaf for leaf in excinfo.value.collected if isinstance(leaf, UndeclaredZone)
    ]
    message = str(refusal)

    assert "'legacy__orders'" in message
    assert "shop__orders" not in message
    assert refusal.source_path == "mapping[legacy__orders->order]: fields.placed_at"
