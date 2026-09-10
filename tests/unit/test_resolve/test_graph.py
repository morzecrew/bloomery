"""The single dependency DAG (RFC 0005 §5.1): node id scheme (pinned — it
reaches CircularDerivation messages and topo output), edge labels, sorting."""

from __future__ import annotations

import pytest

from bloomery import load_catalog, load_project
from bloomery.errors import BloomeryError
from bloomery.ir import NODE_ID_PREFIXES
from bloomery.spec import Project
from bloomery.resolve.graph import (
    NodeKind,
    build_graph,
    canonical_field_node,
    entity_field_node,
    exposure_node,
    metric_node,
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
    }
    assert not [e for e in graph.edges if e.src.kind is NodeKind.EXPOSURE]


def test_a_mart_only_exposure_is_a_node_with_no_edge() -> None:
    """`depends_on.marts` draws no edge — a mart is not a node of this graph
    (logs/T-0038.md) — so an exposure naming only marts would exist nowhere at
    all: absent from `topo_order`, and refused by `bloomery lineage` as an
    unknown node, for a consumer the spec declares.

    Named for the shape rather than for the fixture, because the shape is what
    a future `depends_on` kind would break.
    """

    project, catalog = load_fixture("ecom_basic")
    graph = build_graph(project, catalog, effective_metrics(project, catalog))
    extract = exposure_node("finance_extract")

    assert extract in graph.nodes
    assert not [e for e in graph.edges if extract in (e.src, e.dst)]


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
