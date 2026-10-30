"""Cross-spec reference validation (S-0022/cross-spec-reference-validation-bloomery-resolve-refs-py): every existence check the
parse stage deferred (S-0019/D-4), run before graph construction so the
graph builder may assume references resolve.

All failures are :class:`~bloomery.errors.MissingReference` (or plain
:class:`~bloomery.errors.ResolutionError`) with the referencing node's source
path, batched into one aggregate per stage (S-0019/D-6) — later checks run
only on a reference-clean graph, so their errors are never cascades of a
single dangling name.

Parsed models do not retain their document names, so source paths use
deterministic labels: ``entity_model``, ``metrics``, and
``mapping[<source>-><target>]`` per mapping document.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.errors import BloomeryError, MissingReference, ResolutionError
from bloomery.spec.mapping import ConstFieldMapping, mapping_doc

if TYPE_CHECKING:
    from collections.abc import Collection
    from collections.abc import Mapping as AbcMapping

    from bloomery.spec.catalog import Catalog
    from bloomery.spec.entity import Relationship
    from bloomery.spec.mapping import Mapping
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "mapping_doc",
    "relationship_column_errors",
    "step_written",
    "validate_references",
]


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

    missing = [key_column for key_column in entity.key if key_column not in mapping.key]

    for key_column in missing:
        errors.append(
            ResolutionError(
                f"entity key column {key_column!r} is not lowered by the mapping's key:",
                source_path=f"{doc}: key",
            )
        )

    # The entity's key, not the mapping's: `key:` may also lower a declared
    # non-key field, and a path read there keys nothing (S-0019/D-17).
    if not missing and all(
        isinstance(mapping.key[key_column], ConstFieldMapping) for key_column in entity.key
    ):
        errors.append(
            ResolutionError(
                f"every key column of entity {mapping.target!r} is set by a const, so every "
                "row of this mapping would carry one key: at least one of them must read a "
                "path (S-0019/D-17)",
                source_path=f"{doc}: key",
            )
        )


# ....................... #


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
                        "provided (S-0022/the-result-type-and-api-bloomery-resolve-init-py: a catalog-free project is direct-only)",
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


# ....................... #


def _check_step_canonical_links(
    project: Project, catalog: Catalog | None, errors: list[BloomeryError]
) -> None:
    """A step output's ``canonical:`` links resolve against the catalog, on
    the same terms a mapped field's do (S-0034/D-49).

    The same two checks and for the same reasons: an unknown canonical field
    would make the metric over it read as reachable while nothing declares
    what it means, and a field declared for a *different* entity is the
    grain confusion S-0023 exists to refuse — a step output is an entity
    like any other, so it earns no exemption.
    """

    if project.steps is None:
        return

    for wiring in project.steps.steps:
        for output, links in sorted(wiring.canonical.items()):
            entity_name = wiring.outputs[output].rsplit(".", 1)[-1]
            for column, canonical in sorted(links.items()):
                path = f"steps: steps.{wiring.use}.canonical.{output}.{column}"
                if catalog is None:
                    errors.append(
                        MissingReference(
                            f"step output column links canonical field {canonical!r} but no "
                            "catalog was provided (S-0022/the-result-type-and-api-bloomery-resolve-init-py: a catalog-free project is "
                            "direct-only)",
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


# ....................... #


def _check_relationship_names(project: Project, errors: list[BloomeryError]) -> None:
    """Refuse two relationships sharing a name.

    ``relationships:`` is a list and nothing made its names unique, but every
    consumer treats a name as a key and each one resolves the collision
    differently and silently: a mart's ``via:`` takes the first match
    (`marts/flatten.py`), ``plan`` builds a ``{name: rel}`` dict and keeps the
    last, and the evidence guard reads the name to decide whether the edge was
    imported — so one imported relationship marked every same-named authored
    one as imported and refused a strict mart for it (PR #115 review).

    Refused here rather than fixed at each reader, because the readers are
    four and the fact is one: a name that resolves to two relationships is a
    question the spec has not answered, and answering it differently in four
    places is how the answers came to disagree.
    """

    seen: dict[str, int] = {}

    for index, rel in enumerate(project.entity_model.relationships):
        first = seen.setdefault(rel.name, index)
        if first == index:
            continue
        msg = (
            f"relationship {rel.name!r} is declared twice, at relationships[{first}] and "
            f"relationships[{index}]. A relationship's name is how a mart's via:, an "
            "entity's referential rule and the plan diff all refer to it, so two of one "
            "name is a reference that resolves to either. Fix: give them distinct names"
        )
        errors.append(ResolutionError(msg, source_path=f"entity_model: relationships[{index}]"))


# ....................... #


def step_written(project: Project) -> frozenset[str]:
    """The entities the project's steps write, by the bare relation name the
    synthesized :class:`~bloomery.ir.EntityIR` carries (S-0034/D-36)."""

    if project.steps is None:
        return frozenset()

    return frozenset(
        relation.rsplit(".", 1)[-1]
        for wiring in project.steps.steps
        for relation in wiring.outputs.values()
    )


# ....................... #


def relationship_column_errors(
    index: int, rel: Relationship, columns: AbcMapping[str, Collection[str]]
) -> list[BloomeryError]:
    """``rel``'s ``via`` columns against the columns of both endpoints, which
    ``columns`` must hold."""

    errors: list[BloomeryError] = []

    for from_column, to_column in sorted(rel.via.items()):
        for column, entity in ((from_column, rel.from_), (to_column, rel.to)):
            if column not in columns[entity]:
                errors.append(
                    MissingReference(
                        f"relationship {rel.name!r} via references unknown column "
                        f"{column!r} of entity {entity!r}",
                        source_path=f"entity_model: relationships[{index}].via.{from_column}",
                    )
                )

    return errors


# ....................... #


def _check_relationships(project: Project, errors: list[BloomeryError]) -> None:
    """Both endpoints exist, and the ``via`` columns do on each.

    A step output is an endpoint like an authored entity (S-0034/D-59), known
    here by name only: what it produces is the manifest's to say, and this
    stage has never seen one. So a relationship touching a step output has
    its columns checked where the step lowers, both sides together, rather
    than its authored side here and the step side one run later.
    """
    entities = project.entity_model.entities
    written = step_written(project)
    fields = {name: entity.fields.keys() for name, entity in entities.items()}

    _check_relationship_names(project, errors)

    for index, rel in enumerate(project.entity_model.relationships):
        unknown = [
            (side, name)
            for side, name in (("from", rel.from_), ("to", rel.to))
            if name not in entities and name not in written
        ]
        for side, name in unknown:
            errors.append(
                MissingReference(
                    f"relationship {rel.name!r} references unknown entity {name!r}",
                    source_path=f"entity_model: relationships[{index}].{side}",
                )
            )
        if not unknown and not {rel.from_, rel.to} & written:
            errors.extend(relationship_column_errors(index, rel, fields))


# ....................... #


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
        # S-0050/D-3: the same dependency set the template merge unions into
        # `requires_metrics`, checked here because this stage runs *before* the
        # merge and reads the spec models directly. The merge reads
        # `DerivedSpec.input_metrics` — the distinct metrics, sorted — while
        # this reader walks `inputs` by alias, because a *reference* failure has
        # to name the input it is about and the alias is that name.
        derived = metric.derived or (template.derived if template else None)
        if derived is not None:
            # By alias, not by the block: two unknown inputs would otherwise
            # share one source path, and the alias is the identity the author
            # wrote — the same reason `requires_metrics` reports its index.
            for alias in sorted(derived.inputs):
                input_metric = derived.inputs[alias].metric
                if input_metric not in metric_names:
                    errors.append(
                        MissingReference(
                            f"derived metric reads unknown metric {input_metric!r}",
                            source_path=f"{path}.derived.inputs.{alias}",
                        )
                    )
        # A ratio's operands join `requires_metrics` in the merge too
        # (S-0022/D-9); one `requires_metrics` names as well is reported there.
        ratio = metric.ratio or (template.ratio if template else None)
        if ratio is not None:
            for operand, name in (
                ("numerator", ratio.numerator),
                ("denominator", ratio.denominator),
            ):
                if name not in metric_names and name not in requires_metrics:
                    errors.append(
                        MissingReference(
                            f"ratio reads unknown metric {name!r}",
                            source_path=f"{path}.ratio.{operand}",
                        )
                    )


# ....................... #


def validate_references(project: Project, catalog: Catalog | None) -> None:
    """Run every cross-spec reference check, batched (S-0022/D-7).

    Raises one :class:`ResolutionError` aggregate listing every failure (a
    single failure is raised as itself); returns ``None`` on a clean project.
    """
    errors: list[BloomeryError] = []

    for mapping in project.mappings:
        _check_mapping(mapping, project, errors)

    _check_canonical_links(project, catalog, errors)
    _check_step_canonical_links(project, catalog, errors)
    _check_relationships(project, errors)
    _check_metrics(project, catalog, errors)

    if errors:
        if len(errors) == 1:
            raise errors[0]
        raise ResolutionError.from_collected(tuple(errors))
