"""The ``Project`` container and the pure loaders (RFC 0002 §5.5, D2).

``load_catalog(text)`` and ``load_project(sources)`` are pure text-in: callers
pass strings, never paths — I/O belongs to the control plane (hard invariant).
Each project document self-identifies its kind via its version key
(``spec_version`` / ``mapping_version`` / ``metrics_version`` /
``marts_version``). Exactly one ``EntityModel``, at most one ``MetricSet``, at
most one ``MartSet`` per project; the catalog is deliberately *not* part of
``Project`` (RFC 0002 D8). All parse failures across all documents are batched
into one :class:`~bloomery.errors.SpecParseError` (RFC 0002 D6).
"""

from __future__ import annotations

from collections.abc import Mapping as AbcMapping
from dataclasses import dataclass

from bloomery.errors import BloomeryError, SpecParseError
from bloomery.spec.catalog import Catalog
from bloomery.spec.common import SpecModel, flatten_collected, load_yaml_mapping, validate_document
from bloomery.spec.entity import EntityModel
from bloomery.spec.mapping import Mapping
from bloomery.spec.marts import MartSet
from bloomery.spec.metrics import MetricSet
from bloomery.spec.steps import StepSet

# ----------------------- #

__all__ = [
    "Project",
    "load_catalog",
    "load_project",
]

_KIND_KEYS: dict[str, type[SpecModel]] = {
    "spec_version": EntityModel,
    "mapping_version": Mapping,
    "metrics_version": MetricSet,
    "marts_version": MartSet,
    "steps_version": StepSet,
}


@dataclass(frozen=True, slots=True)
class Project:
    """A parsed project: the entity model, mappings ordered by document name
    (deterministic — RFC 0003 ordering rules), and the optional metric and
    mart sets."""

    entity_model: EntityModel
    mappings: tuple[Mapping, ...]
    metric_set: MetricSet | None = None
    marts: MartSet | None = None
    steps: StepSet | None = None


# ....................... #


def load_catalog(text: str) -> Catalog:
    """Parse a catalog document (original spec §3.2). Pure: text in, model out.

    Raises :class:`SpecParseError` on YAML, shape, or kind failures; source
    paths are prefixed with ``catalog``.
    """
    data = load_yaml_mapping(text, document="catalog")

    if "catalog_version" not in data:
        raise SpecParseError(
            "not a catalog document: missing 'catalog_version'",
            source_path="catalog",
        )

    return validate_document(Catalog, data, document="catalog")


# ....................... #


def _detect_kind(data: dict[str, object], *, document: str) -> type[SpecModel]:
    """Detect a project document's kind from its version key — exactly one."""
    present = sorted(key for key in _KIND_KEYS if key in data)

    if "catalog_version" in data:
        raise SpecParseError(
            "a catalog is not part of a project — load it via load_catalog() "
            "and pass it separately (RFC 0002 D8)",
            source_path=document,
        )

    if not present:
        raise SpecParseError(
            "unknown spec kind: expected exactly one of spec_version / "
            "mapping_version / metrics_version / marts_version / steps_version",
            source_path=document,
        )

    if len(present) > 1:
        raise SpecParseError(
            f"ambiguous spec kind: found multiple version keys {present}",
            source_path=document,
        )

    return _KIND_KEYS[present[0]]


# ....................... #


def _check_document_counts(
    entity_models: list[tuple[str, EntityModel]],
    metric_sets: list[tuple[str, MetricSet]],
    mart_sets: list[tuple[str, MartSet]],
    step_sets: list[tuple[str, StepSet]],
) -> list[BloomeryError]:
    errors: list[BloomeryError] = []

    if not entity_models:
        errors.append(
            SpecParseError("a project requires exactly one EntityModel document, found none")
        )
    elif len(entity_models) > 1:
        names = [name for name, _ in entity_models]
        errors.append(
            SpecParseError(
                f"a project requires exactly one EntityModel document, found {len(names)}: {names}"
            )
        )

    for kind, sets in (
        ("MetricSet", metric_sets),
        ("MartSet", mart_sets),
        ("StepSet", step_sets),
    ):
        if len(sets) > 1:
            names = [name for name, _ in sets]
            errors.append(
                SpecParseError(
                    f"a project allows at most one {kind} document, found {len(names)}: {names}"
                )
            )

    return errors


# ....................... #


def load_project(sources: AbcMapping[str, str]) -> Project:
    """Parse a project from named YAML documents. Pure: strings in, model out.

    ``sources`` maps document names (used as source-path prefixes, RFC 0002
    §5.3) to YAML text. Documents are processed in sorted-name order, so the
    resulting ``mappings`` tuple is deterministic. All failures across all
    documents are batched into a single :class:`SpecParseError`.
    """
    errors: list[BloomeryError] = []
    entity_models: list[tuple[str, EntityModel]] = []
    mappings: list[Mapping] = []
    metric_sets: list[tuple[str, MetricSet]] = []
    mart_sets: list[tuple[str, MartSet]] = []
    step_sets: list[tuple[str, StepSet]] = []

    for name in sorted(sources):
        try:
            data = load_yaml_mapping(sources[name], document=name)
            model = validate_document(_detect_kind(data, document=name), data, document=name)
        except SpecParseError as exc:
            errors.append(exc)
            continue
        if isinstance(model, EntityModel):
            entity_models.append((name, model))
        elif isinstance(model, Mapping):
            mappings.append(model)
        elif isinstance(model, MetricSet):
            metric_sets.append((name, model))
        elif isinstance(model, MartSet):
            mart_sets.append((name, model))
        elif isinstance(model, StepSet):
            step_sets.append((name, model))
        else:  # pragma: no cover — _KIND_KEYS is closed
            # Not a `cast` on the closed table: the cast made a seventh kind
            # silently *become* a StepSet, and hid the mismatch from pyright
            # too. The table stays closed; this makes it verifiable.
            msg = f"unhandled spec kind {type(model).__name__}"
            raise SpecParseError(msg, source_path=name)

    if not errors:
        # Cardinality complaints on top of per-document failures would be
        # misleading (a failed document still *was* its kind) — report the
        # parse errors first; counts are checked once every document parses.
        errors.extend(_check_document_counts(entity_models, metric_sets, mart_sets, step_sets))

    if errors:
        flat = flatten_collected(errors)
        if len(flat) == 1:
            raise flat[0]
        raise SpecParseError.from_collected(flat)

    return Project(
        entity_model=entity_models[0][1],
        mappings=tuple(mappings),
        metric_set=metric_sets[0][1] if metric_sets else None,
        marts=mart_sets[0][1] if mart_sets else None,
        steps=step_sets[0][1] if step_sets else None,
    )
