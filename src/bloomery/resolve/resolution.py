"""The ``Resolution`` result and the public ``resolve`` analysis API
(RFC 0005 §5.6, spec §8): a pure function from parsed specs plus catalog to
reachable/unreachable metrics, per-field provenance, and the deterministic
topological emission order — no I/O, all tuples, explicit sorts.

``catalog=None`` is a bring-up mode (spec: M2 runs without a catalog): every
``canonical:`` link then fails reference validation, so a catalog-free
project is direct-and-native only and reachable metrics are empty by
construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum

from bloomery.ir import UnreachableMetric
from bloomery.resolve.graph import Graph, Node, build_graph, entity_field_node
from bloomery.resolve.metrics import effective_metrics
from bloomery.resolve.order import toposort
from bloomery.resolve.reach import available_canonicals, compute_reachability
from bloomery.resolve.recipes import validate_recipes
from bloomery.resolve.refs import validate_references
from bloomery.spec.catalog import Catalog
from bloomery.spec.mapping import RecipeFieldMapping
from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "FieldProvenance",
    "Provenance",
    "Resolution",
    "resolve",
]


class Provenance(StrEnum):
    """How a mapped entity field is produced (RFC 0005 §5.6)."""

    #: Mapped straight from a source column with a ``canonical:`` link.
    DIRECT = "direct"
    #: Via a validated catalog recipe (id recorded on :class:`FieldProvenance`).
    RECIPE = "recipe"
    #: No ``canonical:`` link — the field participates in no catalog metric.
    NATIVE = "native"


# ....................... #


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    """Provenance of one mapped entity field; ``recipe_id`` is set iff
    ``provenance`` is :attr:`Provenance.RECIPE`.

    **One entry per ``(entity, field, mapping)``** (RFC 0032). Where several
    mappings build one entity (RFC 0024) they may implement the same field
    differently — one straight from a column, another through a recipe — and
    each says so in its own entry. Until RFC 0032 this collection keyed on the
    field alone and reported the last mapping in document order, so a merged
    entity's other mappings were not representable at all; ``mapping`` is the
    document name that made them representable.

    ``mapping`` reads third and is **keyword-only** (RFC 0032 D11). D5 put it
    third on the argument that a positional caller would fail on arity; that
    was wrong, because ``recipe_id`` carries a default, so the old
    four-argument call ``FieldProvenance(entity, field, provenance, recipe_id)``
    still satisfies arity and binds ``provenance`` into ``mapping`` — the exact
    silent rebinding the placement was chosen to avoid. Keyword-only restores
    the loud failure, and keeps the reading order the argument wanted.
    """

    entity: str
    field: str
    #: The mapping document that builds this field (RFC 0032 D1) — the name it
    #: was loaded under, which is the document a reader would edit.
    mapping: str = dataclass_field(kw_only=True)
    provenance: Provenance
    recipe_id: str | None = None


# ....................... #


@dataclass(frozen=True, slots=True)
class Resolution:
    """The resolve stage's product (RFC 0005 D6): all tuples, explicitly
    sorted, because its content is embedded in IR construction and reaches
    fingerprinted output (RFC 0003 §5.3)."""

    reachable_metrics: tuple[str, ...]
    unreachable_metrics: tuple[UnreachableMetric, ...]
    provenance: tuple[FieldProvenance, ...]
    topo_order: tuple[Node, ...]
    #: The DAG the three fields above were computed from (RFC 0031 D2).
    #:
    #: Carried rather than rebuilt, and with **no default**: a ``Resolution``
    #: holding a graph that disagrees with the one its reachability came from
    #: is not a state worth being able to represent, and a caller rebuilding it
    #: with a different ``catalog`` would get exactly that. ``topo_order`` stays
    #: even though it is derivable from this — it is a published field with
    #: callers and RFC 0005 D6 names it as part of the stage's product.
    graph: Graph


# ....................... #


def _field_provenance(project: Project, graph: Graph) -> tuple[FieldProvenance, ...]:
    """One record per mapped entity field.

    ``DIRECT`` versus ``NATIVE`` is the graph's answer, read off the outgoing
    ``canonical`` edges — the same edges ``available_canonicals`` reads to
    decide what a metric can reach (RFC 0031 §5.2). Asking them rather than
    re-reading ``entity.fields[...].canonical`` in parallel is what stops this
    report and reachability disagreeing about which fields feed the catalog.
    It is decided by the outgoing canonical edge rather than by an incoming
    ``direct`` one: every non-recipe mapped field has an incoming ``direct``
    edge whether or not it links to a canonical, so that edge cannot separate
    the two.

    **The recipe and the population come from the mappings, and cannot come
    from the graph.** Both look like they could — a ``recipe:<id>`` label sits
    on every edge a recipe field draws — and both are lossy that way:

    - An alias-bound field may bind **zero** source paths: a ``sql_macro``
      whose ``from`` is empty (the schema's default — a macro may compute from
      its ``parameters`` alone, RFC 0017 D50), or a recipe with an empty
      ``requires`` and an ``expr``, which compiles to a constant column. Such a
      field draws no edge from any source column, so there is no edge to carry
      its label, and a label-derived kind would silently report a recorded
      recipe as ``DIRECT`` — losing exactly the decision this record exists to
      remember (RFC 0005 D2: the compiler never re-chooses).
    - An entity wired as a step input contributes a node for **every** field it
      declares (``_step_edges``), mapped or not, so a node-keyed population
      would report fields no mapping builds.

    So each fact is taken from wherever it is total. The recipe id is a
    recorded upstream decision and the mappings are where it is recorded; the
    canonical link is a graph fact and the graph is asked for it.
    """
    linked = {edge.src.name for edge in graph.edges if edge.label == "canonical"}

    # Keyed on the mapping too (RFC 0032 D1), so nothing overwrites anything:
    # where two mappings build one field they each get an entry, rather than the
    # last in document order deciding for both.
    recipe_of: dict[tuple[str, str, str], str | None] = {}

    for mapping in project.mappings:
        for field_name in mapping.key:
            recipe_of[mapping.target, field_name, mapping.document] = None
        for field_name, field_mapping in mapping.fields.items():
            recipe_of[mapping.target, field_name, mapping.document] = (
                field_mapping.recipe if isinstance(field_mapping, RecipeFieldMapping) else None
            )

    entries: list[FieldProvenance] = []

    # Sorted `(entity, field, mapping)` — RFC 0032 D7, decided against the
    # corpus: on `multi_source` it keeps `order_line.quantity`'s two answers
    # adjacent, which is the comparison a reader of a merged field is making.
    # `(entity, mapping, field)` groups by document instead and interleaves
    # them, so the two rows a merged field exists to show sit apart.
    for (entity, field, document), recipe_id in sorted(recipe_of.items()):
        if recipe_id is not None:
            provenance = Provenance.RECIPE

        elif entity_field_node(entity, field).name in linked:
            provenance, recipe_id = Provenance.DIRECT, None

        else:
            provenance, recipe_id = Provenance.NATIVE, None

        entries.append(
            FieldProvenance(
                entity=entity,
                field=field,
                mapping=document,
                provenance=provenance,
                recipe_id=recipe_id,
            )
        )

    return tuple(entries)


# ....................... #


def resolve(project: Project, catalog: Catalog | None = None) -> Resolution:
    """Resolve a project against a catalog (public API, spec §8).

    Stages, in order (RFC 0005 §5.5): cross-spec reference validation, then
    recorded-recipe validation, both batched; template merge; DAG assembly;
    cycle detection (:class:`~bloomery.errors.CircularDerivation`); then
    availability, reachability, and provenance over the clean, acyclic graph.
    """
    validate_references(project, catalog)
    validate_recipes(project, catalog)

    metrics = effective_metrics(project, catalog)
    graph = build_graph(project, catalog, metrics)
    topo_order = toposort(graph)
    reachable, unreachable = compute_reachability(metrics, available_canonicals(graph))

    return Resolution(
        reachable_metrics=reachable,
        unreachable_metrics=unreachable,
        provenance=_field_provenance(project, graph),
        topo_order=topo_order,
        graph=graph,
    )
