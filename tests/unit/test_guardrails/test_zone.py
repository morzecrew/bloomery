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

from bloomery import build_project_ir, load_catalog, load_project
from bloomery.errors import GuardrailError, ResolutionError, UndeclaredZone

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


MERGED_NEW_YORK = """
mapping_version: 1
source: us__orders
target: order
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  placed_at:
    from: "$.placed"
    transform: [{parse_ts: ISO8601}, {to_utc: America/New_York}]
  revenue: {from: "$.total"}
"""

MERGED_LONDON = """
mapping_version: 1
source: uk__orders
target: order
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  placed_at:
    from: "$.placed"
    transform: [{parse_ts: ISO8601}, {to_utc: Europe/London}]
    zone_in: Europe/London
  revenue: {from: "$.total"}
"""


def test_two_feeds_on_two_clocks_build_one_canonical_column() -> None:
    """D2's whole argument, run: a canonical `placed_at` fed by a New York feed
    and a London feed runs on two clocks, and each mapping declares its own.

    A declaration on the canonical field could not express this — there is one
    field and two answers — and that is why the key sits on the mapping beside
    `currency_in:` rather than beside `type:`. The two spellings are mixed on
    purpose: the London feed states its clock as well as converting it, which
    is the checked redundancy §5.2 allows, and the New York feed lets `to_utc`
    be the declaration, which is what D4 says it already is.
    """

    marts = CARRIED.replace("flatten: []", "flatten:\n      - {date: placed_at, role: placed}")
    ir = build_project_ir(
        load_project(
            {
                "entity_model": ENTITY_MODEL,
                "mapping_us": MERGED_NEW_YORK,
                "mapping_uk": MERGED_LONDON,
                "marts": marts,
                "metrics": METRICS,
            }
        )
    )

    (entity,) = ir.entities
    zones = {
        source.relation: next(
            field.zone_in for field in source.fields if field.target_field == "placed_at"
        )
        for source in entity.sources
    }

    assert zones == {"uk__orders": "Europe/London", "us__orders": None}
    # One column, two branches of the UNION, and both instants are UTC by the
    # time they meet — which is the thing the rule is protecting and the reason
    # neither branch had to be renamed.
    assert [column.name for column in entity.columns].count("placed_at") == 1


def test_a_feed_whose_zone_disagrees_with_its_own_chain_is_refused_alone() -> None:
    """The cross-check is per mapping, so a merged entity does not hide it: the
    London feed's declaration is checked against the London feed's chain, and
    the New York one is untouched."""

    with pytest.raises(ResolutionError, match="uk__orders|Europe/London"):
        build_project_ir(
            load_project(
                {
                    "entity_model": ENTITY_MODEL,
                    "mapping_us": MERGED_NEW_YORK,
                    "mapping_uk": MERGED_LONDON.replace(
                        "zone_in: Europe/London", "zone_in: America/Chicago"
                    ),
                    "marts": CARRIED,
                    "metrics": METRICS,
                }
            )
        )


# ....................... #
# The hole, pinned


RECIPE_CATALOG = """
catalog_version: 1
vertical: probe
canonical_fields:
  placed_at:
    entity: order
    type: timestamp
    recipes:
      - {id: parsed, requires: [raw_placed], expr: "CAST(raw_placed AS TIMESTAMP)"}
"""

RECIPE_MODEL = """
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      placed_at: {type: timestamp, canonical: placed_at}
      revenue: {type: "decimal(12,2)"}
"""

RECIPE_MAPPING = """
mapping_version: 1
source: shop__orders
target: order
key:
  order_id: {from: "$.order_id", transform: [to_string]}
fields:
  placed_at:
    recipe: parsed
    from: {raw_placed: "$.placed_at"}
  revenue: {from: "$.revenue"}
"""


def test_a_recipe_that_parses_a_timestamp_is_not_reached_by_r018() -> None:
    """**A known hole, pinned rather than hidden** — RFC 0074 §10's fourth
    question, answered by running it (logs/T-0062.md).

    A catalog recipe whose body casts text to a timestamp produces the same
    wall-clock-read-as-UTC this rule exists to refuse, and R018 does not see
    it: the column's chain is empty, so §5.3's third provenance — "was never a
    wall clock" — discharges it. Nothing in the mapping is wrong; the parse is
    in the catalog, where there is no `zone_in:` to write.

    Refusing it here would be a refusal no author could satisfy, which is the
    one kind this design cannot afford. So the behaviour is pinned instead: if
    a later change closes the hole this test fails, and closing it deliberately
    is the point.
    """

    marts = CARRIED.replace("flatten: []", "flatten:\n      - {date: placed_at, role: placed}")
    ir = build_project_ir(
        load_project(
            {
                "entity_model": RECIPE_MODEL,
                "mapping": RECIPE_MAPPING,
                "marts": marts,
                "metrics": METRICS,
            }
        ),
        catalog=load_catalog(RECIPE_CATALOG),
    )

    (entity,) = ir.entities
    (field,) = (
        field
        for source in entity.sources
        for field in source.fields
        if field.target_field == "placed_at"
    )

    # The reason it is not reached, rather than the fact alone: an empty chain
    # is what the provenance test reads, and a recipe never fills one.
    assert field.transform == ()
    assert field.zone_in is None


def test_a_wall_clock_rendered_back_to_text_is_still_compared_as_one() -> None:
    """The case the column's *declared type* would have hidden, and the reason
    the walk reads the chain instead.

    `[{parse_ts: ISO8601}, to_string]` produces a `string` column, and it is
    still the same wall clock — rendering it back to text does not move the
    instant it was read as. Compared to a literal, it falls on the wrong side
    of the same boundary, so R018 asks the same question of it.

    Found by sabotage: filtering the comparison to timestamp-typed columns was
    a branch nothing could kill, because the only inputs it changed the answer
    for were ones the suite did not have.
    """

    entity = ENTITY_MODEL.replace(
        "      placed_at: {type: timestamp}", "      placed_at: {type: string}"
    )
    mapping = MAPPING.replace(
        PARSED, 'placed_at: {from: "$.placed_at", transform: [{parse_ts: ISO8601}, to_string]}'
    )
    metrics = METRICS.replace(
        "    expr: revenue",
        "    expr: \"CASE WHEN placed_at >= '2025-02-01 00:00:00' THEN revenue ELSE 0 END\"",
    )

    (refusal,) = refusals(mapping=mapping, metrics=metrics, entity=entity)

    assert "compares it against a literal instant" in str(refusal)


def test_a_string_column_no_chain_ever_parsed_is_not_refused() -> None:
    """The other side of dropping the type filter: comparing an ordinary string
    column to a literal raises the question and answers it immediately, because
    nothing in that column's chain ever read a clock. The rule stays scoped by
    provenance rather than by the shape of the comparison."""

    metrics = METRICS.replace(
        "    expr: revenue",
        "    expr: \"CASE WHEN channel = 'web' THEN revenue ELSE 0 END\"",
    )
    entity = ENTITY_MODEL.replace(
        "      revenue:", "      channel: {type: string}\n      revenue:"
    )
    mapping = MAPPING.replace(
        '  revenue: {from: "$.revenue"}',
        '  channel: {from: "$.channel"}\n  revenue: {from: "$.revenue"}',
    )

    assert refusals(mapping=mapping, metrics=metrics, entity=entity) == []


# ....................... #
# A cast is not a literal (PR #126)


def test_a_cast_column_compared_to_a_literal_instant_is_refused() -> None:
    """`CAST(placed_at AS TIMESTAMP) >= TIMESTAMP '…'` **is** case 011, written
    with the cast spelled out — and it was passing.

    The cast is how an author spells a column as an instant, so reading every
    instant cast as "the literal side" inverted the rule twice: the column
    under the cast stopped being a column, and the comparison stopped having a
    column to pin. What the literal test now requires is that the cast wrap a
    *literal*.
    """

    metrics = METRICS.replace(
        "    expr: revenue",
        "    expr: \"CASE WHEN CAST(placed_at AS TIMESTAMP) >= TIMESTAMP "
        "'2025-02-01 00:00:00' THEN revenue ELSE 0 END\"",
    )
    (refusal,) = refusals(metrics=metrics)

    assert "compares it against a literal instant" in str(refusal)


def test_a_cast_column_compared_to_another_column_is_not_refused() -> None:
    """The same defect's other half, and the reason it is one defect: with a
    cast reading as a literal, `CAST(placed_at AS TIMESTAMP) = shipped_at`
    demanded a zone for `shipped_at` — a refusal for a comparison that has no
    literal instant in it at all."""

    metrics = METRICS.replace(
        "    expr: revenue",
        '    expr: "CASE WHEN CAST(placed_at AS TIMESTAMP) = shipped_at THEN revenue ELSE 0 END"',
    )

    assert refusals(metrics=metrics) == []


def test_a_column_wrapped_in_a_function_is_still_pinned() -> None:
    """A boundary is as wrong under a `COALESCE` as it is bare, so the column
    is looked for *inside* each operand rather than as the operand itself. This
    is the shape that decides between collecting from the whole comparison and
    collecting only from the non-literal side: here one side carries both a
    column and a literal instant."""

    metrics = METRICS.replace(
        "    expr: revenue",
        "    expr: \"CASE WHEN COALESCE(placed_at, TIMESTAMP '2020-01-01 00:00:00') >= "
        "TIMESTAMP '2025-02-01 00:00:00' THEN revenue ELSE 0 END\"",
    )
    (refusal,) = refusals(metrics=metrics)

    assert "order.placed_at" in str(refusal)
