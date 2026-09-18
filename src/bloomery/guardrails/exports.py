"""The dangling-export guard (S-0002/D-1, `LOCKED`): an export naming an
entity, mart or metric the project does not declare.

An export list is entirely references — three lists of names and nothing else —
so a name that resolves to nothing leaves a document that claims a boundary and
publishes none of it. The failure is silent twice over: nothing upstream builds
an export, so nothing upstream notices, and downstream the name is simply absent
from the surface, which is indistinguishable from the upstream having chosen not
to publish it. The author who can see the mistake is the one holding the list,
and this is the only stage that reads it beside what the project declares.

**Against the authored documents, not the draft IR.** ``ProjectIR.marts``
carries only the marts that flattened cleanly — the flattener runs as a sibling
stage and its violations batch into the same aggregate — so a mart that failed
its own check is absent from the draft while very much declared. Reading the
draft would add a second, false leaf to that batch: *export names an undeclared
mart*, for a mart the author can see in the file in front of them. This is
`check_exposure_targets`'s argument, unchanged, because the two documents are
the same shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.errors import DanglingExport

if TYPE_CHECKING:
    from bloomery.errors import GuardrailError
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "check_export_targets",
]


def _declared(candidates: frozenset[str]) -> str:
    """What the project does declare, for the refusal to end on.

    The whole list rather than an edit-distance suggestion, and capped: the
    same reasoning, and the same cap, as the dangling-exposure guard's — the
    mistake here is a name renamed in one document and not the other, and a
    nearest-match would name one candidate and hide the rename.
    """

    if not candidates:
        return "(none)"

    shown = sorted(candidates)
    listed = ", ".join(repr(candidate) for candidate in shown[:8])
    suffix = f", … ({len(shown)} in total)" if len(shown) > 8 else ""
    return f"{listed}{suffix}"


# ....................... #


def check_export_targets(project: Project) -> list[GuardrailError]:
    """Refuse every exported name that names nothing (D1).

    Every dangling name is reported rather than the first: an export list is
    authored as three lists, and a list is usually got wrong in the same way
    more than once — one refusal per round-trip would make an author fix a
    rename four times.

    A **rollup** under ``marts:`` is refused with its own message. It is a
    relation of the gold layer and publishing one is a reasonable thing to
    want, so "not declared" would be a refusal an author could disprove by
    opening the marts document. What is true is narrower: this list names
    marts, and S-0002 (§5.1) scopes it that way. Admitting a rollup is a
    **grammar** change with legs beyond this guard — §5.5 lowers an exported
    mart to a cross-project ``ref()`` on that mart's relation, and a rollup's
    relation is a different thing — so widening one leg and not the others is
    how an export comes to publish something nothing can reference. The same
    argument the exposure guard makes for the same word.
    """

    if project.exports is None:
        return []

    # Spelled `frozenset[str]()` rather than a bare `frozenset()`: the latter
    # infers `frozenset[Unknown]`, which unions with the populated branch and
    # makes every use below partially unknown.
    entities = frozenset(project.entity_model.entities)
    marts = frozenset(project.marts.marts) if project.marts is not None else frozenset[str]()
    rollups = frozenset(project.marts.rollups) if project.marts is not None else frozenset[str]()
    metrics = (
        frozenset(project.metric_set.metrics)
        if project.metric_set is not None
        else frozenset[str]()
    )

    errors: list[GuardrailError] = []
    source_path = "exports: exports"

    for entity in sorted(project.exports.exports.entities):
        if entity in entities:
            continue
        errors.append(
            DanglingExport(
                f"exports entity {entity!r}, which this project does not declare. An export "
                f"naming nothing publishes nothing while reading as a published surface, and "
                f"the refusal downstream names the upstream author's list (S-0002/D-1). Fix: "
                f"correct the name, or declare the entity. Declared entities: "
                f"{_declared(entities)}",
                source_path=source_path,
            )
        )

    for mart in sorted(project.exports.exports.marts):
        if mart in marts:
            continue
        detail = (
            "which this project declares as a rollup rather than a mart. An export list's "
            "'marts:' names marts (S-0002 (§5.1)). Fix: export the mart the rollup is of"
            if mart in rollups
            else f"which this project does not declare. An export naming nothing publishes "
            f"nothing while reading as a published surface (S-0002/D-1). Fix: correct the "
            f"name, or declare the mart. Declared marts: {_declared(marts)}"
        )
        errors.append(DanglingExport(f"exports mart {mart!r}, {detail}", source_path=source_path))

    for metric in sorted(project.exports.exports.metrics):
        if metric in metrics:
            continue
        errors.append(
            DanglingExport(
                f"exports metric {metric!r}, which this project does not declare. An export "
                f"naming nothing publishes nothing while reading as a published surface "
                f"(S-0002/D-1). Fix: correct the name, or declare the metric. Declared "
                f"metrics: {_declared(metrics)}",
                source_path=source_path,
            )
        )

    return errors
