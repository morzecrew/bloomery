"""The single dependency DAG (RFC 0005 §5.1): one graph over source columns,
mapped entity fields, catalog canonical fields, metrics, the gold relations
that carry them (RFC 0067 §5.1) and the consumers that read those
(RFC 0056 §5.2) — reachability, cycles, topo order, and (later) guardrail
traversal all read the same structure, so they cannot disagree about what
depends on what (RFC 0005 D1).

Node ids are kind-prefixed dotted names, pinned by tests because they reach
``CircularDerivation`` messages and topo output (RFC 0005 §9).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from bloomery.spec.catalog import Catalog
from bloomery.spec.mapping import ALIAS_BOUND, RecipeFieldMapping
from bloomery.spec.project import Project, key, node_keys

if TYPE_CHECKING:
    from bloomery.resolve.metrics import EffectiveMetric
    from bloomery.spec.mapping import Mapping

# ----------------------- #

__all__ = [
    "Edge",
    "Graph",
    "Node",
    "NodeKind",
    "build_graph",
    "canonical_field_node",
    "entity_field_node",
    "exposure_node",
    "mart_node",
    "metric_node",
    "node_labels",
    "source_column_node",
    "step_node",
]


class NodeKind(StrEnum):
    """The node kinds of the dependency DAG (RFC 0005 §5.1; ``STEP`` added by
    RFC 0017 §5.6, D11; ``EXPOSURE`` by RFC 0056 §5.2; ``MART`` by RFC 0067
    §5.1)."""

    SOURCE_COLUMN = "source_column"
    ENTITY_FIELD = "entity_field"
    CANONICAL_FIELD = "canonical_field"
    METRIC = "metric"
    STEP = "step"
    MART = "mart"
    EXPOSURE = "exposure"


# ....................... #


@dataclass(frozen=True, slots=True)
class Node:
    """One DAG node; ``name`` is the canonical kind-prefixed dotted id."""

    kind: NodeKind
    name: str


# ....................... #


@dataclass(frozen=True, slots=True)
class Edge:
    """One dependency edge, pointing dependency → dependent (RFC 0005 §5.1)."""

    src: Node
    dst: Node
    #: The label *family* is the part before any ``:`` — see
    #: :data:`_EDGE_SHAPES` for the closed set of
    #: ``(family, src kind, dst kind)`` triples and what each one means.
    #: Two families are parameterised: ``recipe:<id>`` and ``step:<ref@version>``.
    label: str


# ....................... #


#: Every ``(label family, src kind, dst kind)`` this module can emit
#: (RFC 0031 §5.3, D6) — from the three ``_*_edges`` builders below and from
#: :func:`build_graph`'s own constructions. The label family is the part before any ``:``, so
#: the parameterised ``recipe:<id>`` and ``step:<ref@version>`` contribute
#: ``recipe`` and ``step``.
#:
#: **Read off the builders, never off the corpus.** A vocabulary compiled from
#: fixtures can only contain what some fixture exercises, and that method cost
#: RFC 0031's first draft two entries: ``identity_resolution`` is the only
#: project wiring a step and wires exactly one, so neither ``step → step`` form
#: occurs; and no fixture declares a ``sql_macro`` field, so ``step:`` occurs
#: nowhere at all. ``tests/unit/test_resolve/test_edge_vocabulary.py`` guards
#: this from both sides — the corpus is a subset of it, and so is an AST walk
#: over every ``Edge(...)`` construction in this module.
_EDGE_SHAPES: Final[frozenset[tuple[str, NodeKind, NodeKind]]] = frozenset(
    {
        # A mapped field: straight from a source column, via a catalog recipe,
        # or via a Tier 1 `sql_macro` (RFC 0017 D50).
        ("direct", NodeKind.SOURCE_COLUMN, NodeKind.ENTITY_FIELD),
        ("recipe", NodeKind.SOURCE_COLUMN, NodeKind.ENTITY_FIELD),
        ("step", NodeKind.SOURCE_COLUMN, NodeKind.ENTITY_FIELD),
        # The field links to a catalog canonical, which is what makes it
        # available to a metric.
        ("canonical", NodeKind.ENTITY_FIELD, NodeKind.CANONICAL_FIELD),
        ("requires", NodeKind.CANONICAL_FIELD, NodeKind.METRIC),
        ("requires_metrics", NodeKind.METRIC, NodeKind.METRIC),
        # A step reads a mapped entity whole, or another step's output. The
        # second form includes the self-edge a self-referencing binding emits
        # so that cycle detection has something to find — which means it is a
        # shape `toposort` always raises on, never one `lineage()` sees.
        ("step_input", NodeKind.ENTITY_FIELD, NodeKind.STEP),
        ("step_input", NodeKind.STEP, NodeKind.STEP),
        ("step_output", NodeKind.STEP, NodeKind.ENTITY_FIELD),
        # A mart embeds the metric it carries as a measure, at the mart's own
        # grain (RFC 0067 D1). Dependency → dependent like every shape above
        # it: redefining the metric restates the mart's column, while a mart
        # moving leaves the metric's definition where it was.
        ("measure", NodeKind.METRIC, NodeKind.MART),
        # A rollup is a mart of a mart (RFC 0058 §5.2, RFC 0067 §5.4). One kind
        # and one prefix for both, which D10 of that RFC makes safe: a rollup
        # may not take a mart's name.
        ("rollup", NodeKind.MART, NodeKind.MART),
        # A declared consumer reads a metric or a mart (RFC 0056 §5.2,
        # RFC 0067 §5.2). One label for both because it is one relation from
        # two sources — the exposure declared each of them, in the same
        # `depends_on:` block — so an exposure naming a metric *and* the mart
        # serving it shows two edges, which is two declarations rather than a
        # double count.
        ("depends_on", NodeKind.METRIC, NodeKind.EXPOSURE),
        ("depends_on", NodeKind.MART, NodeKind.EXPOSURE),
    }
)


@dataclass(frozen=True, slots=True)
class Graph:
    """The assembled DAG: nodes sorted by name, edges sorted by
    (src, dst, label) — deterministic by construction (RFC 0003 §5.3)."""

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]


# ....................... #


def source_column_node(relation: str, path: str) -> Node:
    """A bronze extraction, e.g. ``source.shopify__order_lines.$.total``."""

    return Node(kind=NodeKind.SOURCE_COLUMN, name=f"source.{relation}.{path}")


# ....................... #


def entity_field_node(entity: str, field: str) -> Node:
    """A mapped entity field, e.g. ``order_item.unit_price``."""

    return Node(kind=NodeKind.ENTITY_FIELD, name=f"{entity}.{field}")


# ....................... #


def canonical_field_node(name: str) -> Node:
    """A catalog canonical field, e.g. ``canonical.unit_price``."""

    return Node(kind=NodeKind.CANONICAL_FIELD, name=f"canonical.{name}")


# ....................... #


def metric_node(name: str) -> Node:
    """A metric, e.g. ``metric.gross_revenue``."""

    return Node(kind=NodeKind.METRIC, name=f"metric.{name}")


# ....................... #


def step_node(ref: str) -> Node:
    """A referenced implementation, e.g. ``step.resolve_customers``
    (RFC 0017 §5.6, D11).

    Keyed by ``ref`` alone, not ``ref@version``: the node is the *place in the
    lineage* where a step sits, and a version bump does not move it. What the
    version changes is the step's fingerprint, which is `plan()`'s business
    (D6) — encoding it in the node id would instead make an upgrade read as a
    node removed and a different one added, breaking the very lineage this
    node exists to preserve.
    """

    return Node(kind=NodeKind.STEP, name=f"step.{ref}")


# ....................... #


def mart_node(name: str) -> Node:
    """A gold relation, e.g. ``mart.order_items`` (RFC 0067 §5.1).

    Named for the mart's **spec** spelling, not for the relation
    ``ctx.naming.relation(...)`` builds from it — every other node in this
    graph is named the way its document names it, and a naming policy is an
    emission concern that would otherwise reach lineage ids.

    A rollup gets one of these too, under the same prefix: both are relations
    of the gold layer, and RFC 0058 D10 refuses a rollup that takes a mart's
    name, so the one namespace cannot collide.
    """

    return Node(kind=NodeKind.MART, name=f"mart.{name}")


# ....................... #


def exposure_node(name: str) -> Node:
    """A declared consumer, e.g. ``exposure.weekly_revenue_review``
    (RFC 0056 §5.2).

    The one node kind nothing is ever downstream of. Every other kind is
    something this project builds, and so can feed something else; an exposure
    is outside the project, reading what was built — which is exactly the
    answer ``--direction downstream`` had no way to give before.
    """

    return Node(kind=NodeKind.EXPOSURE, name=f"exposure.{name}")


# ....................... #


def _mapping_edges(
    mapping: Mapping, canonical_by_field: dict[str, str | None], ids: dict[str, str]
) -> list[Edge]:
    edges: list[Edge] = []

    for field_name, key_field in mapping.key.items():
        edges.append(
            Edge(
                src=source_column_node(mapping.source, key_field.from_),
                dst=entity_field_node(mapping.target, field_name),
                label="direct",
            )
        )

    for field_name, field_mapping in mapping.fields.items():
        dst = entity_field_node(mapping.target, field_name)
        if isinstance(field_mapping, ALIAS_BOUND):
            label = (
                f"recipe:{field_mapping.recipe}"
                if isinstance(field_mapping, RecipeFieldMapping)
                else f"step:{field_mapping.step}"
            )
            edges.extend(
                Edge(src=source_column_node(mapping.source, path), dst=dst, label=label)
                for path in field_mapping.from_.values()
            )
        else:
            edges.append(
                Edge(
                    src=source_column_node(mapping.source, field_mapping.from_),
                    dst=dst,
                    label="direct",
                )
            )

    for field_name in sorted({*mapping.key, *mapping.fields}):
        canonical = canonical_by_field.get(field_name)
        if canonical is not None:
            edges.append(
                Edge(
                    src=entity_field_node(mapping.target, field_name),
                    dst=canonical_field_node(key(canonical, ids)),
                    label="canonical",
                )
            )

    return edges


# ....................... #


def _step_edges(project: Project, ids: dict[str, dict[str, str]]) -> list[Edge]:
    """Wire each step between what fills its inputs and what it produces
    (RFC 0017 §5.6, D11).

    Both directions matter and for different reasons. Input edges put the step
    *downstream* of whatever fills its inputs, so a change upstream reaches it
    in topological order — and so a **cycle between two steps** is a cycle in
    this graph rather than a pipeline that deadlocks at run time. Output edges
    put the produced relation downstream of the step, which is what lets
    `plan()` compute a backfill *across* it (§4).

    An input is resolved two ways, and the second is the one that took a
    regression to learn. A binding naming a **mapped entity** draws an edge
    from each of that entity's fields — a step reads a relation whole. A
    binding naming another **step's output** draws an edge from that step's
    node directly, because a step-produced relation is not an entity and
    looking only in the entity table silently produced no edge at all, which
    is exactly the common case (one step feeding another) and exactly where
    cycle detection was lost.
    """

    if project.steps is None:
        return []

    entities = project.entity_model.entities
    producer_of: dict[str, str] = {
        relation.rsplit(".", 1)[-1]: wiring.ref
        for wiring in project.steps.steps
        for relation in wiring.outputs.values()
    }
    edges: list[Edge] = []

    for wiring in project.steps.steps:
        node = step_node(key(wiring.ref, ids["step"]))
        for _name, bound in sorted(wiring.inputs.items()):
            relation = bound.rsplit(".", 1)[-1]
            producer = producer_of.get(relation)
            if producer is not None and producer != wiring.ref:
                edges.append(
                    Edge(src=step_node(key(producer, ids["step"])), dst=node, label="step_input")
                )
                continue
            entity = entities.get(relation)
            if entity is None:
                # A self-referencing binding lands here too, and must still
                # produce the self-edge the cycle check reads.
                if producer == wiring.ref:
                    edges.append(Edge(src=node, dst=node, label="step_input"))
                continue
            edges.extend(
                Edge(src=entity_field_node(relation, field), dst=node, label="step_input")
                for field in sorted({*entity.fields, *entity.key})
            )
        for output_name, relation in sorted(wiring.outputs.items()):
            produced = relation.rsplit(".", 1)[-1]
            edges.append(
                Edge(src=node, dst=entity_field_node(produced, output_name), label="step_output")
            )
            # A declared `canonical:` link makes the column *available*, which
            # is the whole of what a metric's reachability asks (RFC 0005
            # §5.3, RFC 0017 D49). The column node hangs off the step for the
            # same reason the output node does — so the link is reachable in
            # topological order rather than floating free of its producer.
            for column, canonical in sorted(wiring.canonical.get(output_name, {}).items()):
                field = entity_field_node(produced, column)
                edges.append(Edge(src=node, dst=field, label="step_output"))
                edges.append(
                    Edge(
                        src=field,
                        dst=canonical_field_node(key(canonical, ids["canonical"])),
                        label="canonical",
                    )
                )

    return edges


# ....................... #


def _mart_edges(project: Project, ids: dict[str, dict[str, str]]) -> list[Edge]:
    """Wire the gold layer from the **authored** marts document (RFC 0067 D2).

    Everything here is read off `marts:` — a mart's declared `measures:`, and a
    rollup's `of:`. Nothing reads a :class:`~bloomery.ir.MartColumnIR`, which
    is the flattener's output and does not exist for another two stages; that
    is what keeps `bloomery lineage` able to answer on a project a guardrail
    would refuse, which is when the question is most worth asking.

    The consequence is stated rather than mitigated (D3): a mart **dimension**
    column that no metric reads — `order.status`, flattened and grouped by —
    is reached by a change in fact and not in this graph. Closing that needs
    per-column edges, and per-column edges need LOWER.

    A rollup draws no `measure` edge of its own. Its measures are a subset of
    its parent's — ``marts/rollup.py`` refuses any that are not — so every one
    of them already reaches it through the parent's `measure` edge and the
    `rollup` edge, and a second path would state that subset relation twice.
    """

    if project.marts is None:
        return []

    edges: list[Edge] = []

    for name, mart in sorted(project.marts.marts.items()):
        dst = mart_node(name)
        # A measure names a metric from a document that is not the one
        # carrying its `id:`, so it is a *reference* and goes through the id
        # map like every other one (RFC 0062 §5.2). A mart itself has no
        # `id:` — RFC 0067 §8 leaves that to 0062's own surface — so the mart
        # side is the spec's spelling.
        edges.extend(
            Edge(src=metric_node(key(measure, ids["metric"])), dst=dst, label="measure")
            for measure in sorted(mart.measures)
        )

    edges.extend(
        Edge(src=mart_node(rollup.of), dst=mart_node(name), label="rollup")
        for name, rollup in sorted(project.marts.rollups.items())
    )

    return edges


# ....................... #


def node_labels(project: Project, catalog: Catalog | None) -> dict[str, str]:
    """Node id to the **same node spelled with its name**, for every node that
    adopted an `id:` (RFC 0062 §5.4).

    Both sides are node ids: `metric.mtr_7f3a9c` maps to `metric.gross_revenue`
    and not to `gross_revenue`. A bare name would make an adopted node the only
    one in a lineage walk without a kind prefix, so the edge list would read
    `canonical.quantity --requires--> gross_revenue` — two spellings in one
    column, which is harder to read than either. The label is what the id would
    have been had the project adopted nothing, which is also what makes it
    substitutable wherever an id appears.

    The inverse of what :func:`~bloomery.spec.project.node_keys` does for the
    builders above, and built **with those builders** rather than by joining a
    prefix to a string: an id is minted by exactly one function per kind, so
    inverting it anywhere else is a second spelling that can drift from the
    first. A kind whose constructor moves takes this with it.

    Only adopted nodes appear, and only where the label is unambiguous — a
    label that is itself a node id of the same kind is dropped, because a
    reader shown it would be shown a string naming a different node. A project
    that mints no id gets an empty map, and every caller reads it as
    ``labels.get(node_id, node_id)`` — so the unadopted case costs a lookup and
    no branch (D3), and a dropped label costs the same.

    Names rather than ids are what a person reads: `metric.mtr_7f3a9c` is a
    key, and printing it where `metric.gross_revenue` belongs trades the
    readability the name exists for against a property only tooling needs. The
    machine surfaces carry both.
    """

    ids = node_keys(project, catalog)
    metrics = {} if project.metric_set is None else project.metric_set.metrics
    canonical = {} if catalog is None else catalog.canonical_fields
    steps = () if project.steps is None else project.steps.steps

    labels = {
        **{
            metric_node(adopted).name: metric_node(name).name
            for name, adopted in ids["metric"].items()
        },
        **{
            canonical_field_node(adopted).name: canonical_field_node(name).name
            for name, adopted in ids["canonical"].items()
        },
        **{step_node(adopted).name: step_node(ref).name for ref, adopted in ids["step"].items()},
    }

    # A label that is itself a node id names two things, and the one a reader
    # would act on is the wrong one. Two metrics can legally swap — `alpha`
    # minting `id: mtr_beta` while `gamma` mints `id: alpha` — because the
    # *node ids* do not collide and the per-document guard compares `id or
    # name`. `alpha`'s label is then `gamma`'s node id, and `--node` resolves
    # that string to `gamma`. Such a label is dropped and the node renders as
    # its id: saying nothing about the name is recoverable, and a name that
    # reads as a different node is not.
    minted = {
        *(metric_node(key(name, ids["metric"])).name for name in metrics),
        *(canonical_field_node(key(name, ids["canonical"])).name for name in canonical),
        *(step_node(key(wiring.ref, ids["step"])).name for wiring in steps),
    }

    return {node_id: label for node_id, label in labels.items() if label not in minted}


# ....................... #


def build_graph(
    project: Project,
    catalog: Catalog | None,
    metrics: tuple[EffectiveMetric, ...],
) -> Graph:
    """Assemble the DAG from reference-clean specs (RFC 0005 §5.1).

    Source columns feed entity fields (transform chains or recipe ``from``
    aliases); mapped entity fields feed canonical fields (``canonical:``
    links); canonical fields feed metrics (``requires``); metrics feed
    metrics (``requires_metrics``); metrics feed the marts that carry them as
    measures, and marts feed rollups of themselves (RFC 0067 §5.2); metrics
    and marts feed the exposures that declare them (RFC 0056 §5.2).
    """
    ids = node_keys(project, catalog)
    edges: list[Edge] = []
    edges.extend(_step_edges(project, ids))
    edges.extend(_mart_edges(project, ids))

    for mapping in project.mappings:
        entity = project.entity_model.entities[mapping.target]
        canonical_by_field = {name: field.canonical for name, field in entity.fields.items()}
        edges.extend(_mapping_edges(mapping, canonical_by_field, ids["canonical"]))

    for metric in metrics:
        dst = metric_node(key(metric.name, ids["metric"]))
        edges.extend(
            Edge(src=canonical_field_node(key(leaf, ids["canonical"])), dst=dst, label="requires")
            for leaf in metric.requires
        )
        edges.extend(
            Edge(src=metric_node(key(required, ids["metric"])), dst=dst, label="requires_metrics")
            for required in metric.requires_metrics
        )

    if project.exposures is not None:
        # The metric name goes through `ids["metric"]` like every other
        # *reference* does: an exposure names a metric from a document that is
        # not the one carrying its `id:`, so substituting only at the
        # definition would leave this edge pointing at a vertex nothing built
        # (RFC 0062 §5.2).
        edges.extend(
            Edge(
                src=metric_node(key(metric, ids["metric"])),
                dst=exposure_node(name),
                label="depends_on",
            )
            for name, exposure in sorted(project.exposures.exposures.items())
            for metric in sorted(exposure.depends_on.metrics)
        )
        # The mart leg, and it draws its edge on the same terms: a name that
        # resolves to nothing still gets one. `check_exposure_targets` refuses
        # a dangling dependency two stages later (RFC 0056 D2), and filtering
        # to declared marts here would make the graph disagree with the
        # document the author is holding in exactly the window where
        # `bloomery lineage` answers and a compile does not.
        edges.extend(
            Edge(src=mart_node(mart), dst=exposure_node(name), label="depends_on")
            for name, exposure in sorted(project.exposures.exposures.items())
            for mart in sorted(exposure.depends_on.marts)
        )

    nodes: set[Node] = set()

    if catalog is not None:
        nodes.update(
            canonical_field_node(key(name, ids["canonical"])) for name in catalog.canonical_fields
        )

    nodes.update(metric_node(key(metric.name, ids["metric"])) for metric in metrics)

    if project.steps is not None:
        # A step with no wired inputs still exists in the lineage; without
        # this it would vanish from the topological order entirely.
        nodes.update(step_node(key(wiring.ref, ids["step"])) for wiring in project.steps.steps)

    # A mapped field with no edge at all, for the same reason and with the same
    # fix. Both alias-bound shapes can bind **zero** source paths: a
    # `sql_macro` whose `from` is empty — the schema's default, because a macro
    # may compute from its `parameters` alone (RFC 0017 D50) — and a recipe
    # with an empty `requires` and an `expr`. Such a field draws no edge from
    # any source column, so before this it existed nowhere in the graph:
    # absent from `topo_order`, and refused by `bloomery lineage`, whose
    # `_find_node` looks the id up in `nodes` and suggested a sibling field
    # instead — for a field the entity model declares and the emitter writes
    # a column for. (`lineage()` itself answered: it takes a root that is not
    # a member, by design.) Every ordinary mapped field is already here via
    # its incoming edge, so this adds a node only where one was missing.
    nodes.update(
        entity_field_node(mapping.target, field_name)
        for mapping in project.mappings
        for field_name in (*mapping.key, *mapping.fields)
    )

    # A mart with no `measures:`, once more for the same reason. A dimensional
    # mart is a legitimate shape — RFC 0010 D9 asks a date role only of a
    # *measure-carrying* mart — so such a relation draws no edge at all and
    # would exist nowhere in the graph.
    #
    # Rollups are deliberately **not** listed beside it. `MartSet` refuses a
    # rollup whose `of:` is not a mart of the same document (RFC 0058 D10), so
    # every rollup has an incoming `rollup` edge by the time this runs and a
    # second source for the same node would be a line no test could reach.
    if project.marts is not None:
        nodes.update(mart_node(name) for name in project.marts.marts)

    # An exposure that depends on nothing this project declares, for the same
    # reason a third time. Its mart leg now draws an edge (RFC 0067 §5.2), so
    # the mart-only case this originally covered is no longer the one that
    # needs it; what is left is an exposure whose every dependency dangles,
    # which is refused at GUARDRAILS and reaches `bloomery lineage` before
    # that.
    if project.exposures is not None:
        nodes.update(exposure_node(name) for name in project.exposures.exposures)

    for edge in edges:
        nodes.add(edge.src)
        nodes.add(edge.dst)

    # Both keys carry the node *kind* as a tiebreak, and both are collected
    # from a `set`. An entity-field id has no kind prefix (`<entity>.<field>`),
    # so without the tiebreak two ids that render the same keep whatever
    # relative order set iteration gave, which varies with `PYTHONHASHSEED` —
    # the same specs then produce different `Graph.nodes` in different
    # processes, and `topo_order` derives from this order, so it reaches
    # emitted output. RFC 0003 forbids exactly that; see `logs/T-0005.md`
    # D-025.
    #
    # The collision that motivated it — an entity named `metric` with a field
    # `revenue`, against a metric named `revenue` — is now refused outright
    # (`guardrails.lineage`, RFC 0051 D6): every member of `NODE_ID_PREFIXES`
    # is a reserved entity name, so no two nodes here can share a name. The
    # tiebreak stays, because a sort key that depends on a guardrail holding is
    # a sort key that breaks when someone reorders the stages.
    return Graph(
        nodes=tuple(sorted(nodes, key=lambda n: (n.name, n.kind.value))),
        edges=tuple(
            sorted(
                set(edges),
                key=lambda e: (
                    e.src.name,
                    e.src.kind.value,
                    e.dst.name,
                    e.dst.kind.value,
                    e.label,
                ),
            )
        ),
    )
