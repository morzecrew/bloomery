"""Timeline: one node across N caller-supplied spec sets (RFC 0069 §5.1).

:func:`~bloomery.lineage` answers "what does this depend on" — structure across
the project at one instant. :func:`timeline` answers the other question a
reader has about a node: "how has this changed" — one node across the
project's history. Both are pure functions over values the caller already
holds, and neither reads anything.

**The history is the caller's** (D2, inherited from RFC 0068 D1). bloomery has
no notion of where a past spec set comes from, and this walk adds none: it is
handed a sequence, consumes it once in the order given, and reports what it
saw. **The labels are opaque** (D1) — carried into the result, rendered, and
compared for nothing. Ordering by parsing them would make this project the
owner of timezone and resolution semantics over data it did not produce.

**P1 reports *that* a definition moved, never how.** ``facets`` is present and
empty; the delta vocabulary is RFC 0064's and is deliberately not restated here
(D3), because two tables describing one thing is drift this corpus has already
paid for.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from bloomery.errors import InvariantViolated

# `Iterable` above and every name below are runtime imports rather than
# `TYPE_CHECKING` ones, for the reason
# `resolve.lineage` gives: every name below is public, and RFC 0018 D10
# requires a public annotation to resolve at run time —
# `tests/unit/test_signature_closure.py` calls `get_type_hints` on every
# export and a guarded name fails it.
from bloomery.resolve.build import StageProgress, pipeline
from bloomery.resolve.graph import NodeKind
from bloomery.spec import Catalog, Project
from bloomery.spec.project import node_keys
from bloomery.steps import EMPTY_REGISTRY, StepRegistry

if TYPE_CHECKING:
    from bloomery.ir import ProjectIR
    from bloomery.resolve.graph import Graph

# ----------------------- #

__all__ = [
    "MatchedBy",
    "SpecVersion",
    "Timeline",
    "TimelineChange",
    "TimelineEntry",
    "timeline",
]


#: Node-id prefix to the kind it spells, for the six kinds that carry one.
#: An entity field is the seventh and is spelled bare (``<entity>.<field>``),
#: so it is the fall-through rather than a row.
#:
#: Pinned against :data:`~bloomery.ir.NODE_ID_PREFIXES` by
#: ``test_the_prefix_table_is_the_reserved_one``: the reservation and this
#: table are two readings of one fact, and a kind added to the graph with a new
#: prefix has to fail *somewhere* rather than quietly resolve as an entity
#: field named after it.
_KIND_BY_PREFIX: Final[dict[str, NodeKind]] = {
    "canonical": NodeKind.CANONICAL_FIELD,
    "exposure": NodeKind.EXPOSURE,
    "mart": NodeKind.MART,
    "metric": NodeKind.METRIC,
    "source": NodeKind.SOURCE_COLUMN,
    "step": NodeKind.STEP,
}

#: The kinds that can carry an RFC 0062 ``id:``, and the key
#: :func:`~bloomery.spec.project.node_keys` files each under. A kind absent
#: here has no id anywhere in the spec layer, so every boundary it crosses is
#: matched by name — which is not a limitation of this walk but of what the
#: documents can say.
#:
#: Read off ``node_keys`` rather than off the spec models, so the map this uses
#: to *match* is the map the graph used to *build* the ids. Two answers to
#: "what is this node called" is precisely what that function exists to avoid.
_ID_NAMESPACE: Final[dict[NodeKind, str]] = {
    NodeKind.METRIC: "metric",
    NodeKind.CANONICAL_FIELD: "canonical",
    NodeKind.STEP: "step",
}


class MatchedBy(StrEnum):
    """How one adjacent pair of versions was matched (D12).

    Per pair rather than per timeline: adoption is a thing that *happens*. A
    project that mints an ``id:`` in April has a name-matched boundary in March
    and an id-matched one after, and a single per-timeline answer would have to
    lie about one of them.
    """

    #: Both sides carried the same RFC 0062 ``id:``. A rename across this
    #: boundary is a relabelling, and the node survives it.
    ID = "id"
    #: The node name was the key — either side may still carry an id (adopting
    #: one without renaming is continuous, §5.2). A rename across this boundary
    #: reads as a delete and an add, and that is the honest answer rather than
    #: a shape-matching guess.
    NAME = "name"


# ....................... #


@dataclass(frozen=True, slots=True)
class SpecVersion:
    """One entry of a caller-assembled history (D2).

    **It carries the spec side, not the IR** (D11). A :class:`ProjectIR` does
    not retain the authored ``id:`` — RFC 0062 substitutes it while building
    node ids and the IR keeps only names, because a field there would move
    every fingerprint in the corpus. A timeline handed only IRs therefore
    cannot match by id at all, which is the failure this feature exists to
    avoid.

    :attr:`label` is **opaque** (D1): carried into the result and compared for
    nothing. ``YYYY-MM-DDTHH:MM:SSZ`` is the recommended spelling (D10) and is
    enforced nowhere — a history of ``"before"`` and ``"after"`` is legitimate.
    """

    #: Whatever the caller calls this version. Never parsed (D1).
    label: str
    project: Project
    catalog: Catalog | None = None
    #: The step registry this version compiles against (RFC 0017 §5.3). §5.1
    #: did not list it and the IR cannot be built without it: a project
    #: declaring ``steps:`` is refused with ``UnknownStep`` against the empty
    #: registry, so a history of any step-wiring project would have no timeline
    #: at all. It is the same caller-assembled compile input RFC 0068 D1 puts
    #: the caller in charge of — the party holding the history is already the
    #: party holding this. See ``logs/T-0043.md``.
    steps: StepRegistry = EMPTY_REGISTRY


# ....................... #


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """One history entry, and whether the node was in it (D13).

    **One of these per history entry, present or absent.** A gap is
    ``present=False`` at its own label rather than a missing row: the absence
    has a position, so a reader can see *which* entry the node was missing from
    rather than only that something was missing between two others. That is
    what makes a delete-and-recreate distinguishable from a rename, which is
    the case RFC 0062 exists for.
    """

    #: The caller's label for this version, verbatim.
    label: str
    #: Whether this version's dependency graph carried the node.
    present: bool


# ....................... #


@dataclass(frozen=True, slots=True)
class TimelineChange:
    """A definition that differs between two adjacent present entries.

    Named :class:`TimelineChange` rather than ``Change``, which §5.1's sketch
    used: ``Change`` is already a public export of this package — the
    per-relation change ``plan()`` reports — and the root cannot carry both.

    Emitted only between entries that are **adjacent and both present**: a gap
    is a delete and an add, not a change spanning it, so nothing here ever
    claims a definition moved across a version the node was missing from.
    """

    #: The label of the earlier of the two versions.
    before: str
    #: The label of the later one.
    after: str
    #: How this boundary was crossed (D12).
    matched_by: MatchedBy
    #: What changed, in RFC 0064's vocabulary — **empty in P1** (D3, D13).
    #:
    #: Typed as ``object`` on purpose: the element type is RFC 0064's and
    #: naming one here is exactly what D3 forbids, since two tables describing
    #: one delta is the drift this corpus has paid for before. The field exists
    #: from P1 rather than appearing in P2 so the JSON a consumer reads grows a
    #: value instead of changing shape — §9 notes a UI pins this earlier than a
    #: library usually wants.
    facets: tuple[object, ...] = ()


# ....................... #


@dataclass(frozen=True, slots=True)
class Timeline:
    """The versions one node had, and what moved between them (§5.1).

    It mirrors :class:`~bloomery.Lineage` deliberately, including the property
    that matters most there: **a node that never changed is a result, not a
    miss** (D4). One entry, no changes, is the answer "this has not moved since
    March" — which is what a reader came for at least as often as the other.

    A node no entry carries returns a full-length timeline of absences and no
    changes rather than a refusal (D7), because ``lineage()`` answers the same
    way: a root need not be a member of the graph. The refusal with a
    suggestion is the command's, and lands with it.
    """

    #: The node id asked about, verbatim — not re-spelled per version, because
    #: the whole point is that it may be spelled differently in each.
    node: str
    #: One per history entry, in the order supplied (D1, D13).
    entries: tuple[TimelineEntry, ...]
    #: Between adjacent present entries only, in the same order.
    changes: tuple[TimelineChange, ...]


# ....................... #


@dataclass(frozen=True, slots=True)
class _Held:
    """What the walk carries forward from the last version the node was in.

    Survives a gap — identity has to, or the node could not be found again on
    the far side — while :attr:`index` is what stops a *change* crossing one.
    """

    index: int
    label: str
    name: str
    node_id: str | None
    definition: object


# ....................... #


def _kind_and_spelling(node: str) -> tuple[NodeKind, str]:
    """A node id split into its kind and the part that identifies it.

    ``metric.gross_revenue`` is a metric spelled ``gross_revenue``;
    ``order_item.unit_price`` is an entity field spelled whole, because that
    kind carries no prefix. Every member of
    :data:`~bloomery.ir.NODE_ID_PREFIXES` is a reserved entity name
    (``guardrails.lineage``, RFC 0051 D6), so the fall-through cannot swallow a
    prefixed id.
    """

    prefix, _, rest = node.partition(".")
    kind = _KIND_BY_PREFIX.get(prefix)
    if kind is None or not rest:
        return NodeKind.ENTITY_FIELD, node
    return kind, rest


# ....................... #


def _entity_field(ir: ProjectIR, spelling: str) -> object | None:
    """An entity field's definition: its schema **and** its lowering.

    The two live apart in the IR (RFC 0024 D26). ``ColumnIR`` is the schema
    half — type, canonical link, unit, tax basis — and the expression that
    produces the value is a ``SourceColumnIR`` *per source*, because a merged
    entity contributes one projection per mapping to a ``UNION ALL``. Comparing
    only the first would miss a rewritten mapping entirely; comparing only the
    second would miss a retyped column.

    ``EntityIR.sources`` is sorted by relation and its ``columns`` by name, so
    the pair this builds inherits a total order and never depends on set
    iteration.
    """

    entity_name, _, field = spelling.partition(".")
    entity = next((one for one in ir.entities if one.name == entity_name), None)
    if entity is None:  # pragma: no cover — see :func:`_definition`
        return None

    column = next((one for one in entity.columns if one.name == field), None)
    if column is None:
        # **A step output is a relation, not a field**, and it lives in this
        # namespace anyway: `_step_edges` mints `<produced relation>.<output
        # name>` for each `outputs:` entry, so `customer.customer` is the whole
        # `customer` relation that `resolve_customers` produces. Its definition
        # is the entity, and comparing nothing instead would report every step
        # output as present in every version and changed in none — a silent
        # wrong answer, which is the one failure this walk must not produce.
        #
        # The ambiguity is the graph's rather than this table's: an output
        # named after a real column of the same relation mints the id a field
        # would, and nothing downstream can separate the two.
        return entity
    return (
        column,
        tuple(
            (source.relation, lowered)
            for source in entity.sources
            for lowered in source.columns
            if lowered.name == field
        ),
    )


# ....................... #


def _definition(kind: NodeKind, spelling: str, ir: ProjectIR, catalog: Catalog | None) -> object:
    """The value whose inequality means "this definition moved".

    §12 says the comparison is IR equality per node, and the IR has no record
    for two of the seven kinds — so this table is what that sentence means for
    the rest (``logs/T-0043.md``):

    - **metric** — the ``MetricIR``, or the ``UnreachableMetric`` the IR keeps
      instead when nothing maps its leaves. The second is coarse by
      construction: it records the name and why the metric is blocked, so an
      edit that leaves a metric unreachable for the same reason is not visible
      here. Becoming reachable is, which is the change a reader is waiting for.
    - **mart** — the ``MartIR``, or the ``RollupIR``: both are gold relations
      under one node prefix (RFC 0067 §5.1) and RFC 0058 D10 refuses a rollup
      that takes a mart's name, so the one lookup cannot be ambiguous.
    - **exposure** — the ``ExposureIR``.
    - **step** — the ``StepIR``, keyed by ``ref`` as its node is.
    - **entity field** — the `ColumnIR` with its per-source lowerings, or
      the whole `EntityIR` where the node is a step output rather than a
      field. See :func:`_entity_field`.
    - **canonical field** — the catalog's own ``CanonicalField``. There is no
      canonical-field record anywhere in ``ProjectIR``; the field survives
      lowering only as ``ColumnIR.canonical``, a string reference. The spec
      model is the only record of one that exists, so it is what gets compared.
      Its ``id`` is blanked first: RFC 0062's id is *identity*, not definition,
      and leaving it in would make minting one read as a redefinition — which
      no other kind does, because no other kind's record retains it.
    - **source column** — **nothing**. A source column is a bronze path; it has
      no definition beyond its existence, and presence is the whole of what can
      change about it. Forced rather than chosen.

    The two remaining "not found" paths — an entity-field node whose entity the
    IR has none of, and a canonical node asked of a project with no catalog —
    are unreachable, because this is called only for a node the version's
    *graph* carried and the graph and the IR are built from one pipeline pass
    over one project. **That is measured rather than argued**:
    ``test_every_node_the_graph_carries_has_a_definition`` sweeps every node of
    every fixture and requires a record for every kind but a source column. The
    sweep is there because it found one — step outputs, which live in this
    namespace and are relations rather than fields, were reported present in
    every version and changed in none, which is the one failure shape this walk
    must never produce (``logs/T-0043.md``).
    """

    match kind:
        case NodeKind.METRIC:
            metric = next((one for one in ir.metrics if one.name == spelling), None)
            if metric is not None:
                return metric
            return next((one for one in ir.unreachable if one.name == spelling), None)
        case NodeKind.MART:
            mart = next((one for one in ir.marts if one.name == spelling), None)
            if mart is not None:
                return mart
            return next((one for one in ir.rollups if one.name == spelling), None)
        case NodeKind.EXPOSURE:
            return next((one for one in ir.exposures if one.name == spelling), None)
        case NodeKind.STEP:
            return next((step for step in ir.steps if step.ref == spelling), None)
        case NodeKind.ENTITY_FIELD:
            return _entity_field(ir, spelling)
        case NodeKind.CANONICAL_FIELD:
            if catalog is None:  # pragma: no cover — no catalog, no canonical node
                return None
            field = catalog.canonical_fields.get(spelling)
            return None if field is None else field.model_copy(update={"id": None})
        case NodeKind.SOURCE_COLUMN:  # pragma: no branch — the table is total
            return None


# ....................... #


def _compile(version: SpecVersion) -> tuple[Graph, ProjectIR]:
    """One version's graph and IR, from one pass of the compile pipeline.

    Written as :func:`~bloomery.resolve.pipeline` run to exhaustion rather than
    as ``resolve()`` plus ``build_project_ir()``, which would compile the same
    specs twice — and for the reason ``build_project_ir`` is written that way
    too: one definition of what the pipeline is.

    **Every refusal propagates**, so a history containing one spec set that
    does not compile has no timeline at all. That is stated rather than caught:
    comparing the pre-guardrail draft would tolerate such an entry while
    silently dropping the amendments the guardrail stage makes to the IR, and
    an entry-level "did not compile" state is a third value of ``present`` —
    a shape change to a value a UI pins early (§9). See ``logs/T-0043.md``.
    """

    progress = StageProgress()
    for _stage, reached in pipeline(version.project, version.catalog, steps=version.steps):
        progress = reached

    if progress.ir is None or progress.resolution is None:  # pragma: no cover
        msg = "the pipeline reached COMPLETE without an IR"
        raise InvariantViolated(msg)

    return progress.resolution.graph, progress.ir


# ....................... #


def _locate(
    spelling: str,
    kind: NodeKind,
    graph: Graph,
    ids: dict[str, str],
    held: _Held | None,
) -> tuple[str, str | None] | None:
    """The node's authored name and adopted id in this version, or ``None``.

    ``ids`` is this version's name-to-``id:`` map for the kind, from
    :func:`~bloomery.spec.project.node_keys` — the same map the graph built its
    node ids from.

    Before the node has been seen, ``spelling`` is read as a node id **as this
    version spells it**: an adopted id resolves back to its name, anything else
    is a name. After that, D5 and D12 decide: the id where *both* sides carry
    one, the name otherwise. Falling back to the name is right in the common
    case — adopting an id without renaming is continuous — and honest in the
    one it cannot recover, where adopting an id *and* renaming in the same
    entry reads as a delete and an add.
    """

    present = frozenset(
        _kind_and_spelling(node.name)[1] for node in graph.nodes if node.kind is kind
    )
    by_id = {adopted: name for name, adopted in ids.items()}

    if held is None:
        if spelling not in present:
            return None
        name = by_id.get(spelling, spelling)
        return name, ids.get(name)

    # `by_id` is this version's own adoption map and the graph built its node
    # ids from the same one, so an id it names is an id the graph carried —
    # membership in `present` was asserted here too and no test could tell the
    # two apart, because `node_keys` and `build_graph` read one source.
    if held.node_id is not None and held.node_id in by_id:
        return by_id[held.node_id], held.node_id

    if ids.get(held.name, held.name) in present:
        return held.name, ids.get(held.name)

    return None


# ....................... #


def timeline(history: Iterable[SpecVersion], node: str) -> Timeline:
    """The versions ``node`` had across ``history``, and what moved (§5.1).

    ``history`` is **consumed once, in the order given** (D1, D2). Nothing here
    sorts it, validates it or reads a label, so a caller who supplies entries
    out of order gets a timeline that is out of order and no refusal — the same
    trust ``plan(old, new)`` already places in its arguments, where nothing
    checks that ``old`` is older. A generator is accepted and never
    re-iterated, because a caller fetching from a store pays for every pass.

    Every entry is compiled: sixty versions is sixty compiles, and the cost
    lands on the caller, who is also the only party able to decide the
    resolution they need.

    ``node`` is a lineage node id, spelled as
    :func:`~bloomery.lineage`'s root is — and it need only be spelled as *some*
    version spells it. An id adopted partway through a history is matched from
    either side (D12), so asking by name reaches a node that has since minted
    an id, and asking by id reaches the versions before it existed.
    """

    kind, spelling = _kind_and_spelling(node)
    namespace = _ID_NAMESPACE.get(kind)

    entries: list[TimelineEntry] = []
    changes: list[TimelineChange] = []
    held: _Held | None = None

    for index, version in enumerate(history):
        graph, ir = _compile(version)
        ids = {} if namespace is None else node_keys(version.project, version.catalog)[namespace]

        found = _locate(spelling, kind, graph, ids, held)
        entries.append(TimelineEntry(label=version.label, present=found is not None))

        if found is None:
            continue

        name, node_id = found
        definition = _definition(kind, name, ir, version.catalog)

        # Adjacency is the index, not "the last one we saw": a node missing
        # from a middle entry is a delete and an add, and eliding to one change
        # that spans the gap would report a definition moving across a version
        # it was not in.
        if held is not None and held.index == index - 1 and definition != held.definition:
            # D5/D12 stated once, here, rather than inferred from which branch
            # of `_locate` fired: a pair matches by id only when both sides
            # carry one, and the same id at that.
            matched_by = (
                MatchedBy.ID
                if held.node_id is not None and held.node_id == node_id
                else MatchedBy.NAME
            )
            changes.append(
                TimelineChange(before=held.label, after=version.label, matched_by=matched_by)
            )

        held = _Held(
            index=index,
            label=version.label,
            name=name,
            node_id=node_id,
            definition=definition,
        )

    return Timeline(node=node, entries=tuple(entries), changes=tuple(changes))
