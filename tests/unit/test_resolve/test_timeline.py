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
    EMPTY_REGISTRY,
    Catalog,
    MatchedBy,
    Project,
    StepRegistry,
    SpecVersion,
    Timeline,
    load_catalog,
    load_project,
    timeline,
)
from bloomery.errors import GuardrailError, UnknownStep
from bloomery.resolve.facets import Facet, facets
from bloomery.ir import NODE_ID_PREFIXES
from bloomery.resolve.graph import Node, NodeKind
from bloomery.spec.project import node_keys
from bloomery.resolve.timeline import (
    _ID_NAMESPACE,  # pyright: ignore[reportPrivateUsage]
    _KIND_BY_PREFIX,  # pyright: ignore[reportPrivateUsage]
    _compile,  # pyright: ignore[reportPrivateUsage]
    _definition,  # pyright: ignore[reportPrivateUsage]
    _kind_and_spelling,  # pyright: ignore[reportPrivateUsage]
)
from support.compiling import FIXTURES, fixture_sources, load_fixture, spec_fixture_names
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


def sources(
    *,
    metric: str = "gross_revenue",
    node_id: str | None = None,
    agg: str = "sum",
    required: bool = False,
) -> dict[str, str]:
    """One project, varied along the axes a history moves on: the metric's
    name, whether it has adopted an RFC 0062 ``id:``, its definition — and one
    entity-field axis that moves a column's *schema* without touching the
    expression that produces it."""

    minted = f"\n    id: {node_id}" if node_id is not None else ""
    return {
        "entity_model": ENTITY_MODEL.replace(
            'amount: {type: "decimal(12, 2)"}',
            f'amount: {{type: "decimal(12, 2)", required: {str(required).lower()}}}',
        ),
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


def twice(
    project: Project, catalog: Catalog | None = None, steps: StepRegistry = EMPTY_REGISTRY
) -> list[SpecVersion]:
    """The same version, labelled `a` and `b`.

    The shape every "this kind is found at all" assertion needs, where the
    claim is that the lookup found a record rather than that a definition
    moved — so every such answer reads "present, present, no change".
    """

    return [
        SpecVersion(label=label, project=project, catalog=catalog, steps=steps)
        for label in ("a", "b")
    ]


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


def test_a_change_carries_the_facet_that_moved() -> None:
    """D3: the vocabulary is RFC 0064's, asserted against that module's own
    members rather than restated here, so the two cannot fork."""
    walk = timeline([version("a"), version("b", agg="max")], "metric.gross_revenue")

    assert [
        (delta.facet, delta.field, delta.old, delta.new)
        for change in walk.changes
        for delta in change.facets
    ] == [(Facet.ADDITIVITY, "agg", "sum", "max")]


def test_a_change_is_never_empty() -> None:
    """The facets decide what a change *is*, so one with nothing to report is
    not a change at all — which is what makes RFC 0064 §6's first test true."""
    walk = timeline([version("a"), version("b", agg="max")], "metric.gross_revenue")

    assert walk.changes
    assert all(change.facets for change in walk.changes)


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

    # RFC 0064 §6's first test: the node crossed the boundary and **nothing**
    # is attributed to it. Identity belongs to no facet, so a rename moves no
    # definition — which is the whole claim, and is why the delete-and-add
    # above is told from this by `entries` rather than by `changes`.
    assert shape(timeline(history, "metric.mtr_7f3a9c")) == (
        (("a", True), ("b", True)),
        (),
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


def test_minting_a_catalog_id_alone_is_not_a_definition_change_either() -> None:
    """The claim above, on the one kind it could fail for.

    A canonical field is compared by the catalog's own model and that model
    *does* carry `id` — so without `_definition` blanking it, adopting an id
    would read as a redefinition for this kind and for no other. Asserted
    rather than argued, because the blanking is one keyword and invisible.
    """
    project, _ = load_fixture("ecom_basic")
    text = (FIXTURES / "ecom_basic" / "catalog.yaml").read_text()
    minted = text.replace("  unit_price:\n", "  unit_price:\n    id: cf_9b2e14\n", 1)
    assert minted != text, "the edit the rest of this test rests on"

    history = [
        SpecVersion(label="a", project=project, catalog=load_catalog(text)),
        SpecVersion(label="b", project=project, catalog=load_catalog(minted)),
    ]

    # The node is renamed by the mint — `canonical.unit_price` becomes
    # `canonical.cf_9b2e14` — and is matched across the boundary by name.
    assert shape(timeline(history, "canonical.unit_price")) == ((("a", True), ("b", True)), ())


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


def test_an_id_match_picks_up_the_new_name_it_found() -> None:
    """After crossing a rename by id, the *name* carried forward has to be the
    new one — every later lookup reads the definition under it.

    It takes a third entry and a project where the old name has been reused,
    which is exactly when a stale name stops finding nothing and starts finding
    somebody else's definition. The id-carrying metric never moves here, so the
    correct answer is no change at all; carrying `alpha` forward would read
    *that* metric's aggregate instead and report two.
    """

    def metrics(renamed: str, reused_agg: str | None) -> dict[str, str]:
        reused = (
            ""
            if reused_agg is None
            else f"""
  alpha:
    grain: order
    additivity: additive
    agg: {reused_agg}
    expr: "amount"
"""
        )
        return {
            "entity_model": ENTITY_MODEL,
            "mapping": MAPPING,
            "metrics": f"""
metrics_version: 1
metrics:
  {renamed}:
    id: mtr_7f3a9c
    grain: order
    additivity: additive
    agg: sum
    expr: "amount"
{reused}""",
        }

    history = [
        SpecVersion(label="a", project=load_project(metrics("alpha", None))),
        SpecVersion(label="b", project=load_project(metrics("beta", "max"))),
        SpecVersion(label="c", project=load_project(metrics("beta", "count"))),
    ]

    # `alpha` is the id-carrying metric in `a` and a *different* metric from
    # `b` on. Asked by the id, the walk follows the id — and `beta` does not
    # move between `b` and `c`, whatever `alpha` does.
    assert shape(timeline(history, "metric.mtr_7f3a9c")) == (
        (("a", True), ("b", True), ("c", True)),
        (),
    )


def test_a_node_is_found_at_the_first_entry_that_carries_the_spelling_asked() -> None:
    """Resolution is forward-only, and that is not symmetric between the two
    spellings — so it is pinned rather than described.

    The walk reads the history once and in order (D2), so it cannot know at the
    first entry that a spelling appearing three entries later belongs to the
    node in front of it. A **name** query therefore spans a later adoption, the
    name being carried and translated per version; an **id** query reports the
    versions before that id existed as absent; and a name query against a
    project that adopted the id before the window reads absent throughout,
    because `metric.gross_revenue` is then a node id no version has.
    """
    adoption = [version("a"), version("b", node_id="mtr_7f3a9c")]

    assert shape(timeline(adoption, "metric.gross_revenue")) == ((("a", True), ("b", True)), ())
    assert shape(timeline(adoption, "metric.mtr_7f3a9c")) == ((("a", False), ("b", True)), ())

    adopted_before = [version(label, node_id="mtr_7f3a9c") for label in ("a", "b")]
    assert shape(timeline(adopted_before, "metric.gross_revenue")) == (
        (("a", False), ("b", False)),
        (),
    )


def test_one_name_with_two_different_ids_is_two_nodes() -> None:
    """§5.2 licenses the name fallback only where **one** side lacks an id.

    An `id:` is write-once (RFC 0062 D6): editing one is a delete and an add,
    and nothing can tell that apart from an actual delete and an add — which is
    the distinction the id was carrying. Falling through to the name here
    reported the two as one node, and reported it as a node that never moved,
    because the only thing that differs is the id and the IR does not carry it.
    """
    history = [version("a", node_id="mtr_7f3a9c"), version("b", node_id="mtr_0041aa")]

    assert shape(timeline(history, "metric.mtr_7f3a9c")) == ((("a", True), ("b", False)), ())
    assert shape(timeline(history, "metric.mtr_0041aa")) == ((("a", False), ("b", True)), ())


def test_dropping_an_id_falls_back_to_the_name() -> None:
    """The direction §5.2 licenses, and the one the rule above must not eat.

    "An id present on one side and absent on the other falls back to the name"
    covers a version that drops an `id:` as much as one that has not adopted it
    yet — so the guard against two *different* ids has to ask whether this
    version adopted one at all, not merely whether the carried side has one.
    """
    history = [version("a", node_id="mtr_7f3a9c"), version("b", agg="max")]

    assert shape(timeline(history, "metric.mtr_7f3a9c")) == (
        (("a", True), ("b", True)),
        (("a", "b", "name"),),
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


def test_identity_survives_a_gap_even_though_a_change_does_not() -> None:
    """The two halves of a gap pull in opposite directions, and both matter.

    A change must **not** cross a gap — the node was deleted and re-added. But
    identity must, or the node cannot be found again on the far side: here the
    metric is renamed while it is away, and only the id carried across the
    absence connects the two. Clearing the carried identity on an absence gives
    the same answer as this test's first half and the wrong one for its second,
    which is why one test asserts both.
    """
    history = [
        version("a"),
        version("b", node_id="mtr_7f3a9c", agg="max"),
        version("c", metric="something_else"),
        version("d", metric="revenue_gross", node_id="mtr_7f3a9c", agg="max"),
    ]

    # Asked by the name it had in `a`, which is not what `d` spells it: only
    # the id picked up in `b` and carried across `c` reaches the last entry.
    assert shape(timeline(history, "metric.gross_revenue")) == (
        (("a", True), ("b", True), ("c", False), ("d", True)),
        (("a", "b", "name"),),
    )


def test_a_columns_schema_moves_even_when_its_lowering_does_not() -> None:
    """The half of `_entity_field` the corpus cannot separate.

    In `evolution_v1`..`v2` the retype moves the `ColumnIR` *and* the
    `SourceColumnIR` — the cast is in the lowered expression — so that history
    cannot show which half of the pair is carrying the answer. `required:`
    moves the schema alone, and the lowering is asserted identical here so the
    premise is the test's rather than the reader's.
    """
    history = [version("a"), version("b", required=True)]
    lowerings = []
    for entry in history:
        _graph, ir = _compile(entry)
        entity = next(one for one in ir.entities if one.name == "order")
        lowerings.append(
            tuple(
                (source.relation, lowered)
                for source in entity.sources
                for lowered in source.columns
                if lowered.name == "amount"
            )
        )

    assert lowerings[0] == lowerings[1], "the premise: the expression does not move"
    assert shape(timeline(history, "order.amount")) == (
        (("a", True), ("b", True)),
        (("a", "b", "name"),),
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

    wired = twice(project, catalog, steps)
    assert shape(timeline(wired, node)) == ((("a", True), ("b", True)), ())

    with pytest.raises(UnknownStep, match="resolve_customers"):
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
    history = twice(project, catalog)
    rollups = twice(*load_fixture("rollup_mart"))

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


def test_an_unreachable_metric_is_compared_coarsely_and_that_is_stated() -> None:
    """The one place this walk is knowingly lossy, pinned rather than left in a
    docstring.

    `ir.metrics` holds only reachable metrics; an unreachable one survives as an
    `UnreachableMetric`, which records the name, the missing leaves and the
    chain — not the definition. So an edit that leaves the metric unreachable
    *for the same reason* is invisible here, and the change a reader is actually
    waiting for — it becoming reachable — is not.
    """
    project, catalog = load_fixture("ecom_basic")
    text = (FIXTURES / "ecom_basic" / "metrics.yaml").read_text()
    edited = text.replace('expr: "unit_price - cogs"', 'expr: "unit_price - cogs - 1"', 1)
    assert edited != text, "the edit the rest of this test rests on"
    moved = load_project({**fixture_sources("ecom_basic"), "metrics": edited})

    invisible = [
        SpecVersion(label="a", project=project, catalog=catalog),
        SpecVersion(label="b", project=moved, catalog=catalog),
    ]
    assert shape(timeline(invisible, "metric.margin")) == ((("a", True), ("b", True)), ())


def test_a_template_moving_moves_every_metric_built_from_it() -> None:
    """Why the comparison is over the IR and not over the documents.

    `gross_revenue` in this fixture is one line — `template: gross_revenue` —
    and its definition lives in the catalog. Editing the template moves the
    metric while `metrics.yaml` stays byte-identical, and a walk that diffed
    the authored spec would report nothing at all.
    """
    project, _ = load_fixture("ecom_basic")
    text = (FIXTURES / "ecom_basic" / "catalog.yaml").read_text()
    edited = text.replace('expr: "unit_price * quantity"', 'expr: "unit_price * quantity * 2"', 1)
    assert edited != text, "the edit the rest of this test rests on"

    history = [
        SpecVersion(label="a", project=project, catalog=load_catalog(text)),
        SpecVersion(label="b", project=project, catalog=load_catalog(edited)),
    ]

    assert shape(timeline(history, "metric.gross_revenue")) == (
        (("a", True), ("b", True)),
        (("a", "b", "name"),),
    )


def test_a_step_is_compared_by_its_manifest() -> None:
    """The kind `ecom_basic` has no instance of. A version bump moves the
    `StepIR` and the node stays put — `step_node` is keyed by `ref` alone,
    because a version bump does not move where a step sits in the lineage."""
    project, catalog = load_fixture("identity_resolution")
    steps = registry_for("identity_resolution")
    assert shape(timeline(twice(project, catalog, steps), "step.resolve_customers")) == (
        (("a", True), ("b", True)),
        (),
    )


def test_a_step_output_is_the_relation_it_produces() -> None:
    """`<relation>.<output name>` is an entity-field *node* and not a field.

    `_step_edges` mints one per `outputs:` entry, so `customer.customer` is the
    whole relation `resolve_customers` produces — and `customer` has no column
    called `customer`. Before this was handled, the lookup found nothing and
    the walk reported every step output as present in every version and changed
    in none, which is a wrong answer shaped exactly like a right one.
    """
    project, catalog = load_fixture("identity_resolution")
    steps = registry_for("identity_resolution")
    graph, ir = _compile(SpecVersion(label="x", project=project, catalog=catalog, steps=steps))

    assert Node(kind=NodeKind.ENTITY_FIELD, name="customer.customer") in graph.nodes
    entity = next(one for one in ir.entities if one.name == "customer")
    assert "customer" not in {column.name for column in entity.columns}
    assert _definition(*_kind_and_spelling("customer.customer"), ir, catalog) is entity


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


def test_the_id_namespaces_are_node_keys_own() -> None:
    """`_ID_NAMESPACE` names which kinds can carry an `id:` and under which key
    `node_keys` files them. A kind added *there* and not here would keep
    matching by name with nothing saying so — the id would be minted, the graph
    would use it, and this walk alone would ignore it.

    The wrong-key direction fails loudly already (a `KeyError` on the next
    call); this is the silent one.
    """
    project, catalog = load_fixture("ecom_basic")

    assert set(_ID_NAMESPACE.values()) == set(node_keys(project, catalog))


#: The two fixtures that exist to be refused, so they reach no IR and cannot be
#: swept below. Named rather than caught: a `try/except` around the sweep would
#: pass just as green on the day a fixture that used to compile stopped, which
#: is the failure this list makes visible.
REFUSED_AT_GUARDRAILS = frozenset({"fanout_trap", "scd2_mart_refusal"})


@pytest.mark.parametrize("fixture", spec_fixture_names())
def test_every_node_the_graph_carries_has_a_definition(fixture: str) -> None:
    """`_definition`'s remaining "not found" path is marked unreachable, and
    this is the measurement behind that claim rather than the argument for it.

    Every node of every fixture is looked up, and every kind but a source
    column must find a record. A kind that quietly stopped finding one would
    not raise: it would report the node present in every version and changed in
    none, which is the failure mode this whole walk has to avoid — and it is
    exactly what this sweep caught for step outputs, which live in the
    entity-field namespace as `<relation>.<output name>` and are relations
    rather than fields (`logs/T-0043.md`).
    """
    if fixture in REFUSED_AT_GUARDRAILS:
        with pytest.raises(GuardrailError):
            project, catalog = load_fixture(fixture)
            _compile(SpecVersion(label="x", project=project, catalog=catalog))
        return

    project, catalog = load_fixture(fixture)
    graph, ir = _compile(
        SpecVersion(label="x", project=project, catalog=catalog, steps=registry_for(fixture))
    )

    missing = [
        node.name
        for node in graph.nodes
        if node.kind is not NodeKind.SOURCE_COLUMN
        and _definition(*_kind_and_spelling(node.name), ir, catalog) is None
    ]

    assert missing == []


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


# ....................... #
# The closure (RFC 0064 D4)


def attributed(walk: Timeline) -> tuple[tuple[str, str, str, tuple[str, ...]], ...]:
    """Each change as ``(before, after, node, the facets it names)`` — the
    shape every closure claim is about, where `shape` deliberately drops the
    node because every change it describes is about the root."""

    return tuple(
        (
            change.before,
            change.after,
            change.node,
            tuple(f"{delta.facet.value}:{delta.field}" for delta in change.facets),
        )
        for change in walk.changes
    )


def test_a_metric_that_never_moved_reports_what_moved_beneath_it() -> None:
    """RFC 0064 D4, and §12's reason for shipping P1 and P2 together.

    `gross_revenue` is defined identically in all five versions of the corpus's
    own history. P1 answered "this has not changed", which is true about the
    metric's own record and false about the number it reports: `unit_price`
    is retyped under it between v1 and v2 and re-derived between v3 and v4.
    The single-node answer is the one `git log` already gives badly.
    """
    history = evolution()
    first, last = _compile(history[0])[1], _compile(history[-1])[1]
    assert (
        facets(
            _definition(NodeKind.METRIC, "gross_revenue", first, history[0].catalog),
            _definition(NodeKind.METRIC, "gross_revenue", last, history[-1].catalog),
        )
        == ()
    ), "the premise: the metric's own record is identical in v1 and v5"

    walk = timeline(history, "metric.gross_revenue")

    # Two hops down, through the catalog: nothing here is adjacent to the root.
    assert walk.node == "metric.gross_revenue"
    assert attributed(walk) == (
        ("v1", "v2", "order_item.unit_price", ("body:expr", "unit:type")),
        ("v3", "v4", "order_item.qty", ("metadata:renamed_from",)),
        (
            "v3",
            "v4",
            "order_item.unit_price",
            ("body:expr", "body:recipe_id"),
        ),
    )


def test_the_closure_is_upstream_only() -> None:
    """What the root is built *from*, never what is built from it.

    `$.price` is a bronze path that `unit_price` reads, so the two are one edge
    apart and the change is on the far side of it. Asked about the source
    column, the answer is nothing — and the same history asked about the metric
    above it names that very change. A closure walked in the wrong direction
    would report a definition moving under a node that has nothing under it.
    """
    walk = timeline(evolution(), "source.shop__order_lines.$.price")

    assert [entry.present for entry in walk.entries] == [True, True, True, False, False]
    assert walk.changes == ()


def test_one_boundary_carrying_several_nodes_is_sorted_by_node() -> None:
    """Deterministic within a boundary as well as across them. The holds carry
    across versions in the order nodes entered the closure, which is a fact
    about a version several entries back — so the report is sorted here rather
    than inheriting it."""
    walk = timeline(evolution(), "metric.gross_revenue")
    boundary = [change.node for change in walk.changes if (change.before, change.after) == ("v3", "v4")]

    assert boundary == sorted(boundary)
    assert len(boundary) > 1, "the assertion above is vacuous on one node"


def test_a_node_that_left_the_closure_carries_no_change_across_the_gap() -> None:
    """The root's own gap rule, applied per node.

    `net_revenue` is absent from v1, v2 and v5 of the corpus history, so its
    closure is undefined in those versions — and the change it does report sits
    between the two adjacent versions that both carried it, never spanning one
    that did not.
    """
    walk = timeline(evolution(), "metric.net_revenue")

    assert [entry.present for entry in walk.entries] == [False, False, True, True, False]
    assert {(change.before, change.after) for change in walk.changes} == {("v3", "v4")}


def test_the_same_history_walked_twice_answers_identically() -> None:
    """RFC 0064 §6's last test: the version graph is derived per invocation and
    persisted nowhere (D5).

    Written as *equality of two answers* rather than as "no file was written",
    because the second is what a reader would check and the first is what would
    actually break. A cache keyed wrongly, a held map leaking across calls, a
    set iterated into the output — each of them produces two different answers
    from one history, and none of them writes a file.
    """
    once = timeline(evolution(), "metric.gross_revenue")
    again = timeline(evolution(), "metric.gross_revenue")

    assert once == again
    assert attributed(once) == attributed(again)

def test_a_change_is_named_for_the_node_a_reader_knows() -> None:
    """A node that adopted an `id:` is reported under its **name**.

    The id is what makes the node trackable and the name is what makes the
    answer readable — RFC 0062 P3 settled the same question for `lineage`, and
    a timeline has the sharper version of it: a node that adopts an id partway
    through a history would otherwise change its spelling mid-answer.

    Pinned because nothing else could tell the two apart: no fixture in the
    corpus adopts an id, so a walk naming the id passed every other test here
    (`logs/T-0045.md`).
    """
    history = [
        version("a", node_id="mtr_7f3a9c"),
        version("b", node_id="mtr_7f3a9c", agg="max"),
    ]

    assert attributed(timeline(history, "metric.mtr_7f3a9c")) == (
        ("a", "b", "metric.gross_revenue", ("additivity:agg",)),
    )
