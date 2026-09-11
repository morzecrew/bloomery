"""One node across N spec sets (RFC 0069 §6).

The projects here are hand-written, for the reason ``test_lineage.py`` gives
about hand-built graphs: every claim is about a *history* — a rename, an id
minted partway through, a gap — and no fixture in the corpus has the shape a
given claim needs. Where a real history is the better input, this uses the real
one: ``evolution_v1``..``v5`` are five versions of one project and are what the
``plan()`` suite already diffs pairwise.

The two guards at the bottom are the ones that outlive this phase. A node kind
added to the graph with no rule for reading its definition would otherwise
compare equal to itself forever — present in every version, changed in none —
which is a wrong answer that looks exactly like a right one.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from collections.abc import Iterator

import pytest

from bloomery import (
    MatchedBy,
    SpecVersion,
    Timeline,
    load_catalog,
    load_project,
    timeline,
)
from bloomery.ir import NODE_ID_PREFIXES
from bloomery.resolve.graph import NodeKind
from bloomery.resolve.timeline import (
    _KIND_BY_PREFIX,  # pyright: ignore[reportPrivateUsage]
)
from support.compiling import FIXTURES, load_fixture
from support.steps import registry_for

pytestmark = pytest.mark.unit


ENTITY_MODEL = """
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      amount: {type: "decimal(12, 2)"}
"""

MAPPING = """
mapping_version: 1
source: raw__orders
target: order
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  amount: {from: "$.amount"}
"""


def sources(*, metric: str = "gross_revenue", node_id: str | None = None, agg: str = "sum") -> dict[str, str]:
    """One project, varied along the three axes a history moves on: the
    metric's name, whether it has adopted an RFC 0062 ``id:``, and its
    definition."""

    minted = f"\n    id: {node_id}" if node_id is not None else ""
    return {
        "entity_model": ENTITY_MODEL,
        "mapping": MAPPING,
        "metrics": f"""
metrics_version: 1
metrics:
  {metric}:{minted}
    grain: order
    additivity: additive
    agg: {agg}
    expr: "amount"
""",
    }


def version(label: str, **kwargs: object) -> SpecVersion:
    return SpecVersion(label=label, project=load_project(sources(**kwargs)))  # type: ignore[arg-type]


def shape(walk: Timeline) -> tuple[tuple[tuple[str, bool], ...], tuple[tuple[str, str, str], ...]]:
    """A timeline as comparable primitives — labels and presence, then each
    change as ``(before, after, matched_by)``."""

    return (
        tuple((entry.label, entry.present) for entry in walk.entries),
        tuple((change.before, change.after, change.matched_by.value) for change in walk.changes),
    )


# ....................... #
# The value (D4, D13)


def test_a_node_that_never_changed_is_a_result_not_a_miss() -> None:
    """D4, and the property `Lineage` has for the same reason: "this has not
    moved since March" is what a reader came for at least as often as the
    other, so it comes back as a one-version timeline rather than an empty
    one."""
    walk = timeline([version("2026-03-01T00:00:00Z")], "metric.gross_revenue")

    assert shape(walk) == ((("2026-03-01T00:00:00Z", True),), ())
    assert walk.node == "metric.gross_revenue"


def test_two_identical_versions_report_no_change() -> None:
    """The other half of D4: present twice, changed never. A comparison that
    reported a change here would be reporting that the spec was recompiled."""
    history = [version("a"), version("b")]

    assert shape(timeline(history, "metric.gross_revenue")) == ((("a", True), ("b", True)), ())


def test_a_changed_definition_is_one_change_between_the_two_labels() -> None:
    history = [version("a"), version("b", agg="max")]

    assert shape(timeline(history, "metric.gross_revenue")) == (
        (("a", True), ("b", True)),
        (("a", "b", "name"),),
    )


def test_facets_is_empty_in_p1_and_is_a_tuple() -> None:
    """D3 and D13. The field is present from P1 so a consumer's JSON grows a
    value in P2 rather than changing shape — and it is empty, because the
    delta vocabulary is RFC 0064's and is not restated here."""
    walk = timeline([version("a"), version("b", agg="max")], "metric.gross_revenue")

    assert [change.facets for change in walk.changes] == [()]


# ....................... #
# Identity (D5, D12)


def test_a_rename_without_an_id_is_a_delete_and_an_add() -> None:
    """§5.2's stated cost. Matching two definitions by their *shape* is a
    guess, and a confidently wrong history is worse than an honest gap — so the
    old id stops being a node and nothing claims the new one continues it."""
    history = [version("a"), version("b", metric="revenue_gross")]

    assert shape(timeline(history, "metric.gross_revenue")) == ((("a", True), ("b", False)), ())
    assert shape(timeline(history, "metric.revenue_gross")) == ((("a", False), ("b", True)), ())


def test_the_same_rename_with_an_id_is_one_node_across_the_boundary() -> None:
    """The pair that makes RFC 0062 pay, and the reason D11 takes the `Project`
    rather than the IR: the IR does not retain the `id:` at all."""
    history = [
        version("a", node_id="mtr_7f3a9c"),
        version("b", metric="revenue_gross", node_id="mtr_7f3a9c"),
    ]

    assert shape(timeline(history, "metric.mtr_7f3a9c")) == (
        (("a", True), ("b", True)),
        (("a", "b", "id"),),
    )


def test_minting_an_id_alone_is_not_a_definition_change() -> None:
    """An id is identity, not definition — RFC 0062 keeps it out of the IR
    entirely, so nothing a metric's record holds moves when one is adopted.

    Asserted rather than assumed because the one kind whose record is a *spec*
    model — a canonical field, which the IR has no record of at all — does
    carry its `id`, and `_definition` blanks it so that this holds there too.
    """
    history = [version("a"), version("b", node_id="mtr_7f3a9c")]

    assert shape(timeline(history, "metric.gross_revenue")) == ((("a", True), ("b", True)), ())


def test_an_id_adopted_partway_through_matches_that_boundary_by_name() -> None:
    """D12: a pair matches by id only when **both** sides carry one, so the
    boundary where adoption happens is a name match and every boundary after it
    is an id match. One per-timeline answer would have to lie about one of
    them.

    The definition moves in the same entry as the mint, because otherwise there
    is no change at that boundary to carry a `matched_by` at all.
    """
    history = [
        version("a"),
        version("b", node_id="mtr_7f3a9c", agg="max"),
        version("c", metric="revenue_gross", node_id="mtr_7f3a9c", agg="min"),
    ]

    assert shape(timeline(history, "metric.gross_revenue")) == (
        (("a", True), ("b", True), ("c", True)),
        (("a", "b", "name"), ("b", "c", "id")),
    )


def test_adopting_an_id_and_renaming_at_once_is_a_delete_and_an_add() -> None:
    """The case the rule cannot recover, asserted because a reader should find
    it written down rather than discover it. Nothing connects the two
    definitions except a guess about their shape, and §5.2 refuses to guess."""
    history = [version("a"), version("b", metric="revenue_gross", node_id="mtr_7f3a9c")]

    assert shape(timeline(history, "metric.gross_revenue")) == ((("a", True), ("b", False)), ())
    assert shape(timeline(history, "metric.mtr_7f3a9c")) == ((("a", False), ("b", True)), ())


# ....................... #
# Absence (D13) and the unknown node (D7)


def test_a_gap_is_an_absence_and_no_change_spans_it() -> None:
    """The absence has a *position*, so a reader can see which entry the node
    was missing from — and the changes step over it rather than eliding to one
    change that spans it, which would claim a definition moved across a version
    it was not in."""
    history = [version("a"), version("b", metric="something_else"), version("c", agg="max")]

    assert shape(timeline(history, "metric.gross_revenue")) == (
        (("a", True), ("b", False), ("c", True)),
        (),
    )


def test_an_unknown_node_is_absent_everywhere_and_refuses_nothing() -> None:
    """D7, decided as `lineage()` already answers it: a root need not be a
    member of the graph, and refusing here would make the library disagree with
    its own sibling. The refusal with a did-you-mean is the command's."""
    walk = timeline([version("a"), version("b")], "metric.no_such_thing")

    assert shape(walk) == ((("a", False), ("b", False)), ())


def test_an_empty_history_is_an_empty_timeline() -> None:
    assert shape(timeline([], "metric.gross_revenue")) == ((), ())


# ....................... #
# The labels, and the order (D1, D10)


def test_the_labels_are_never_parsed() -> None:
    """D1. A history labelled `a`/`b`/`c` answers identically to one labelled
    with instants, because nothing reads a label — it is carried, rendered, and
    compared for nothing."""
    opaque = [version("a"), version("b", agg="max")]
    dated = [version("2026-03-01T00:00:00Z"), version("2026-06-01T00:00:00Z", agg="max")]

    by_presence = [entry.present for entry in timeline(opaque, "metric.gross_revenue").entries]
    assert by_presence == [entry.present for entry in timeline(dated, "metric.gross_revenue").entries]

    assert shape(timeline(dated, "metric.gross_revenue")) == (
        (("2026-03-01T00:00:00Z", True), ("2026-06-01T00:00:00Z", True)),
        (("2026-03-01T00:00:00Z", "2026-06-01T00:00:00Z", "name"),),
    )


def test_order_is_positional_and_a_reversed_history_is_not_refused() -> None:
    """D1's stated cost, pinned so that adding a sort later is a visible
    decision rather than a fix. It is the same trust `plan(old, new)` already
    places in its arguments, where nothing checks that `old` is older."""
    forward = [version("2026-03-01T00:00:00Z"), version("2026-06-01T00:00:00Z", agg="max")]

    assert shape(timeline(list(reversed(forward)), "metric.gross_revenue")) == (
        (("2026-06-01T00:00:00Z", True), ("2026-03-01T00:00:00Z", True)),
        (("2026-06-01T00:00:00Z", "2026-03-01T00:00:00Z", "name"),),
    )


def test_a_label_with_an_offset_would_sort_wrongly_and_is_carried_anyway() -> None:
    """D10 is a *convention*, enforced nowhere — and the reason it narrows to
    one spelling rather than to "ISO-8601" is demonstrated here, not asserted:
    `-01:00` sorts before `Z` and is an hour later.

    The timeline carries both verbatim and orders neither, which is what makes
    the recommendation a docs matter rather than a check.
    """
    later = "2026-03-01T00:00:00-01:00"
    earlier = "2026-03-01T00:00:00Z"
    assert later < earlier, "the counterexample D10 rests on"

    walk = timeline([version(earlier), version(later, agg="max")], "metric.gross_revenue")
    assert [entry.label for entry in walk.entries] == [earlier, later]


# ....................... #
# The history itself (D2)


def test_a_generator_is_accepted_and_read_exactly_once() -> None:
    """D2. A caller fetching from a store pays for every pass, so the walk
    takes an `Iterable`, consumes it once in order, and never re-iterates."""
    passes = 0

    class Once:
        def __iter__(self) -> Iterator[SpecVersion]:
            nonlocal passes
            passes += 1
            yield version("a")
            yield version("b", agg="max")

    walk = timeline(Once(), "metric.gross_revenue")

    assert passes == 1
    assert shape(walk) == ((("a", True), ("b", True)), (("a", "b", "name"),))


def test_a_history_entry_may_wire_steps() -> None:
    """§5.1 listed three fields and a project that wires a step cannot be
    compiled from them: the registry is a caller-assembled compile input
    (RFC 0017 §5.3), and against an empty one the compile is refused before
    anything can be compared. See `logs/T-0043.md`.

    The refusal is asserted beside the answer, because "it works" is only
    interesting next to the thing that does not.
    """
    project, catalog = load_fixture("identity_resolution")
    steps = registry_for("identity_resolution")
    node = "step.resolve_customers"

    wired = [
        SpecVersion(label="a", project=project, catalog=catalog, steps=steps),
        SpecVersion(label="b", project=project, catalog=catalog, steps=steps),
    ]
    assert shape(timeline(wired, node)) == ((("a", True), ("b", True)), ())

    with pytest.raises(Exception, match="resolve_customers"):
        timeline([SpecVersion(label="a", project=project, catalog=catalog)], node)


# ....................... #
# A real history


def evolution() -> list[SpecVersion]:
    history = []
    for step in range(1, 6):
        name = f"evolution_v{step}"
        project, catalog = load_fixture(name)
        history.append(
            SpecVersion(label=f"v{step}", project=project, catalog=catalog, steps=registry_for(name))
        )
    return history


def test_a_real_history_locates_the_two_versions_a_field_moved_in() -> None:
    """The corpus's own five-version project, which the `plan()` suite already
    diffs pairwise. `order_item.unit_price` is retyped between v1 and v2
    (`decimal(10, 2)` → `decimal(12, 4)`, in the entity model) and re-derived
    between v3 and v4 (the `direct` recipe → `from_total`, in the mapping).

    Both halves matter: the first moves only the `ColumnIR` and the second only
    the `SourceColumnIR`, so a comparison reading either alone would report one
    of these two and miss the other.
    """
    assert shape(timeline(evolution(), "order_item.unit_price")) == (
        (("v1", True), ("v2", True), ("v3", True), ("v4", True), ("v5", True)),
        (("v1", "v2", "name"), ("v3", "v4", "name")),
    )


def test_a_source_column_is_presence_and_nothing_else() -> None:
    """A bronze path has no definition beyond its existence, so presence is the
    whole of what its timeline can report — and here that is the whole story.

    `$.price` is read directly until v4 swaps the field onto the `from_total`
    recipe, after which nothing reads it and the node is gone. A change list is
    the wrong shape for that fact and stays empty; the entries carry it.
    """
    assert shape(timeline(evolution(), "source.shop__order_lines.$.price")) == (
        (("v1", True), ("v2", True), ("v3", True), ("v4", False), ("v5", False)),
        (),
    )


def test_a_catalog_field_is_compared_by_the_only_record_of_one_there_is() -> None:
    """`ProjectIR` has no canonical-field record — the field survives lowering
    only as `ColumnIR.canonical`, a string reference — so the catalog's own
    model is what gets compared."""
    project, _ = load_fixture("ecom_basic")
    text = (FIXTURES / "ecom_basic" / "catalog.yaml").read_text()
    widened = text.replace("type: decimal(12,4)", "type: decimal(14,4)", 1)
    assert widened != text, "the edit the rest of this test rests on"

    history = [
        SpecVersion(label="a", project=project, catalog=load_catalog(text)),
        SpecVersion(label="b", project=project, catalog=load_catalog(widened)),
    ]
    walk = timeline(history, "canonical.unit_price")

    assert [entry.present for entry in walk.entries] == [True, True]
    assert [(change.before, change.after) for change in walk.changes] == [("a", "b")]


def test_every_kind_the_graph_mints_has_a_timeline() -> None:
    """One assertion per node kind, over projects that actually carry one.

    The per-kind table in `_definition` is the part of this walk a test can
    only reach by *asking* for each kind: a kind whose lookup is wrong reports
    the node present in every version and changed in none, which reads exactly
    like a node that never moved.

    The two versions are identical, so every answer here is "present, never
    changed" — the claim is that the lookup found a record at all, which the
    change tests above then exercise for the kinds a fixture can move.
    """
    project, catalog = load_fixture("ecom_basic")
    history = [
        SpecVersion(label="a", project=project, catalog=catalog),
        SpecVersion(label="b", project=project, catalog=catalog),
    ]
    rollup_project, rollup_catalog = load_fixture("rollup_mart")
    rollups = [
        SpecVersion(label="a", project=rollup_project, catalog=rollup_catalog),
        SpecVersion(label="b", project=rollup_project, catalog=rollup_catalog),
    ]

    for walk, node in (
        (timeline(history, "metric.gross_revenue"), NodeKind.METRIC),
        # `margin` requires a canonical field the fixture deliberately never
        # maps, so the IR keeps an `UnreachableMetric` for it and no `MetricIR`
        # at all — a record, and the one this walk has to fall back to.
        (timeline(history, "metric.margin"), NodeKind.METRIC),
        (timeline(history, "canonical.unit_price"), NodeKind.CANONICAL_FIELD),
        (timeline(history, "order_item.unit_price"), NodeKind.ENTITY_FIELD),
        (timeline(history, "mart.order_items"), NodeKind.MART),
        (timeline(history, "exposure.weekly_revenue_review"), NodeKind.EXPOSURE),
        (timeline(history, "source.shopify__order_lines.$.qty"), NodeKind.SOURCE_COLUMN),
        # A rollup is a gold relation under the same `mart.` prefix, and lives
        # in its own IR collection (RFC 0058 §5.2).
        (timeline(rollups, "mart.order_items_monthly"), NodeKind.MART),
    ):
        assert shape(walk) == ((("a", True), ("b", True)), ()), node


def test_a_step_is_compared_by_its_manifest() -> None:
    """The kind `ecom_basic` has no instance of. A version bump moves the
    `StepIR` and the node stays put — `step_node` is keyed by `ref` alone,
    because a version bump does not move where a step sits in the lineage."""
    project, catalog = load_fixture("identity_resolution")
    steps = registry_for("identity_resolution")
    history = [
        SpecVersion(label="a", project=project, catalog=catalog, steps=steps),
        SpecVersion(label="b", project=project, catalog=catalog, steps=steps),
    ]

    assert shape(timeline(history, "step.resolve_customers")) == (
        (("a", True), ("b", True)),
        (),
    )


def test_a_catalog_node_asked_of_a_project_with_no_catalog_is_absent() -> None:
    """A canonical field's only record is the catalog's, so a history with no
    catalog can carry no such node — reported absent rather than raised."""
    assert shape(timeline([version("a")], "canonical.unit_price")) == ((("a", False),), ())


def test_a_bare_prefix_is_read_as_a_name_not_as_a_kind() -> None:
    """`metric` with nothing after it is not a metric node — it is a node id
    with no kind, which is what an entity field looks like. It resolves to
    nothing, which is the same answer any other unknown node gets (D7)."""
    assert shape(timeline([version("a")], "metric")) == ((("a", False),), ())


# ....................... #
# The two guards that outlive this phase


def test_the_prefix_table_is_the_reserved_one() -> None:
    """`_KIND_BY_PREFIX` and `NODE_ID_PREFIXES` are two readings of one fact.
    A kind added to the graph with a new prefix that is reserved but unmapped
    would resolve here as an *entity field* named after it — a node that exists
    nowhere, reported absent in every version, with nothing saying why."""
    assert tuple(sorted(_KIND_BY_PREFIX)) == NODE_ID_PREFIXES


def test_every_node_kind_has_a_definition_rule() -> None:
    """Read off `_definition`'s own `match`, not off a list beside it.

    A kind with no arm falls through to `None`, and two `None`s compare equal —
    so a new node kind would be reported present in every version and changed in
    none, which is a wrong answer indistinguishable from a right one. That is
    exactly the shape `_EDGE_SHAPES`' source guard exists for, applied to the
    other closed table this walk depends on.
    """
    # By name through `importlib`, not as an attribute of the package: the
    # package re-exports the *function* `timeline`, which shadows the module
    # of the same name exactly as it does for `lineage`.
    source = inspect.getsource(importlib.import_module("bloomery.resolve.timeline"))
    definition = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_definition"
    )
    matched = {
        pattern.value.attr
        for statement in definition.body
        if isinstance(statement, ast.Match)
        for case in statement.cases
        if isinstance(pattern := case.pattern, ast.MatchValue)
        and isinstance(pattern.value, ast.Attribute)
    }

    assert matched == {kind.name for kind in NodeKind}
