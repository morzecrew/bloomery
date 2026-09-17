"""R019, the row-set obligation on a ratio (RFC 0075).

R012 is about *how* a ratio is rebuilt and says nothing about which rows belong
in it, which is why corpus case 009 satisfies it exactly and answers `4.00`
where the answer is `3.00`. This is the neighbouring question, and most of what
is asserted here is what **discharges** it: the rule's value is that every
discharge is an author having stated a reading, so a discharge that fires
without one would be the defect wearing a proof.
"""

from __future__ import annotations

import pytest

import pathlib

from bloomery import build_project_ir, load_catalog, load_project
from bloomery.resolve import pipeline
from support.compiling import fixture_sources
from support.planning import variant_ir
from bloomery.errors import GuardrailError, RatioOperandsDisagree, UndeclaredRatioRows
from bloomery.semantic import RULES, Proof, Refutation, prove_ratio_rows
from bloomery.ir import OnFail
from bloomery.semantic.additivity import (
    _REMOVING,
    RatioRowsRefusal,
    _dimension_source,
)

pytestmark = pytest.mark.unit

ENTITY_MODEL = """
spec_version: 1
entities:
  shipment:
    grain: one row per shipment
    key: [shipment_id]
    fields:
      shipment_id: {type: string, required: true}
      carrier_cost: {type: "decimal(12,2)", required: true}
      parcels: {type: int, required: true}
      crates: {type: int, required: true}
      shipped_on: {type: date, required: true}
      note: {type: string}
"""

MAPPING = """
mapping_version: 1
source: carrier__shipments
target: shipment
key:
  shipment_id: {from: "$.id", transform: [to_string]}
fields:
  carrier_cost: {from: "$.cost"}
  parcels: {from: "$.parcels", transform: [to_int]}
  crates: {from: "$.crates", transform: [to_int]}
  shipped_on: {from: "$.shipped_on", transform: [{parse_date: ISO8601}]}
  note: {from: "$.note"}
"""

MARTS = """
marts_version: 1
marts:
  shipments:
    grain: shipment
    base: shipment
    measures: [carrier_cost, parcels]
    flatten:
      - {date: shipped_on, role: shipped}
"""

#: The ratio as case 009 declares it: correct by every rule that existed before
#: R019, and wrong.
METRICS = """
metrics_version: 1
metrics:
  carrier_cost:
    grain: shipment
    additivity: additive
    agg: sum
    expr: "carrier_cost"
  parcels:
    grain: shipment
    additivity: additive
    agg: sum
    expr: "parcels"
  cost_per_parcel:
    grain: shipment
    additivity: ratio
    ratio: {numerator: carrier_cost, denominator: parcels}
"""

EXCLUDES_ZERO = """
    filter:
      - {dimension: parcels, op: gt, values: [0]}
"""


def build(*, metrics: str = METRICS, entity: str = ENTITY_MODEL, mapping: str = MAPPING):
    return build_project_ir(
        load_project(
            {"entity_model": entity, "mapping": mapping, "marts": MARTS, "metrics": metrics}
        )
    )


def answer(metrics: str = METRICS, **kwargs: str) -> Proof | Refutation:
    """R019's own answer, asked of the draft the guard asks it of.

    Built through `build_project_ir` rather than by hand so the facts the rule
    reads are the ones a project really produces — a hand-built `MetricIR` is
    where a rule and its inputs come to disagree without a test noticing.

    A project the rule *refuses* never finishes building, so the draft is taken
    from the stage before the guardrails: `pipeline` hands back what it had
    when it stopped, which is exactly the IR the guard was reading.
    """

    project = load_project(
        {
            "entity_model": kwargs.get("entity", ENTITY_MODEL),
            "mapping": kwargs.get("mapping", MAPPING),
            "marts": MARTS,
            "metrics": metrics,
        }
    )
    ir = _drafted(project)
    (ratio,) = (metric for metric in ir.metrics if metric.ratio is not None)

    return prove_ratio_rows(ratio, ir)


def _drafted(project, catalog=None):
    """The draft as the guardrail stage received it, refused or not.

    `StageProgress` carries what analysis had produced *before* the stage it is
    yielded with, and never narrows — so the last one holding an IR is the IR
    the guardrails read (RFC 0022 D3).
    """

    drafted = None

    try:
        for _stage, progress in pipeline(project, catalog):
            drafted = progress.ir if progress.ir is not None else drafted
    except GuardrailError:
        pass

    assert drafted is not None, "the pipeline produced no IR to ask about"

    return drafted


# ....................... #


def test_r019_is_in_the_registry() -> None:
    assert "R019" in RULES
    assert "one row set" in RULES["R019"].summary


def test_an_undeclared_row_set_is_refuted() -> None:
    """Case 009's shape: a summed denominator that can be zero on a row, no
    restriction, no range rule, no declaration."""

    with pytest.raises(GuardrailError) as excinfo:
        build()

    (refusal,) = excinfo.value.collected

    assert isinstance(refusal, UndeclaredRatioRows)
    assert refusal.source_path == "metrics: metrics.cost_per_parcel"
    message = str(refusal)
    # Both readings, in the order the RFC fixes: a refusal that names one of
    # two legitimate answers pushes every author toward it.
    assert message.index("op: gt") < message.index("includes_zero_denominator")
    assert "range, min: 1, on_fail: quarantine" in message


def test_restricting_both_operands_discharges_it() -> None:
    """The first reading, and the one case 009's own `restricted` arm uses."""

    metrics = METRICS.replace('    expr: "carrier_cost"\n', f'    expr: "carrier_cost"{EXCLUDES_ZERO}')
    metrics = metrics.replace('    expr: "parcels"\n', f'    expr: "parcels"{EXCLUDES_ZERO}')
    proof = answer(metrics)

    assert isinstance(proof, Proof)
    assert proof.rule == "R019"
    (fact,) = proof.facts
    assert "not zero" in fact.statement


def test_declaring_the_inclusive_reading_discharges_it() -> None:
    """The second reading: `4.00` reachable by an author who means it, and by
    nobody who has not thought about it (D2)."""

    proof = answer(
        METRICS.replace(
            "ratio: {numerator: carrier_cost, denominator: parcels}",
            "ratio: {numerator: carrier_cost, denominator: parcels, "
            "includes_zero_denominator: true}",
        )
    )

    assert isinstance(proof, Proof)
    (fact,) = proof.facts
    assert "include rows whose parcels is zero" in fact.statement


@pytest.mark.parametrize("disposition", ["quarantine", "fail"])
def test_a_range_rule_that_removes_the_row_discharges_it(disposition: str) -> None:
    """The third: asserted once on the field, for every metric over it.

    Both removing dispositions, because what makes the premise true is that the
    row leaves the relation — and a rule that held for one of them would be a
    rule that reads `quarantine` as a synonym rather than as a disposition.
    """

    mapping = MAPPING.replace(
        '  parcels: {from: "$.parcels", transform: [to_int]}',
        '  parcels:\n    from: "$.parcels"\n    transform: [to_int]\n'
        f"    quality:\n      - {{rule: range, min: 1, on_fail: {disposition}}}",
    )
    proof = answer(mapping=mapping)

    assert isinstance(proof, Proof)
    (fact,) = proof.facts
    assert "declares positive" in fact.statement
    assert disposition in fact.statement


def test_a_flagged_rule_does_not_discharge_it() -> None:
    """D3: the disposition is the premise, not the rule's presence.

    A flagged row stays in the relation, so a `range` rule at that disposition
    asserts nothing about what the ratio sums — and reading the rule alone
    would be a proof that is true of a project where the rows are still there.
    """

    mapping = MAPPING.replace(
        '  parcels: {from: "$.parcels", transform: [to_int]}',
        '  parcels:\n    from: "$.parcels"\n    transform: [to_int]\n'
        "    quality:\n      - {rule: range, min: 1, on_fail: flag}",
    )
    refutation = answer(mapping=mapping)

    assert isinstance(refutation, Refutation)
    assert refutation.reason == RatioRowsRefusal.UNDECLARED_ROWS.value


def test_every_disposition_is_classified_and_only_two_remove_the_row() -> None:
    """The vocabulary, not the two members the tests above reach.

    `repair` is the one that would otherwise slip: it leaves the row in place
    with a value this rule cannot bound — its recipe is a Tier 1 macro and its
    fallback is whatever the author wrote — so it belongs with `flag` and not
    with the removing pair. A member added to `OnFail` and not considered here
    would silently join whichever side the code happened to fall on, which is
    the failure a catch-all over a shared enum always has.
    """

    assert _REMOVING == {OnFail.QUARANTINE, OnFail.FAIL}
    assert set(OnFail) - _REMOVING == {OnFail.FLAG, OnFail.REPAIR}


def test_operands_restricted_differently_are_refused_on_the_other_leg() -> None:
    """The second leg, which is a different bug: a quotient of two quantities
    about different row sets is not a rate of anything, zeros or no zeros."""

    metrics = METRICS.replace('    expr: "parcels"\n', f'    expr: "parcels"{EXCLUDES_ZERO}')

    with pytest.raises(GuardrailError) as excinfo:
        build(metrics=metrics)

    (refusal,) = excinfo.value.collected

    assert isinstance(refusal, RatioOperandsDisagree)
    assert "restricted by nothing" in str(refusal)


def test_the_same_restriction_in_two_orders_is_one_restriction() -> None:
    """§5.2's identity is over the *canonical* restriction, and the IR is not
    canonical here: `filter:` keeps authored order on purpose, because the
    clauses are ANDed and the order is load-bearing in the artifact bytes. So
    the rule canonicalises for itself, and this is the test that says so.
    """

    numerator = """
    filter:
      - {dimension: parcels, op: gt, values: [0]}
      - {dimension: note, op: ne, values: ["void"]}
"""
    denominator = """
    filter:
      - {dimension: note, op: ne, values: ["void"]}
      - {dimension: parcels, op: gt, values: [0]}
"""
    metrics = METRICS.replace('    expr: "carrier_cost"\n', f'    expr: "carrier_cost"{numerator}')
    metrics = metrics.replace('    expr: "parcels"\n', f'    expr: "parcels"{denominator}')
    marts = MARTS.replace(
        "    measures: [carrier_cost, parcels]",
        "    measures: [carrier_cost, parcels]\n    flatten:\n"
        "      - {date: shipped_on, role: shipped}",
    )

    assert isinstance(answer(metrics), Proof), marts


def test_a_count_over_a_required_column_discharges_it() -> None:
    """The discharge the RFC does not list, and without which the rule refuses
    `revenue / order_count` — the most common correct ratio there is.

    `COUNT(expr)` counts the rows where `expr` is not null, so a count over a
    column that cannot be null counts *every* row of the set: a row that
    contributes to the numerator contributes 1 to the denominator by
    construction, and there is nothing for an author to declare
    (logs/T-0063.md).
    """

    metrics = METRICS.replace(
        '  parcels:\n    grain: shipment\n    additivity: additive\n    agg: sum\n'
        '    expr: "parcels"\n',
        '  parcels:\n    grain: shipment\n    additivity: additive\n    agg: count\n'
        '    expr: "shipment_id"\n',
    )
    proof = answer(metrics)

    assert isinstance(proof, Proof)
    (fact,) = proof.facts
    assert "counts every row" in fact.statement


def test_a_count_over_a_nullable_column_does_not_discharge_it() -> None:
    """The premise is the column's nullability, not the aggregate's name.

    `COUNT(note)` skips the rows where `note` is null, so a shipment with no
    note contributes cost to the numerator and nothing to the denominator —
    which is this rule's own bug, reached through the aggregate that usually
    rules it out.
    """

    metrics = METRICS.replace(
        '  parcels:\n    grain: shipment\n    additivity: additive\n    agg: sum\n'
        '    expr: "parcels"\n',
        '  parcels:\n    grain: shipment\n    additivity: additive\n    agg: count\n'
        '    expr: "note"\n',
    )
    refutation = answer(metrics)

    assert isinstance(refutation, Refutation)
    assert refutation.reason == RatioRowsRefusal.UNDECLARED_ROWS.value


def test_a_distinct_count_over_a_required_column_discharges_it() -> None:
    """A distinct count is at least one over any non-empty row set, so there is
    no zero-denominator row to declare anything about.

    It was excluded once, on the grounds that a distinct count is about the
    group rather than the row — true, and not the premise. What R019 refuses is
    a denominator whose *per-row* contribution can be zero while the
    numerator's is not, which is a property of a sum over a numeric column
    (logs/T-0063.md, attempt 2).
    """

    metrics = METRICS.replace(
        '  parcels:\n    grain: shipment\n    additivity: additive\n    agg: sum\n'
        '    expr: "parcels"\n',
        '  parcels:\n    grain: shipment\n    additivity: distinct_count\n'
        '    agg: count_distinct\n    expr: "shipment_id"\n',
    )
    proof = answer(metrics)

    assert isinstance(proof, Proof)
    (fact,) = proof.facts
    assert "counts every row" in fact.statement


def test_an_expression_that_is_not_a_column_discharges_nothing() -> None:
    """`parcels * 2` has no single field to carry a range rule and no column to
    count, so both structural discharges are unavailable rather than guessed
    at. The author still has the two declarations."""

    metrics = METRICS.replace('    expr: "parcels"\n', '    expr: "parcels * 2"\n')
    refutation = answer(metrics)

    assert isinstance(refutation, Refutation)
    assert refutation.reason == RatioRowsRefusal.UNDECLARED_ROWS.value


def test_one_restriction_under_two_mart_names_is_one_restriction() -> None:
    """Leg 2 compares what a dimension *resolves to*, not what it is called.

    The flattener prefixes a joined column, so one order-level `region` is
    `region` on the orders mart and `order_region` on the order-items mart. A
    ratio spanning both, restricted to the same rows, carries two spellings —
    and comparing spellings would refuse exactly the cross-mart ratios whose
    operands are most likely to be restricted at all (logs/T-0063.md).
    """

    ir = variant_ir(
        "cross_mart_branches",
        metrics=(
            (
                "  line_discount:\n    grain: order_item\n",
                "  line_discount:\n    grain: order_item\n"
                "    filter:\n      - {dimension: order_region, op: eq, values: ['EU']}\n",
            ),
            (
                "  shipping_count:\n    grain: order\n",
                "  shipping_count:\n    grain: order\n"
                "    filter:\n      - {dimension: region, op: eq, values: ['EU']}\n",
            ),
        ),
    )
    (ratio,) = (metric for metric in ir.metrics if metric.ratio is not None)

    assert isinstance(prove_ratio_rows(ratio, ir), Proof)


def test_two_restrictions_that_resolve_differently_still_disagree() -> None:
    """The other side of the same resolution: `region` and `tier` are two
    columns however they are spelled, so the leg still refuses. A comparison
    that resolved everything to the same thing would be a check that passes."""

    sources = dict(fixture_sources("cross_mart_branches"))
    sources["metrics"] = sources["metrics"].replace(
        "  line_discount:\n    grain: order_item\n",
        "  line_discount:\n    grain: order_item\n"
        "    filter:\n      - {dimension: order_region, op: eq, values: ['EU']}\n",
    ).replace(
        "  shipping_count:\n    grain: order\n",
        "  shipping_count:\n    grain: order\n"
        "    filter:\n      - {dimension: customer_tier, op: eq, values: ['EU']}\n",
    )
    catalog = load_catalog(
        (pathlib.Path("tests/fixtures/cross_mart_branches/catalog.yaml")).read_text()
    )
    ir = _drafted(load_project(sources), catalog)
    (ratio,) = (metric for metric in ir.metrics if metric.ratio is not None)
    refutation = prove_ratio_rows(ratio, ir)

    assert isinstance(refutation, Refutation)
    assert refutation.reason == RatioRowsRefusal.OPERANDS_DISAGREE.value


@pytest.mark.parametrize(
    ("clause", "discharges"),
    [
        ("{dimension: parcels, op: gt, values: [0]}", True),
        ("{dimension: parcels, op: gt, values: [1]}", True),
        ("{dimension: parcels, op: gte, values: [1]}", True),
        ("{dimension: parcels, op: gte, values: [0]}", False),
        ("{dimension: parcels, op: eq, values: [2]}", True),
        ("{dimension: parcels, op: eq, values: [0]}", False),
        ("{dimension: parcels, op: ne, values: [0]}", True),
        ("{dimension: parcels, op: ne, values: [7]}", False),
        ("{dimension: parcels, op: not_in, values: [0, 1]}", True),
        ("{dimension: parcels, op: not_in, values: [1, 2]}", False),
        ("{dimension: parcels, op: in, values: [1, 2]}", True),
        ("{dimension: parcels, op: in, values: [0, 1]}", False),
        ("{dimension: parcels, op: lt, values: [5]}", False),
        ("{dimension: parcels, op: lte, values: [5]}", False),
        ("{dimension: note, op: is_null, values: [false]}", False),
        ('{dimension: parcels, op: ne, values: ["many"]}', False),
    ],
)
def test_which_restrictions_are_read_as_excluding_a_zero(clause: str, discharges: bool) -> None:
    """The operator table, exhaustively, because a restriction the compiler
    reads *wrongly* is worse than one it cannot read at all.

    `>= 0` and `!= 7` are the two that look like they exclude a zero and do
    not; `lt`/`lte` can only exclude one by admitting negatives, which is a
    worse version of this bug and out of scope (§8); `is_null` is about nulls,
    which is a counting denominator's question rather than a summed one's.
    """

    restriction = f"\n    filter:\n      - {clause}\n"
    metrics = METRICS.replace('    expr: "carrier_cost"\n', f'    expr: "carrier_cost"{restriction}')
    metrics = metrics.replace('    expr: "parcels"\n', f'    expr: "parcels"{restriction}')

    assert isinstance(answer(metrics), Proof if discharges else Refutation)


def test_a_restriction_on_another_column_does_not_discharge_it() -> None:
    """The restriction has to be about the *denominator's* column.

    Both operands restricted the same way satisfies leg 2, and a filter on
    `note` says nothing about whether `parcels` is zero — so leg 1 still asks.
    Found by sabotage: dropping the column match broke no test.
    """

    # A zero-excluding restriction on a *different* numeric column: it reads as
    # one of the shapes the operator table admits, and says nothing about
    # `parcels`. Found by sabotage — with the column match dropped, this is the
    # project that wrongly discharges.
    restriction = "\n    filter:\n      - {dimension: crates, op: gt, values: [0]}\n"
    metrics = METRICS.replace('    expr: "carrier_cost"\n', f'    expr: "carrier_cost"{restriction}')
    metrics = metrics.replace('    expr: "parcels"\n', f'    expr: "parcels"{restriction}')
    refutation = answer(metrics)

    assert isinstance(refutation, Refutation)
    assert refutation.reason == RatioRowsRefusal.UNDECLARED_ROWS.value


def test_a_range_rule_of_min_zero_does_not_discharge_it() -> None:
    """`min: 0` admits the zero it would have to exclude. The bound has to be
    *above* zero, and `>= 0` is the most natural thing to write for a count of
    things — which is why this is the boundary worth pinning."""

    mapping = MAPPING.replace(
        '  parcels: {from: "$.parcels", transform: [to_int]}',
        '  parcels:\n    from: "$.parcels"\n    transform: [to_int]\n'
        "    quality:\n      - {rule: range, min: 0, on_fail: quarantine}",
    )
    refutation = answer(mapping=mapping)

    assert isinstance(refutation, Refutation)
    assert refutation.reason == RatioRowsRefusal.UNDECLARED_ROWS.value


def test_a_boolean_filter_value_is_not_read_as_a_number() -> None:
    """`False == 0` in Python, so a `ne: [false]` clause would otherwise read as
    "not zero" and discharge a premise nobody stated. The values a filter
    carries are text, ints and bools (RFC 0034 D8), and only the first two are
    numbers."""

    restriction = "\n    filter:\n      - {dimension: parcels, op: ne, values: [false]}\n"
    metrics = METRICS.replace('    expr: "carrier_cost"\n', f'    expr: "carrier_cost"{restriction}')
    metrics = metrics.replace('    expr: "parcels"\n', f'    expr: "parcels"{restriction}')
    refutation = answer(metrics)

    assert isinstance(refutation, Refutation)
    assert refutation.reason == RatioRowsRefusal.UNDECLARED_ROWS.value


def test_one_set_valued_restriction_written_in_two_orders_is_one_restriction() -> None:
    """The values inside a clause are canonicalised too, not only the clauses.

    `in: [1, 2]` and `in: [2, 1]` admit the same rows, and the IR keeps each as
    written because the bytes differ. Leg 2 compares what they mean.
    """

    numerator = "\n    filter:\n      - {dimension: parcels, op: in, values: [1, 2]}\n"
    denominator = "\n    filter:\n      - {dimension: parcels, op: in, values: [2, 1]}\n"
    metrics = METRICS.replace('    expr: "carrier_cost"\n', f'    expr: "carrier_cost"{numerator}')
    metrics = metrics.replace('    expr: "parcels"\n', f'    expr: "parcels"{denominator}')

    assert isinstance(answer(metrics), Proof)


def test_a_denominator_with_no_measure_of_its_own_is_refused() -> None:
    """§8 names ratios of ratios as the next question and does not answer it.

    What this pins is the answer the rule gives meanwhile: a denominator that
    is a computed metric has no expression to trace to a field, so neither
    structural discharge is available and the author is asked for a
    declaration. Refusing is the conservative end of an undesigned question,
    and it is reachable by an author, so it is pinned rather than left to be
    discovered.
    """

    metrics = METRICS.replace(
        '  parcels:\n    grain: shipment\n    additivity: additive\n    agg: sum\n'
        '    expr: "parcels"\n',
        '  parcels:\n    grain: shipment\n    additivity: additive\n    agg: sum\n'
        '    expr: "parcels"\n'
        "  parcels_computed:\n    additivity: non_additive\n    derived:\n"
        '      expr: "p * 1"\n      inputs:\n        p: {metric: parcels}\n',
    ).replace("denominator: parcels}", "denominator: parcels_computed}")
    refutation = answer(metrics)

    assert isinstance(refutation, Refutation)
    assert refutation.reason == RatioRowsRefusal.UNDECLARED_ROWS.value
    # Named by the metric, because there is no column to name.
    assert "parcels_computed" in str(refutation.obligations[0].required)


def test_a_counted_expression_that_is_not_a_column_discharges_nothing() -> None:
    """The counting discharge needs a *column* to ask about nullability, and
    `COUNT(parcels * 2)` has none — an expression can be null for reasons no
    field declares, so the premise is unavailable rather than assumed."""

    metrics = METRICS.replace(
        '  parcels:\n    grain: shipment\n    additivity: additive\n    agg: sum\n'
        '    expr: "parcels"\n',
        '  parcels:\n    grain: shipment\n    additivity: additive\n    agg: count\n'
        '    expr: "parcels * 2"\n',
    )
    refutation = answer(metrics)

    assert isinstance(refutation, Refutation)
    assert refutation.reason == RatioRowsRefusal.UNDECLARED_ROWS.value


def test_a_ratio_naming_an_operand_that_does_not_exist_is_left_to_r012() -> None:
    """Two rules must not claim one defect.

    A ratio whose denominator names nothing is already reported where it
    belongs — the metric is unreachable, and R012 refuses the reconstruction
    with the message written for it. R019 stays silent rather than adding a
    second leaf telling the author to declare a row set for a metric that is
    not there.
    """

    metrics = METRICS.replace("denominator: parcels}", "denominator: nowhere}")

    assert build(metrics=metrics) is not None


def test_an_expression_naming_no_column_of_the_entity_resolves_to_nothing() -> None:
    """The membership half of the origin lookup, which is not decoration.

    `parse_one("parcels * 2").name` is the empty string and `parse_one("SUM(x)")`
    reports `x`, so a check that stopped at "is this an `exp.Column`" would let
    a compound expression resolve to whatever name SQLGlot surfaced. The
    membership test is what makes the answer *this entity's column or nothing*,
    and it is reachable: an expression naming a column the entity does not
    declare reaches R019 before any other guard refuses it.
    """

    metrics = METRICS.replace('    expr: "parcels"\n', '    expr: "nonexistent_column"\n')
    refutation = answer(metrics)

    assert isinstance(refutation, Refutation)
    # Named by the metric, because the expression resolved to no column.
    assert "'parcels'" in str(refutation.obligations[0].required)


AMBIGUOUS_MODEL = """
spec_version: 1
entities:
  shipment:
    grain: one row per shipment
    key: [shipment_id]
    fields:
      shipment_id: {type: string, required: true}
      carrier_id: {type: string}
      depot_id: {type: string}
      carrier_cost: {type: "decimal(12,2)", required: true}
      parcels: {type: int, required: true}
      shipped_on: {type: date, required: true}
  carrier:
    grain: one row per carrier
    key: [carrier_id]
    fields:
      carrier_id: {type: string, required: true}
      tier: {type: string}
  depot:
    grain: one row per depot
    key: [depot_id]
    fields:
      depot_id: {type: string, required: true}
      tier: {type: string}
relationships:
  - name: shipment_of_carrier
    from: shipment
    to: carrier
    via: {carrier_id: carrier_id}
    cardinality: many_to_one
  - name: shipment_of_depot
    from: shipment
    to: depot
    via: {depot_id: depot_id}
    cardinality: many_to_one
"""


def test_a_dimension_name_two_marts_spell_over_two_columns_resolves_to_both() -> None:
    """Two same-grain marts may flatten *different* entities under one prefix,
    and then one dimension name means two columns.

    Resolving it to whichever mart sorted last made two restrictions that mean
    different things compare equal — a ratio accepted over operands about
    different row sets, which is the defect this leg exists to refuse. The
    identity is what the name can mean for this metric, so two operands agree
    exactly when every mart that can answer them agrees (PR #127).
    """

    sources = {
        "entity_model": AMBIGUOUS_MODEL,
        "mapping": """
mapping_version: 1
source: carrier__shipments
target: shipment
key:
  shipment_id: {from: "$.id", transform: [to_string]}
fields:
  carrier_id: {from: "$.carrier", transform: [to_string]}
  depot_id: {from: "$.depot", transform: [to_string]}
  carrier_cost: {from: "$.cost"}
  parcels: {from: "$.parcels", transform: [to_int]}
  shipped_on: {from: "$.shipped_on", transform: [{parse_date: ISO8601}]}
""",
        "mapping_carrier": """
mapping_version: 1
source: carrier__carriers
target: carrier
key:
  carrier_id: {from: "$.id", transform: [to_string]}
fields:
  tier: {from: "$.tier"}
""",
        "mapping_depot": """
mapping_version: 1
source: carrier__depots
target: depot
key:
  depot_id: {from: "$.id", transform: [to_string]}
fields:
  tier: {from: "$.tier"}
""",
        "marts": """
marts_version: 1
marts:
  by_carrier:
    grain: shipment
    base: shipment
    measures: [carrier_cost, parcels]
    flatten:
      - {via: shipment_of_carrier, prefix: via_}
      - {date: shipped_on, role: shipped}
  by_depot:
    grain: shipment
    base: shipment
    measures: [carrier_cost, parcels]
    flatten:
      - {via: shipment_of_depot, prefix: via_}
      - {date: shipped_on, role: shipped}
""",
        "metrics": METRICS.replace(
            '    expr: "parcels"\n',
            '    expr: "parcels"\n'
            "    filter:\n      - {dimension: via_tier, op: eq, values: ['gold']}\n",
        )
        .replace(
            '    expr: "carrier_cost"\n',
            '    expr: "carrier_cost"\n'
            "    filter:\n      - {dimension: via_tier, op: eq, values: ['gold']}\n",
        )
        .replace(
            "ratio: {numerator: carrier_cost, denominator: parcels}",
            "ratio: {numerator: carrier_cost, denominator: parcels, "
            "includes_zero_denominator: true}",
        ),
    }
    ir = _drafted(load_project(sources))
    (parcels,) = (metric for metric in ir.metrics if metric.name == "parcels")

    assert _dimension_source(parcels, ir)["via_tier"] == "carrier.tier|depot.tier"
