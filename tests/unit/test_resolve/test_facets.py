"""The delta vocabulary (RFC 0064 §5.1, §6).

Two claims run through every test here and neither is about a particular
facet. The first is **totality**: §9's opening risk is a facet list that is a
closed world and therefore wrong, and under this design an unattributed field
is not merely unlabelled — the facets decide what a change *is*, so a field
landing nowhere is a change reported as no change. The second is that
**identity is not definition**: a pure rename must attribute nothing (§6), and
that holds because three field names belong to no facet rather than because
any particular arm remembers to blank one.

The records are hand-built where a claim is about one field and taken from the
corpus where the claim is about the table's coverage. A hand-built record
cannot tell you the table covers what real projects produce, and a fixture
sweep cannot tell you what a single field does.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from bloomery import SpecVersion
from bloomery.errors import GuardrailError, InvariantViolated
from bloomery.ir import (
    Additivity,
    ColumnIR,
    EntityIR,
    ExposureIR,
    ExposureKind,
    Materialization,
    MartIR,
    MetricFilterIR,
    MetricIR,
    RollupIR,
    SCDKind,
    SourceColumnIR,
    SqlExpr,
    StepIR,
    Unit,
    UnreachableMetric,
)
from bloomery.resolve.facets import (
    Facet,
    FacetDelta,
    _FACETS,  # pyright: ignore[reportPrivateUsage]
    _flatten,  # pyright: ignore[reportPrivateUsage]
    _IDENTITY,  # pyright: ignore[reportPrivateUsage]
    _render,  # pyright: ignore[reportPrivateUsage]
    facets,
)
from bloomery.resolve.graph import NodeKind
from bloomery.resolve.timeline import (
    _compile,  # pyright: ignore[reportPrivateUsage]
    _definition,  # pyright: ignore[reportPrivateUsage]
    _kind_and_spelling,  # pyright: ignore[reportPrivateUsage]
)
from bloomery.spec.catalog import CanonicalField
from bloomery.typing import parse_type
from support.compiling import load_fixture, spec_fixture_names
from support.steps import registry_for

pytestmark = pytest.mark.unit


#: Every record `_definition` can return, as classes rather than as names, so
#: that a field added to one of them is enumerated here without this list being
#: edited. Pinned against `_FACETS`'s own keys below in both directions: a
#: record the table describes and this list omits is a row nothing checks, and
#: a record this list carries and the table omits is a kind whose every field
#: would raise.
COMPARABLE = (
    MetricIR,
    UnreachableMetric,
    MartIR,
    RollupIR,
    ExposureIR,
    StepIR,
    EntityIR,
    ColumnIR,
    SourceColumnIR,
    CanonicalField,
)


def metric(**overrides: object) -> MetricIR:
    """A minimal metric, varied along one field at a time."""

    base: dict[str, object] = {
        "name": "gross_revenue",
        "grain": "order",
        "additivity": Additivity.ADDITIVE,
        "agg": "sum",
        "expr": SqlExpr(sql="amount"),
        "ratio": None,
        "semi_additive": None,
        "depends_on": ("order.amount",),
    }
    return MetricIR(**{**base, **overrides})  # type: ignore[arg-type]


# ....................... #
# Totality (§9, D6)


def test_the_table_and_the_comparable_records_are_one_list() -> None:
    """The table is keyed by record type, so it and the set of records that
    reach it have to agree — in both directions.

    A record in the table and not in `_definition`'s output is a row nothing
    can reach; a record `_definition` returns and the table omits raises on
    every field it has. Neither is visible from reading one of the two.
    """
    assert {record for record, _field in _FACETS} == {one.__name__ for one in COMPARABLE}


@pytest.mark.parametrize("record", COMPARABLE, ids=lambda one: one.__name__)
def test_every_field_of_every_comparable_record_has_a_facet(record: type) -> None:
    """D6's answer, as a check rather than as a rule (`logs/T-0045.md`).

    §10's third question asks whether the facet list should be derived from the
    models so the failure is a build error instead of a review miss. It is not
    derived — a classification cannot be — but it is *enumerated against* them,
    which buys the same thing: a spec field added later turns this red before
    it can be reported as unchanged when it changed.
    """
    if record is CanonicalField:
        names = tuple(CanonicalField.model_fields)
    else:
        names = tuple(field.name for field in dataclasses.fields(record))

    unmapped = [
        name for name in names if name not in _IDENTITY and (record.__name__, name) not in _FACETS
    ]

    assert unmapped == []


def test_every_facet_the_vocabulary_declares_is_used() -> None:
    """A member no row lands in is a distinction the compiler does not draw,
    which is the failure RFC 0037's `transitive` basis was retired for."""
    assert set(_FACETS.values()) == set(Facet)


@pytest.mark.parametrize("fixture", spec_fixture_names())
def test_every_definition_the_corpus_produces_flattens_into_the_table(fixture: str) -> None:
    """The static check above reads the models; this one reads what real
    projects actually put in them.

    The two catch different things. A field added to `MetricIR` fails the first
    without any fixture exercising it; a *record* reaching `_definition` that
    `COMPARABLE` does not name — a shape that arrives through some arm nobody
    updated — fails only here, because `_flatten` refuses a record it has no
    field table for.
    """
    if fixture in {"fanout_trap", "scd2_mart_refusal"}:
        pytest.skip("refused at guardrails, so it reaches no IR")

    project, catalog = load_fixture(fixture)
    graph, ir = _compile(
        SpecVersion(label="x", project=project, catalog=catalog, steps=registry_for(fixture))
    )

    for node in graph.nodes:
        kind, spelling = _kind_and_spelling(node.name)
        definition = _definition(kind, spelling, ir, catalog)
        flat = _flatten(definition)

        unmapped = [
            f"{record}.{field}" for field, (record, _value) in flat.items()
            if (record, field) not in _FACETS
        ]
        assert unmapped == [], node.name


def test_a_field_the_table_does_not_cover_is_refused_loudly() -> None:
    """The raise §9 asks for, reached deliberately.

    A `check` refusal would reject an author's specs for a gap in a table that
    ships with the compiler, and there is no warnings channel to put it in
    (RFC 0033 is unstarted) — so the answer to D6 is a test plus this, which is
    loud in the one place a wrong answer could otherwise be quiet.
    """

    @dataclasses.dataclass(frozen=True)
    class Invented:
        name: str
        curvature: int

    with pytest.raises(InvariantViolated, match="Invented.curvature lands in no facet"):
        facets(Invented(name="x", curvature=1), Invented(name="x", curvature=2))


def test_a_record_with_no_field_table_is_refused_rather_than_ignored() -> None:
    """`_flatten` takes `object`, because `_definition` returns one. A value it
    cannot read has to say so: returning an empty map would report every such
    node as never having changed."""
    with pytest.raises(InvariantViolated, match="no field table"):
        facets("a definition", "another")


# ....................... #
# Identity is not definition (§6)


@pytest.mark.parametrize("field", sorted(_IDENTITY))
def test_no_identity_field_is_in_the_table(field: str) -> None:
    """Excluded once, rather than blanked per kind. The canonical field is the
    one record that retains RFC 0062's `id`, and a rule stated in its arm alone
    is a rule the other nine kinds are free to contradict."""
    assert not [record for record, name in _FACETS if name == field]


def test_a_pure_rename_attributes_nothing() -> None:
    """RFC 0064 §6's first test. Identity is RFC 0062's business, and a node
    whose only difference is what it is called has not been redefined."""
    assert facets(metric(), metric(name="revenue_gross")) == ()


def test_minting_a_catalog_id_attributes_nothing_either() -> None:
    """The claim above on the one record that carries an `id` field at all."""
    field = CanonicalField(entity="order_item", type="decimal(12, 2)")

    assert facets(field, field.model_copy(update={"id": "cf_9b2e14"})) == ()


# ....................... #
# The facets themselves


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"grain": "order_item"}, (Facet.GRAIN, "grain", "order", "order_item")),
        ({"agg": "max"}, (Facet.ADDITIVITY, "agg", "sum", "max")),
        (
            {"additivity": Additivity.NON_ADDITIVE},
            (Facet.ADDITIVITY, "additivity", "additive", "non_additive"),
        ),
        ({"expr": SqlExpr(sql="amount * 2")}, (Facet.BODY, "expr", "amount", "amount * 2")),
        (
            {"depends_on": ("order.amount", "order.tax")},
            (Facet.INPUTS, "depends_on", "order.amount", "order.amount, order.tax"),
        ),
        (
            {"description": "what the shop billed"},
            (Facet.METADATA, "description", None, "what the shop billed"),
        ),
    ],
    ids=["grain", "agg", "additivity", "expr", "depends_on", "description"],
)
def test_one_metric_field_lands_in_one_facet(
    overrides: dict[str, object], expected: tuple[Facet, str, str | None, str | None]
) -> None:
    """§5.1's table, read one row at a time — and the fields it does not name,
    which are the four members this corpus needed beyond it."""
    moved = facets(metric(), metric(**overrides))

    assert [(one.facet, one.field, one.old, one.new) for one in moved] == [expected]


def test_a_filter_moving_is_the_filter_facet_and_carries_no_values() -> None:
    """A filter is a tuple of records, so there is no compact spelling for it
    and the delta names the field and stops. Naming it is the answer; rendering
    a predicate list into a string would be the text diff D1 refuses."""
    clause = MetricFilterIR(dimension="status", op="in", values=("paid",))
    moved = facets(metric(), metric(filter=(clause,)))

    assert [(one.facet, one.field, one.old, one.new) for one in moved] == [
        (Facet.FILTER, "filter", None, None)
    ]


def test_several_facets_moving_come_back_sorted() -> None:
    """Deterministic in the way everything else is (RFC 0003 §5.3) — sorted by
    facet and then field, never in the order the fields happen to be declared
    in.

    The pair is `depends_on` and `expr`, and it is chosen rather than
    convenient: sorted by **field** they come back in that order, and sorted by
    **facet** the expression comes first. Every other combination of this
    record's fields agrees with alphabetical field order, so a walk that
    returned its input order unsorted passed a three-facet version of this test
    (`logs/T-0045.md`).
    """
    moved = facets(metric(), metric(depends_on=("order.tax",), expr=SqlExpr(sql="net")))

    assert [(one.facet.value, one.field) for one in moved] == [
        ("body", "expr"),
        ("inputs", "depends_on"),
    ]


def test_a_record_that_changed_kind_compares_across_the_two() -> None:
    """A metric that stopped resolving becomes an `UnreachableMetric`, and the
    two records share one field, which is the one excluded.

    Nothing special-cases it: both sides flatten to a field map, and a field
    only one side carries is a delta with one end. The answer is verbose and
    it is an answer — the alternative, refusing to compare two shapes, reports
    a metric that stopped computing as a metric that did not move.
    """
    moved = facets(metric(), UnreachableMetric(name="gross_revenue", missing=("order.amount",)))

    assert ("inputs", "missing", None, "order.amount") in [
        (one.facet.value, one.field, one.old, one.new) for one in moved
    ]
    assert ("grain", "grain", "order", None) in [
        (one.facet.value, one.field, one.old, one.new) for one in moved
    ]


# ....................... #
# The entity field, which is two records (RFC 0024 D26)


def lowering(relation: str, sql: str, recipe: str | None = None) -> tuple[str, SourceColumnIR]:
    return relation, SourceColumnIR(name="unit_price", expr=SqlExpr(sql=sql), recipe_id=recipe)


def column(**overrides: object) -> ColumnIR:
    base: dict[str, object] = {
        "name": "unit_price",
        "type": parse_type("decimal(12, 2)", source_path="tests"),
        "canonical": "unit_price",
        "unit": Unit.CURRENCY,
        "tax_basis": None,
        "renamed_from": None,
        "required": False,
    }
    return ColumnIR(**{**base, **overrides})  # type: ignore[arg-type]


def test_a_columns_schema_and_its_lowering_are_both_compared() -> None:
    """The two halves live apart, and a comparison reading either alone misses
    the other entirely — which is what the corpus's five-version history shows
    at two different boundaries."""
    before = (column(), (lowering("shop", "price"),))
    after = (column(unit=Unit.COUNT), (lowering("shop", "total / qty"),))

    assert [(one.facet.value, one.field) for one in facets(before, after)] == [
        ("body", "expr"),
        ("unit", "unit"),
    ]


def test_a_lowering_is_reported_under_the_source_it_belongs_to() -> None:
    """A merged entity lowers one column once per source (D28), and a rendering
    that dropped the relation would show two expressions and no way to tell
    which shop's mapping moved."""
    before = (column(), (lowering("shop", "price"), lowering("erp", "unit_cost")))
    after = (column(), (lowering("shop", "price"), lowering("erp", "cost")))

    assert [(one.field, one.old, one.new) for one in facets(before, after)] == [
        ("expr", "shop: price; erp: unit_cost", "shop: price; erp: cost")
    ]


# ....................... #
# Rendering


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("order", "order"),
        (Unit.CURRENCY, "currency"),
        (Materialization.FULL, "full"),
        (7, "7"),
        (True, "True"),
        (Decimal("1.50"), "1.50"),
        (SqlExpr(sql="a + b"), "a + b"),
        (("one", "two"), "one, two"),
        ((), None),
    ],
    ids=[
        "none", "str", "str-enum", "materialization", "int", "bool",
        "decimal", "expression", "name-list", "empty",
    ],
)
def test_a_value_with_a_compact_spelling_is_rendered(value: object, expected: str | None) -> None:
    assert _render(value) == expected


def test_a_logical_type_renders_as_a_spec_would_write_it() -> None:
    """Through `render_type`, which is public precisely so that the consumers
    that report a type back to a person cannot invent a second spelling."""
    assert _render(column().type) == "decimal(12,2)"


def test_a_value_with_no_compact_spelling_renders_as_nothing() -> None:
    """`None` here means "this has no short form", and the field name is what
    carries the answer. Flattening a record list into a string would be a text
    diff wearing a facet's name (D1)."""
    assert _render((MetricFilterIR(dimension="status", op="in", values=("paid",)),)) is None
    assert _render(SCDKind.TYPE2) == "type2"


def test_a_half_renderable_lowering_list_renders_as_nothing() -> None:
    """Half a list is worse than none: a reader cannot see which half is
    missing, and the field name already says what moved."""
    value = (("shop", SqlExpr(sql="price")), ("erp", MetricFilterIR("status", "in", ("paid",))))

    assert _render(value) is None


# ....................... #
# The kinds beyond a metric


def test_a_rollups_retained_dimensions_are_its_grain() -> None:
    """A rollup's `keep` is which rows it describes, which is the same fact a
    mart states in `grain` — so it lands in the same facet rather than in a
    second one meaning the same thing."""
    before = RollupIR(name="daily", of="order_items", keep=("day",), measures=("revenue",))
    after = dataclasses.replace(before, keep=("day", "region"))

    assert [(one.facet.value, one.field) for one in facets(before, after)] == [("grain", "keep")]


def test_an_exposures_owner_is_metadata_and_its_metrics_are_inputs() -> None:
    """One record, two facets, and the split is what a reader does with the
    answer: an owner changing is a person to ask, a metric list changing is a
    number that moved."""
    before = ExposureIR(
        name="weekly", kind=ExposureKind.DASHBOARD, owner="analytics", metrics=("revenue",), marts=()
    )
    after = dataclasses.replace(before, owner="finance", metrics=("revenue", "orders"))

    assert [(one.facet.value, one.field) for one in facets(before, after)] == [
        ("inputs", "metrics"),
        ("metadata", "owner"),
    ]


def test_a_step_is_told_apart_from_what_it_runs() -> None:
    """A step's `body` is what it computes and its `runtime_lock` is what
    executes it. They move for different reasons and a reader chases them in
    different places, so `RUNTIME` exists rather than `body` covering both."""
    project, catalog = load_fixture("identity_resolution")
    _graph, ir = _compile(
        SpecVersion(
            label="x", project=project, catalog=catalog, steps=registry_for("identity_resolution")
        )
    )
    step = next(one for one in ir.steps)

    assert [(one.facet.value, one.field) for one in facets(step, dataclasses.replace(step, version=step.version + 1))] == [
        ("runtime", "version")
    ]
