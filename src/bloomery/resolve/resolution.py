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
from enum import StrEnum

from bloomery.ir import UnreachableMetric
from bloomery.resolve.graph import Graph, Node, build_graph
from bloomery.resolve.metrics import effective_metrics
from bloomery.resolve.order import toposort
from bloomery.resolve.reach import available_canonicals, compute_reachability
from bloomery.resolve.recipes import validate_recipes
from bloomery.resolve.refs import validate_references
from bloomery.spec.catalog import Catalog
from bloomery.spec.mapping import RecipeFieldMapping
from bloomery.spec.project import Project

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


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    """Provenance of one mapped entity field; ``recipe_id`` is set iff
    ``provenance`` is :attr:`Provenance.RECIPE`."""

    entity: str
    field: str
    provenance: Provenance
    recipe_id: str | None = None


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


def _field_provenance(project: Project) -> tuple[FieldProvenance, ...]:
    entries: dict[tuple[str, str], FieldProvenance] = {}
    for mapping in project.mappings:
        entity = project.entity_model.entities[mapping.target]
        for field_name in mapping.key:
            has_link = entity.fields[field_name].canonical is not None
            entries[mapping.target, field_name] = FieldProvenance(
                entity=mapping.target,
                field=field_name,
                provenance=Provenance.DIRECT if has_link else Provenance.NATIVE,
            )
        for field_name, field_mapping in mapping.fields.items():
            if isinstance(field_mapping, RecipeFieldMapping):
                provenance, recipe_id = Provenance.RECIPE, field_mapping.recipe
            elif entity.fields[field_name].canonical is not None:
                provenance, recipe_id = Provenance.DIRECT, None
            else:
                provenance, recipe_id = Provenance.NATIVE, None
            entries[mapping.target, field_name] = FieldProvenance(
                entity=mapping.target,
                field=field_name,
                provenance=provenance,
                recipe_id=recipe_id,
            )
    return tuple(entries[key] for key in sorted(entries))


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
        provenance=_field_provenance(project),
        topo_order=topo_order,
        graph=graph,
    )
