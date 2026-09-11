"""The single dependency DAG (RFC 0005 §5.1): node id scheme (pinned — it
reaches CircularDerivation messages and topo output), edge labels, sorting."""

from __future__ import annotations

import dataclasses

import pytest

from bloomery import Direction, build_project_ir, lineage, load_catalog, load_project
from bloomery.errors import BloomeryError, GuardrailError
from bloomery.ir import NODE_ID_PREFIXES
from bloomery.quality import QUALITY_MART
from bloomery.spec import Project
from bloomery.resolve.graph import (
    Edge,
    NodeKind,
    build_graph,
    canonical_field_node,
    entity_field_node,
    exposure_node,
    mart_node,
    metric_node,
    node_labels,
    source_column_node,
    step_node,
)
from bloomery.resolve.metrics import effective_metrics
from bloomery.spec.project import key, node_keys
from support.compiling import FIXTURES, fixture_sources, load_fixture

pytestmark = pytest.mark.unit

STEP_WIRING = """
steps_version: 1
steps:
  - use: resolve_customers@3
    inputs: {raw: silver.customer_raw}
    outputs: {customer: silver.customer}
"""

STEP_ENTITIES = """
spec_version: 1
entities:
  customer_raw:
    grain: one row per source row
    key: [source_id]
    fields:
      source_id: {type: string, required: true}
      email: {type: string}
"""


@pytest.fixture
def step_project() -> Project:
    return load_project({"entity_model": STEP_ENTITIES, "steps": STEP_WIRING})


def test_node_id_scheme_is_kind_prefixed() -> None:
    assert source_column_node("shopify__order_lines", "$.total").name == (
        "source.shopify__order_lines.$.total"
    )
    assert entity_field_node("order_item", "unit_price").name == "order_item.unit_price"
    assert canonical_field_node("unit_price").name == "canonical.unit_price"
    assert metric_node("gross_revenue").name == "metric.gross_revenue"


def test_ecom_graph_edges_and_labels() -> None:
    project, catalog = load_fixture("ecom_basic")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))

    labels = {(e.src.name, e.dst.name): e.label for e in graph.edges}
    # Recipe alias bindings: one edge per alias, labeled recipe:<id>.
    assert labels["source.shopify__order_lines.$.total", "order_item.unit_price"] == (
        "recipe:from_total"
    )
    assert labels["source.shopify__order_lines.$.qty", "order_item.unit_price"] == (
        "recipe:from_total"
    )
    # Direct mappings.
    assert labels["source.shopify__order_lines.$.qty", "order_item.quantity"] == "direct"
    assert labels["source.shopify__orders.$.id", "order.order_id"] == "direct"
    # canonical: links and metric requires.
    assert labels["order_item.unit_price", "canonical.unit_price"] == "canonical"
    assert labels["canonical.unit_price", "metric.gross_revenue"] == "requires"
    assert labels["metric.gross_revenue", "metric.average_order_value"] == "requires_metrics"
    # The unmapped canonical leaf has a node (from the catalog) but no
    # incoming canonical edge.
    assert canonical_field_node("cogs") in graph.nodes
    assert not any(e.dst.name == "canonical.cogs" and e.label == "canonical" for e in graph.edges)


def test_graph_collections_are_sorted() -> None:
    project, catalog = load_fixture("ecom_basic")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    assert [n.name for n in graph.nodes] == sorted(n.name for n in graph.nodes)
    keys = [(e.src.name, e.dst.name, e.label) for e in graph.edges]
    assert keys == sorted(keys)


def test_node_kinds_cover_the_step_free_vocabulary() -> None:
    """``ecom_basic`` wires no step, so it exercises every kind but one. The
    claim worth keeping is that the vocabulary is *covered*, which is why the
    step half is asserted separately rather than by weakening this to a
    subset check."""
    project, catalog = load_fixture("ecom_basic")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    assert {n.kind for n in graph.nodes} == set(NodeKind) - {NodeKind.STEP}


def test_an_exposure_is_the_graph_s_only_sink() -> None:
    """RFC 0056 §5.2. Both halves matter: the edges point *into* the exposure,
    and nothing points out of one — the downstream question stops there, which
    is the answer `--direction downstream` had no way to give before."""

    project, catalog = load_fixture("ecom_basic")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    review = exposure_node("weekly_revenue_review")

    incoming = {(e.src.name, e.label) for e in graph.edges if e.dst == review}
    assert incoming == {
        ("metric.gross_revenue", "depends_on"),
        ("metric.order_count", "depends_on"),
        # RFC 0067 §5.2: the mart leg shares the label, because it is the same
        # relation declared in the same `depends_on:` block.
        ("mart.order_items", "depends_on"),
    }
    assert not [e for e in graph.edges if e.src.kind is NodeKind.EXPOSURE]


def test_a_mart_only_exposure_now_has_an_upstream() -> None:
    """RFC 0067 §6, and the case RFC 0056 could not answer: `finance_extract`
    names no metric, so before the `mart` node it came back from an upstream
    walk as a node with nothing above it — a consumer whose whole declaration
    is what it reads, and the walk could see none of it.

    The second assertion is what makes the first worth having. The mart is not
    a leaf: the walk carries on through the metric it measures and into the
    source columns behind it, which is the reachability a `depends_on.marts`
    entry always implied and never had.
    """

    project, catalog = load_fixture("ecom_basic")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    extract = exposure_node("finance_extract")

    assert extract in graph.nodes
    incoming = {(e.src.name, e.label) for e in graph.edges if e.dst == extract}
    assert incoming == {("mart.order_items", "depends_on")}

    walk = lineage(graph, extract, Direction.UPSTREAM)
    reached = {n.name for n in walk.nodes}
    assert "mart.order_items" in reached
    assert "metric.gross_revenue" in reached
    assert "source.shopify__order_lines.$.total" in reached

    # And a project with no marts document at all builds no mart node, rather
    # than an empty one — the `is None` branch of the builder.
    bare_project, bare_catalog = load_fixture("minimal")
    bare = build_graph(bare_project, bare_catalog, effective_metrics(bare_project, bare_catalog))
    assert not [n for n in bare.nodes if n.kind is NodeKind.MART]


def test_a_metric_reaches_the_marts_that_carry_it() -> None:
    """The downstream half of RFC 0067 §1: `--direction downstream` from a
    metric now names the relation that will actually be rebuilt, not only the
    definitions and dashboards above it."""

    project, catalog = load_fixture("ecom_basic")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))

    walk = lineage(graph, metric_node("gross_revenue"), Direction.DOWNSTREAM)
    assert mart_node("order_items") in walk.nodes
    assert (
        Edge(src=metric_node("gross_revenue"), dst=mart_node("order_items"), label="measure")
        in walk.edges
    )


def test_a_mart_reaches_its_measures_upstream() -> None:
    """The direction §6 calls the one that makes the node worth having: from a
    relation, back to the definitions and the columns underneath it."""

    project, catalog = load_fixture("ecom_basic")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))

    walk = lineage(graph, mart_node("order_items"), Direction.UPSTREAM)
    reached = {n.name for n in walk.nodes}
    assert "metric.gross_revenue" in reached
    assert "canonical.unit_price" in reached
    assert "order_item.unit_price" in reached


def test_a_rollup_hangs_off_its_parent() -> None:
    """RFC 0067 §5.4, D5: one kind and one prefix for both, and the rollup's
    own measures draw no edge of their own — they are a subset of the parent's
    (`marts/rollup.py`), so a metric reaches the rollup through the parent.

    A reader asking what reads `order_items` wants `order_items_monthly` in
    the answer, which is the whole of why a rollup is a node.
    """

    project, catalog = load_fixture("rollup_mart")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    monthly = mart_node("order_items_monthly")

    incoming = {(e.src.name, e.label) for e in graph.edges if e.dst == monthly}
    assert incoming == {("mart.order_items", "rollup")}

    walk = lineage(graph, metric_node("gross_revenue"), Direction.DOWNSTREAM)
    assert monthly in walk.nodes


def test_the_quality_mart_is_not_a_node() -> None:
    """RFC 0067 D2 over D6, and the departure `logs/T-0039.md` records.

    `gold.mart_data_quality` is synthesized from the finished IR by
    `attach_quality_mart`, three stages after the graph is built, so no
    document this builder reads names it. It is absent by the ordinary rule —
    the builder reads `marts:` and it is not there — rather than by a filter,
    which is why nothing here names it but this test.
    """

    project, catalog = load_fixture("multi_source_quality")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))

    assert mart_node(QUALITY_MART) not in graph.nodes
    assert not [n for n in graph.nodes if n.name.startswith(f"mart.{QUALITY_MART}")]

    # The mart is absent; its metrics are declared and present, which is the
    # half §3 measured and the half that stays true.
    ir = build_project_ir(project, catalog)
    assert any(mart.name == QUALITY_MART for mart in ir.marts)


def test_a_mart_with_no_measure_and_no_rollup_still_exists() -> None:
    """A dimensional mart draws no edge at all — RFC 0010 D9 asks a date role
    only of a *measure-carrying* mart — so without the unconditional node it
    would be absent from `topo_order` and refused by `bloomery lineage`, for a
    relation the emitters write a model for."""

    project, catalog = load_fixture("ecom_basic")
    marts = project.marts
    assert marts is not None
    stripped = dataclasses.replace(
        project,
        marts=marts.model_copy(
            update={
                "marts": {
                    name: mart.model_copy(update={"measures": ()})
                    for name, mart in marts.marts.items()
                }
            }
        ),
        exposures=None,
    )
    graph = build_graph(stripped, catalog, effective_metrics(stripped, catalog))

    node = mart_node("order_items")
    assert node in graph.nodes
    assert not [e for e in graph.edges if node in (e.src, e.dst)]


def test_a_measure_naming_no_metric_is_a_node_here_and_a_refusal_later() -> None:
    """The `measure` leg draws its edge unconditionally, like the two legs into
    an exposure — and both halves of that have to be asserted together.

    The first half alone reads as a bug: `resolve()` succeeds and the walk
    shows `metric.<typo>`, a metric the project does not declare. What makes it
    the design rather than a hole is the second half — `_check_measures`
    refuses the same spec at LOWER, so no artifact is ever emitted from a name
    that resolves to nothing. The phantom is reachable only on a project that
    does not compile, which is exactly the case `bloomery lineage` exists to
    answer for (RFC 0031 D2, RFC 0067 D2).

    Filtering it here would instead hide a name the marts document plainly
    declares, and would make this leg disagree with the two beside it.
    """

    sources = fixture_sources("ecom_basic")
    sources["marts"] = sources["marts"].replace(
        "measures: [gross_revenue]", "measures: [revenue_gross]", 1
    )
    project = load_project(sources)
    _, catalog = load_fixture("ecom_basic")

    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    assert (
        Edge(
            src=metric_node("revenue_gross"),
            dst=mart_node("order_items"),
            label="measure",
        )
        in graph.edges
    )

    with pytest.raises(GuardrailError, match="measure names no declared metric"):
        build_project_ir(project, catalog)


def test_a_dangling_mart_dependency_still_draws_its_edge() -> None:
    """The graph is built at RESOLVE and `check_exposure_targets` refuses at
    GUARDRAILS, so a name that resolves to nothing reaches this builder. It
    draws the edge, exactly as the metric leg beside it does — filtering here
    would make the graph disagree with the document in the one window where
    `bloomery lineage` answers and a compile does not (logs/T-0039.md).
    """

    project, catalog = load_fixture("ecom_basic")
    exposures = project.exposures
    assert exposures is not None
    extract = exposures.exposures["finance_extract"]
    bogus = dataclasses.replace(
        project,
        exposures=exposures.model_copy(
            update={
                "exposures": {
                    "finance_extract": extract.model_copy(
                        update={
                            "depends_on": extract.depends_on.model_copy(
                                update={"marts": ("order_itmes",)}
                            )
                        }
                    )
                }
            }
        ),
    )
    graph = build_graph(bogus, catalog, effective_metrics(bogus, catalog))

    assert (
        Edge(
            src=mart_node("order_itmes"),
            dst=exposure_node("finance_extract"),
            label="depends_on",
        )
        in graph.edges
    )


def test_a_wired_step_is_a_first_class_node(step_project: Project) -> None:
    """RFC 0017 D11: steps are DAG citizens. Both edge directions matter — the
    input edge puts the step downstream of what fills it, the output edge puts
    its produced fields downstream of the step, and it is the second that lets
    `plan()` compute a backfill *across* a step (§4)."""
    graph = build_graph(step_project, None, ())
    step = step_node("resolve_customers")
    assert step in graph.nodes
    labels = {(e.src.name, e.dst.name, e.label) for e in graph.edges}
    # A step reads a relation *whole*, so every field of the input entity
    # feeds it — not a synthetic `customer_raw.*` node, which had no producer
    # and no consumer and made the lineage claim false.
    assert ("customer_raw.email", "step.resolve_customers", "step_input") in labels
    assert ("customer_raw.source_id", "step.resolve_customers", "step_input") in labels
    assert ("step.resolve_customers", "customer.customer", "step_output") in labels
    # Both ends: a regression reintroducing a `customer.*` *destination*
    # passed the one-sided version of this assertion.
    assert not any(
        endpoint.endswith(".*") for src, dst, _ in labels for endpoint in (src, dst)
    )


def test_a_step_with_no_wired_inputs_still_appears() -> None:
    """It exists in the lineage regardless; without the explicit node it would
    vanish from the topological order entirely (the catalog/metrics
    precedent)."""
    project = load_project(
        {
            "entity_model": "spec_version: 1\nentities: {}\n",
            "steps": (
                "steps_version: 1\nsteps:\n  - use: resolve_customers@3\n"
                "    outputs: {customer: silver.customer}\n"
            ),
        }
    )
    graph = build_graph(project, None, ())
    assert step_node("resolve_customers") in graph.nodes


# ....................... #
# Determinism when two kinds share a name (RFC 0003; logs/T-0005.md D-025)


#: An entity literally named `metric` with a field `revenue` produces the node
#: name `metric.revenue` — the same string `metric_node("revenue")` produces.
#: Entity-field ids carry no kind prefix, so they can collide with every other
#: kind's prefix: `metric.`, `canonical.`, `step.`, `source.`.
COLLIDING_ENTITY = """
spec_version: 1
entities:
  metric:
    grain: one row per thing
    key: [revenue]
    fields:
      revenue: {type: string}
"""
COLLIDING_MAPPING = """
mapping_version: 1
source: raw__things
target: metric
key:
  revenue: {from: "$.r", transform: [to_string]}
"""
COLLIDING_METRICS = """
metrics_version: 1
metrics:
  revenue:
    grain: thing
    additivity: additive
    agg: count
    expr: "revenue"
"""


def colliding_graph() -> object:
    project = load_project(
        {
            "entity_model": COLLIDING_ENTITY,
            "mapping_c": COLLIDING_MAPPING,
            "metrics": COLLIDING_METRICS,
        }
    )
    return build_graph(project, None, effective_metrics(project, None))


def test_two_kinds_can_share_a_node_name() -> None:
    """The premise. If this ever stops being true the ordering test below is
    vacuous, so it is asserted rather than assumed."""
    shared = [node for node in colliding_graph().nodes if node.name == "metric.revenue"]  # type: ignore[attr-defined]

    assert len(shared) == 2
    assert {node.kind for node in shared} == {NodeKind.ENTITY_FIELD, NodeKind.METRIC}


def test_nodes_sharing_a_name_are_ordered_by_kind_not_by_hash() -> None:
    """`build_graph` collects nodes in a `set` and sorts them.

    Sorted by `name` alone, two nodes sharing a name keep whatever relative
    order the set iteration gave — which varies with `PYTHONHASHSEED`, so the
    same specs produced different `Graph.nodes` in different processes. That is
    the invariant CLAUDE.md states as non-negotiable, and `topo_order` derives
    from this order, so it reaches emitted output.
    """
    graph = colliding_graph()
    shared = [node for node in graph.nodes if node.name == "metric.revenue"]  # type: ignore[attr-defined]

    # Deterministic and stated: ties break on the kind's value, ascending.
    assert [node.kind.value for node in shared] == sorted(node.kind.value for node in shared)


def test_node_order_is_identical_across_hash_seeds() -> None:
    """The cross-process form of the test above — the one that actually caught
    it, since a single process can produce the right order by luck."""
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    program = (
        "from bloomery import load_project;"
        "from bloomery.resolve.graph import build_graph;"
        "from bloomery.resolve.metrics import effective_metrics;"
        f"p = load_project({{'entity_model': {COLLIDING_ENTITY!r},"
        f" 'mapping_c': {COLLIDING_MAPPING!r}, 'metrics': {COLLIDING_METRICS!r}}});"
        "g = build_graph(p, None, effective_metrics(p, None));"
        "print([(n.kind.value, n.name) for n in g.nodes])"
    )
    outputs = {
        subprocess.run(  # noqa: S603
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        ).stdout
        for seed in ("0", "1", "42", "7", "12345", "999", "31337")
    }
    assert len(outputs) == 1, f"node order varied with the hash seed: {outputs}"


# ....................... #
# The reservation's drift gate (RFC 0051 §5.2, D8)


def test_every_prefixed_builder_uses_a_reserved_name() -> None:
    """The guardrail that reserves the names sits below ``resolve`` and
    cannot import this module, so the two lists are pinned together here
    rather than by an import. A node kind added with a new prefix fails this
    test instead of quietly escaping the reservation.

    ``entity_field_node`` is deliberately absent: it is the one builder that
    emits no prefix, which is the whole reason the others' are reserved.
    """
    ids = (
        source_column_node("shopify__orders", "$.total").name,
        canonical_field_node("unit_price").name,
        metric_node("gross_revenue").name,
        step_node("resolve_customers").name,
        mart_node("order_items").name,
        exposure_node("weekly_revenue_review").name,
    )
    assert {node_id.split(".", 1)[0] for node_id in ids} == set(NODE_ID_PREFIXES)
    assert entity_field_node("order_item", "unit_price").name == "order_item.unit_price"


# ....................... #
# RFC 0062 P1 — a stable id substitutes for the name


def _with_metric_ids(**ids: str) -> tuple[Project, object]:
    """``ecom_basic`` with an ``id:`` added to each named metric."""

    project, catalog = load_fixture("ecom_basic")
    sources = fixture_sources("ecom_basic")

    for name, value in ids.items():
        anchor = f"  {name}:\n"
        assert anchor in sources["metrics"], name
        sources["metrics"] = sources["metrics"].replace(anchor, f"{anchor}    id: {value}\n", 1)

    return load_project(sources), catalog


def test_an_unadopted_project_keys_every_node_by_name() -> None:
    """D3, at the level the substitution happens.

    The byte-exact promise rests on this: with no ``id:`` anywhere, the map is
    empty for every kind and ``key`` is the identity, so nothing downstream can
    take a different branch.
    """

    project, catalog = load_fixture("ecom_basic")
    ids = node_keys(project, catalog)

    assert ids == {"metric": {}, "canonical": {}, "step": {}}
    assert key("gross_revenue", ids["metric"]) == "gross_revenue"


def test_an_unadopted_project_has_no_labels() -> None:
    """The other side of D3, and the reason every caller reads this map as
    ``labels.get(node_id, node_id)``: with nothing adopted there is nothing to
    look up, and the node id *is* the name."""

    assert node_labels(*load_fixture("ecom_basic")) == {}


def test_a_label_maps_the_node_id_back_to_the_name() -> None:
    """§5.4's half that a person reads. The map is keyed by the id the graph
    actually minted, so a caller holding a `Node` can look it up without
    knowing how the id was built."""

    project, catalog = _with_metric_ids(gross_revenue="mtr_7f3a9c")

    assert node_labels(project, catalog) == {"metric.mtr_7f3a9c": "metric.gross_revenue"}


def test_the_labels_invert_exactly_what_the_graph_minted() -> None:
    """Every adopted node, in every kind that can adopt — and the ids are
    taken from the graph rather than from the spec, so the inversion is checked
    against what was actually built (D2: the id is substituted whole).

    Two kinds here and the third below, because `node_keys` files three and a
    label map that covered metrics alone would be silently right on every
    fixture this repository happens to have — `ecom_basic` wires no step.
    """
    sources = fixture_sources("ecom_basic")
    sources["metrics"] = sources["metrics"].replace(
        "  gross_revenue:\n", "  gross_revenue:\n    id: mtr_7f3a9c\n", 1
    )
    catalog_text = (FIXTURES / "ecom_basic" / "catalog.yaml").read_text().replace(
        "  unit_price:\n", "  unit_price:\n    id: cf_9b2e14\n", 1
    )
    project, catalog = load_project(sources), load_catalog(catalog_text)
    labels = node_labels(project, catalog)
    minted = {node.name for node in build_graph(project, catalog, effective_metrics(project, catalog)).nodes}

    assert labels == {
        "metric.mtr_7f3a9c": "metric.gross_revenue",
        "canonical.cf_9b2e14": "canonical.unit_price",
    }
    assert set(labels) <= minted, "a label for an id the graph never built"


def test_a_step_ref_is_labelled_by_its_ref() -> None:
    """The third kind, and the one whose *name* is not called a name.

    A step node is keyed by `ref` (`step_node`'s own rule: a version bump does
    not move where a step sits), so the label is `step.<ref>` — not the `use:`
    spelling, and not `ref@version`.
    """
    sources = fixture_sources("identity_resolution")
    assert "    id:" not in sources["steps"]
    sources["steps"] = sources["steps"].replace(
        "  - use: resolve_customers@4\n", "  - use: resolve_customers@4\n    id: stp_44c1\n", 1
    )
    project = load_project(sources)
    catalog_text = (FIXTURES / "identity_resolution" / "catalog.yaml").read_text()

    assert node_labels(project, load_catalog(catalog_text)) == {
        "step.stp_44c1": "step.resolve_customers"
    }


def test_a_label_that_is_another_nodes_id_is_not_a_label() -> None:
    """A label has to be unambiguous or it is worse than the id it replaces.

    Two metrics can legally swap: `alpha` minting `id: mtr_beta` and `gamma`
    minting `id: alpha`. Nothing refuses it — the *node ids* are `metric.beta`
    and `metric.alpha`, which do not collide, and the per-document guard
    compares `id or name`. But `alpha`'s **label** is then `metric.alpha`,
    which is `gamma`'s node id: a reader shown `metric.alpha` cannot tell which
    node it means, and `--node metric.alpha` resolves to the other one.

    So the label is dropped and that node renders as its id. Silence about the
    name is recoverable; a name that reads as a different node is not.
    """
    sources = fixture_sources("ecom_basic")
    sources["metrics"] = """
metrics_version: 1
metrics:
  alpha:
    id: mtr_beta
    grain: order_item
    additivity: additive
    agg: sum
    expr: "quantity"
  gamma:
    id: alpha
    grain: order_item
    additivity: additive
    agg: sum
    expr: "quantity"
"""
    project = load_project(sources)
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())

    # `gamma` keeps its label: `metric.gamma` names no node.
    assert node_labels(project, catalog) == {"metric.alpha": "metric.gamma"}


def test_an_adopted_id_replaces_the_name_in_the_node_id() -> None:
    project, catalog = _with_metric_ids(gross_revenue="mtr_7f3a9c")
    metrics = effective_metrics(project, catalog)
    graph = build_graph(project, catalog, metrics)
    names = {node.name for node in graph.nodes}

    assert "metric.mtr_7f3a9c" in names
    assert "metric.gross_revenue" not in names


def test_a_reference_by_name_reaches_the_node_its_id_renamed() -> None:
    """The edge case §5.2's "nothing else moves" understates.

    ``average_order_value`` names ``gross_revenue`` in ``requires_metrics``,
    from a different block than the one carrying the id. Substituting only at
    the definition would leave this edge pointing at ``metric.gross_revenue``,
    a vertex nothing built — a graph split in two with no error anywhere.
    """

    project, catalog = _with_metric_ids(gross_revenue="mtr_7f3a9c")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))

    into_aov = {
        edge.src.name for edge in graph.edges if edge.dst.name == "metric.average_order_value"
    }

    assert "metric.mtr_7f3a9c" in into_aov
    assert "metric.gross_revenue" not in into_aov

    # And the mart's `measures:` entry, which names the metric from a fourth
    # document and is the reference RFC 0067 §5.2 added.
    into_mart = {edge.src.name for edge in graph.edges if edge.dst.name == "mart.order_items"}
    assert into_mart == {"metric.mtr_7f3a9c"}


def test_a_rename_moves_the_label_and_not_the_node() -> None:
    """§6's traversal test: the same id, a different name, the same edges."""

    project, catalog = _with_metric_ids(gross_revenue="mtr_7f3a9c")
    before = build_graph(project, catalog, effective_metrics(project, catalog))

    sources = fixture_sources("ecom_basic")
    sources["metrics"] = sources["metrics"].replace(
        "  gross_revenue:\n", "  revenue_gross:\n    id: mtr_7f3a9c\n", 1
    )
    sources["metrics"] = sources["metrics"].replace(
        "requires_metrics: [gross_revenue, order_count]",
        "requires_metrics: [revenue_gross, order_count]",
        1,
    )
    # An exposure names a metric from a third document, so a rename reaches
    # here too — and that is the half of RFC 0062 §5.2 the edge into an
    # exposure exercises: the id belongs to the definition, so this reference
    # spells the *new* name and still resolves to the same node.
    sources["exposures"] = sources["exposures"].replace(
        "metrics: [gross_revenue, order_count]",
        "metrics: [revenue_gross, order_count]",
        1,
    )
    # A mart's `measures:` is a fourth document naming the same metric, and the
    # `measure` edge RFC 0067 §5.2 draws from it is a *reference* for exactly
    # the reason the two above are. Renaming everywhere but here would leave
    # this edge sourced at a vertex nothing built.
    sources["marts"] = sources["marts"].replace(
        "measures: [gross_revenue]", "measures: [revenue_gross]", 1
    )
    renamed = load_project(sources)
    after = build_graph(renamed, catalog, effective_metrics(renamed, catalog))

    assert {(e.src.name, e.dst.name, e.label) for e in before.edges} == {
        (e.src.name, e.dst.name, e.label) for e in after.edges
    }


def test_an_id_is_substituted_whole_and_never_parsed() -> None:
    """D2 and §6: opaque means opaque.

    A traversal-shaped value reaches a node id and nothing else — no path is
    resolved from it, and the dots do not split it into segments the way
    ``source.<relation>.<path>`` is built.
    """

    project, catalog = _with_metric_ids(gross_revenue="../../etc/passwd")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))

    assert "metric.../../etc/passwd" in {node.name for node in graph.nodes}


def test_an_authored_id_opens_no_route_to_the_entity_field_namespace() -> None:
    """§6's last test, which the existing reservation already answers.

    An entity field is ``<entity>.<field>`` **bare**; every other id carries a
    kind prefix. An id can put anything after that prefix and never remove it,
    so no authored value reaches the bare form — the collision RFC 0051 D6-D8
    closes stays closed, and this says so rather than leaving a reader to
    re-derive it.
    """

    project, catalog = _with_metric_ids(gross_revenue="order_item.unit_price")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    names = {node.name for node in graph.nodes}

    assert "metric.order_item.unit_price" in names
    assert "order_item.unit_price" in names
    assert len({n for n in names if n.endswith("order_item.unit_price")}) == 2


def test_the_whole_fixture_corpus_is_unadopted() -> None:
    """§6's byte-exact opt-out, stated as the thing that makes it true.

    Every golden in the tree was generated before this feature existed, and they
    all still pass — which is evidence only for as long as no fixture adopts an
    ``id:``. The day one does, its artifacts are the ones that have to be
    re-examined, and this fails then rather than letting a golden be regenerated
    against a changed identity model without anybody saying so.
    """

    adopted: dict[str, dict[str, dict[str, str]]] = {}

    for path in sorted(FIXTURES.iterdir()):
        if not path.is_dir() or not list(path.glob("*.yaml")):
            continue
        try:
            project, catalog = load_fixture(path.name)
        except BloomeryError:
            continue
        ids = node_keys(project, catalog)
        if any(ids.values()):
            adopted[path.name] = ids

    assert adopted == {}, f"a fixture adopted an id: {adopted}"


def test_a_canonical_id_is_substituted_and_its_references_follow() -> None:
    """The canonical kind, which the metric tests do not reach.

    ``requires`` names a canonical field from the metrics document while the
    ``id:`` sits in the catalog — the same cross-document reference the metric
    case has, one kind over. Removing the substitution from this edge left every
    metric test green (`logs/T-0032.md`), because none of them adopted a
    canonical id.
    """

    project, _ = load_fixture("ecom_basic")
    catalog_text = (FIXTURES / "ecom_basic" / "catalog.yaml").read_text()
    assert "  unit_price:\n" in catalog_text
    catalog = load_catalog(
        catalog_text.replace("  unit_price:\n", "  unit_price:\n    id: cnl_9b2\n", 1)
    )

    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    names = {node.name for node in graph.nodes}
    into_revenue = {
        edge.src.name for edge in graph.edges if edge.dst.name == "metric.gross_revenue"
    }

    assert "canonical.cnl_9b2" in names
    assert "canonical.unit_price" not in names
    assert "canonical.cnl_9b2" in into_revenue


def test_a_step_id_is_substituted_and_its_wiring_follows() -> None:
    """The step kind, likewise unreached by the metric tests.

    A step node is keyed by its ``ref``, and an adopted id replaces that ref
    everywhere the wiring appears — the node itself and the edges a step input
    draws from another step's output.
    """

    project = load_project(
        {
            "entity_model": STEP_ENTITIES,
            "steps": STEP_WIRING.replace(
                "  - use: resolve_customers@3\n",
                "  - use: resolve_customers@3\n    id: stp_44c\n",
                1,
            ),
        }
    )
    graph = build_graph(project, None, effective_metrics(project, None))
    names = {node.name for node in graph.nodes}

    assert "step.stp_44c" in names
    assert "step.resolve_customers" not in names


def test_a_step_output_link_reaches_the_canonical_field_by_id() -> None:
    """The twin of the mapping-link site, and it needed its own fixture.

    A step wiring's ``canonical:`` block links a produced column to a canonical
    field — a third place a canonical name is referenced, from a document that
    is neither the catalog nor the metrics. The mapping-link bug was found by
    covering the canonical kind at all; this one survived the re-sweep because
    the step fixture used above declares no ``canonical:`` block
    (`logs/T-0032.md`).
    """

    project, _ = load_fixture("identity_resolution")
    catalog_text = (FIXTURES / "identity_resolution" / "catalog.yaml").read_text()
    assert "  customer_ref:\n" in catalog_text
    catalog = load_catalog(
        catalog_text.replace("  customer_ref:\n", "  customer_ref:\n    id: cnl_ref\n", 1)
    )

    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    linked = {
        edge.dst.name
        for edge in graph.edges
        if edge.label == "canonical" and edge.src.name.endswith("canonical_id")
    }

    assert linked == {"canonical.cnl_ref"}
