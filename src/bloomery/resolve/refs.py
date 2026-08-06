"""Cross-spec reference validation (RFC 0005 §5.5): every existence check the
parse stage deferred (RFC 0002 D4), run before graph construction so the
graph builder may assume references resolve.

All failures are :class:`~bloomery.errors.MissingReference` (or plain
:class:`~bloomery.errors.ResolutionError`) with the referencing node's source
path, batched into one aggregate per stage (RFC 0002 D6) — later checks run
only on a reference-clean graph, so their errors are never cascades of a
single dangling name.

Parsed models do not retain their document names, so source paths use
deterministic labels: ``entity_model``, ``metrics``, and
``mapping[<source>-><target>]`` per mapping document.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.errors import BloomeryError, MissingReference, ResolutionError

if TYPE_CHECKING:
    from bloomery.spec.catalog import Catalog
    from bloomery.spec.mapping import Mapping
    from bloomery.spec.project import Project

__all__ = [
    "mapping_doc",
    "validate_references",
]


def mapping_doc(mapping: Mapping) -> str:
    """The deterministic source-path label for one mapping document."""
    return f"mapping[{mapping.source}->{mapping.target}]"


def _check_mapping(mapping: Mapping, project: Project, errors: list[BloomeryError]) -> None:
    doc = mapping_doc(mapping)
    entity = project.entity_model.entities.get(mapping.target)
    if entity is None:
        known = sorted(project.entity_model.entities)
        errors.append(
            MissingReference(
                f"mapping targets unknown entity {mapping.target!r}; known entities: {known}",
                source_path=f"{doc}: target",
            )
        )
        return
    for field_name in sorted(mapping.key):
        if field_name not in entity.fields:
            errors.append(
                MissingReference(
                    f"key lowers unknown field {field_name!r} of entity {mapping.target!r}",
                    source_path=f"{doc}: key.{field_name}",
                )
            )
    for field_name in sorted(mapping.fields):
        if field_name not in entity.fields:
            errors.append(
                MissingReference(
                    f"mapping maps unknown field {field_name!r} of entity {mapping.target!r}",
                    source_path=f"{doc}: fields.{field_name}",
                )
            )
        elif field_name in mapping.key:
            errors.append(
                ResolutionError(
                    f"field {field_name!r} is mapped both under key: and fields:",
                    source_path=f"{doc}: fields.{field_name}",
                )
            )
    for key_column in entity.key:
        if key_column not in mapping.key:
            errors.append(
                ResolutionError(
                    f"entity key column {key_column!r} is not lowered by the mapping's key:",
                    source_path=f"{doc}: key",
                )
            )


def _check_canonical_links(
    project: Project, catalog: Catalog | None, errors: list[BloomeryError]
) -> None:
    for entity_name in sorted(project.entity_model.entities):
        entity = project.entity_model.entities[entity_name]
        for field_name in sorted(entity.fields):
            canonical = entity.fields[field_name].canonical
            if canonical is None:
                continue
            path = f"entity_model: entities.{entity_name}.fields.{field_name}.canonical"
            if catalog is None:
                errors.append(
                    MissingReference(
                        f"field links canonical field {canonical!r} but no catalog was "
                        "provided (RFC 0005 §5.6: a catalog-free project is direct-only)",
                        source_path=path,
                    )
                )
                continue
            canonical_field = catalog.canonical_fields.get(canonical)
            if canonical_field is None:
                known = sorted(catalog.canonical_fields)
                errors.append(
                    MissingReference(
                        f"unknown canonical field {canonical!r}; known: {known}",
                        source_path=path,
                    )
                )
            elif canonical_field.entity != entity_name:
                errors.append(
                    MissingReference(
                        f"canonical field {canonical!r} is declared for entity "
                        f"{canonical_field.entity!r}, not {entity_name!r}",
                        source_path=path,
                    )
                )


def _check_relationships(project: Project, errors: list[BloomeryError]) -> None:
    entities = project.entity_model.entities
    for index, rel in enumerate(project.entity_model.relationships):
        path = f"entity_model: relationships[{index}]"
        endpoints_ok = True
        for side, name in (("from", rel.from_), ("to", rel.to)):
            if name not in entities:
                endpoints_ok = False
                errors.append(
                    MissingReference(
                        f"relationship {rel.name!r} references unknown entity {name!r}",
                        source_path=f"{path}.{side}",
                    )
                )
        if not endpoints_ok:
            continue
        for from_column, to_column in sorted(rel.via.items()):
            if from_column not in entities[rel.from_].fields:
                errors.append(
                    MissingReference(
                        f"relationship {rel.name!r} via references unknown column "
                        f"{from_column!r} of entity {rel.from_!r}",
                        source_path=f"{path}.via.{from_column}",
                    )
                )
            if to_column not in entities[rel.to].fields:
                errors.append(
                    MissingReference(
                        f"relationship {rel.name!r} via references unknown column "
                        f"{to_column!r} of entity {rel.to!r}",
                        source_path=f"{path}.via.{from_column}",
                    )
                )


def _check_metrics(project: Project, catalog: Catalog | None, errors: list[BloomeryError]) -> None:
    if project.metric_set is None:
        return
    metric_names = set(project.metric_set.metrics)
    for name in sorted(project.metric_set.metrics):
        metric = project.metric_set.metrics[name]
        path = f"metrics: metrics.{name}"
        template = None
        if metric.template is not None:
            if catalog is None:
                errors.append(
                    MissingReference(
                        f"metric references template {metric.template!r} but no catalog "
                        "was provided",
                        source_path=f"{path}.template",
                    )
                )
            else:
                template = catalog.metric_templates.get(metric.template)
                if template is None:
                    known = sorted(catalog.metric_templates)
                    errors.append(
                        MissingReference(
                            f"unknown metric template {metric.template!r}; known: {known}",
                            source_path=f"{path}.template",
                        )
                    )
        requires = metric.requires or (template.requires if template else ())
        for index, leaf in enumerate(requires):
            if catalog is None or leaf not in catalog.canonical_fields:
                errors.append(
                    MissingReference(
                        f"metric requires unknown canonical field {leaf!r}",
                        source_path=f"{path}.requires[{index}]",
                    )
                )
        requires_metrics = metric.requires_metrics or (
            template.requires_metrics if template else ()
        )
        for index, required in enumerate(requires_metrics):
            if required not in metric_names:
                errors.append(
                    MissingReference(
                        f"metric requires unknown metric {required!r}",
                        source_path=f"{path}.requires_metrics[{index}]",
                    )
                )


def validate_references(project: Project, catalog: Catalog | None) -> None:
    """Run every cross-spec reference check, batched (RFC 0005 D7).

    Raises one :class:`ResolutionError` aggregate listing every failure (a
    single failure is raised as itself); returns ``None`` on a clean project.
    """
    errors: list[BloomeryError] = []
    for mapping in project.mappings:
        _check_mapping(mapping, project, errors)
    _check_canonical_links(project, catalog, errors)
    _check_relationships(project, errors)
    _check_metrics(project, catalog, errors)
    if errors:
        if len(errors) == 1:
            raise errors[0]
        raise ResolutionError.from_collected(tuple(errors))
