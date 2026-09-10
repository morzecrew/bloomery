"""The dangling-exposure guard (RFC 0056 D2, `LOCKED`): an exposure naming a
metric or a mart the project does not declare.

An exposure is the one spec document that is entirely references — a name, a
kind, an owner and a list of things it reads — so a reference that resolves to
nothing leaves a document that claims something and asserts nothing. The
failure is silent by construction: `plan()` walks the exposures whose
dependencies match a change, a dependency matching no node matches no change,
and the report comes back clean. That is worse than having no exposure at all,
because a reader trusts a report that names nobody.

**Against the authored documents, not the draft IR.** ``ProjectIR.marts``
carries only the marts that flattened cleanly — the flattener runs as a sibling
stage and its violations batch into the same aggregate — so a mart that failed
its own check is absent from the draft while very much declared. Reading the
draft would add a second, false leaf to that batch: *exposure names an
undeclared mart*, for a mart the author can see in the file in front of them.
The authored names are what D2 means by declared.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.errors import DanglingExposure

if TYPE_CHECKING:
    from bloomery.errors import GuardrailError
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "check_exposure_targets",
]


def _declared(candidates: frozenset[str]) -> str:
    """What the project does declare, for the refusal to end on.

    The whole list rather than an edit-distance suggestion: the mistake this
    catches is a name renamed in one document and not the other, and the author
    needs to see what is actually there — a nearest-match would name one
    candidate and hide the rename. Capped, because a refusal that prints eighty
    metric names is one nobody reads to the end.
    """

    if not candidates:
        return "(none)"

    shown = sorted(candidates)
    listed = ", ".join(repr(candidate) for candidate in shown[:8])
    suffix = f", … ({len(shown)} in total)" if len(shown) > 8 else ""
    return f"{listed}{suffix}"


# ....................... #


def check_exposure_targets(project: Project) -> list[GuardrailError]:
    """Refuse every exposure dependency that names nothing (D2).

    Every dangling name is reported, not merely the first: an exposure is
    authored as a list, and a list is usually got wrong in the same way more
    than once — one refusal per round-trip would make an author fix a rename
    four times.

    A **rollup** named under ``marts:`` gets its own message. It is a relation
    of the gold layer and a dashboard can legitimately read one, so "not
    declared" would be a refusal an author could disprove by opening the marts
    document; what is true is narrower — this list names marts, and RFC 0056
    §5.1 scopes it that way (logs/T-0038.md).

    That refusal was first argued from a rollup not being a node of the lineage
    graph, and RFC 0067 made it one — so it is restated here on the ground that
    survives (D9, logs/T-0039.md). Admitting a rollup is a **grammar** change
    with two legs beyond this guard: the dbt emitter lowers a mart dependency
    to a ``ref()`` on that mart's relation, and `plan()` matches the dependency
    against a ``mart:`` change subject. Widening one of the three and not the
    others is how a declared dependency comes to report clean, which is the
    failure this whole guard exists to refuse.
    """

    if project.exposures is None:
        return []

    metrics = (
        frozenset(project.metric_set.metrics) if project.metric_set is not None else frozenset()
    )
    marts = frozenset(project.marts.marts) if project.marts is not None else frozenset()
    rollups = frozenset(project.marts.rollups) if project.marts is not None else frozenset()

    errors: list[GuardrailError] = []

    for name, exposure in sorted(project.exposures.exposures.items()):
        source_path = f"exposures: exposures.{name}"

        for metric in sorted(exposure.depends_on.metrics):
            if metric in metrics:
                continue
            msg = (
                f"exposure {name!r} depends on metric {metric!r}, which this project does not "
                f"declare. An exposure pointing at nothing reports clean — it names no consumer "
                f"of a change that should reach one (RFC 0056 D2). Fix: correct the name, or "
                f"declare the metric. Declared metrics: {_declared(metrics)}"
            )
            errors.append(DanglingExposure(msg, source_path=source_path))

        for mart in sorted(exposure.depends_on.marts):
            if mart in marts:
                continue
            detail = (
                "which this project declares as a rollup rather than a mart. An exposure's "
                "'marts:' names marts (RFC 0056 §5.1). Fix: name the mart the rollup is of"
                if mart in rollups
                else f"which this project does not declare. An exposure pointing at nothing "
                f"reports clean — it names no consumer of a change that should reach one "
                f"(RFC 0056 D2). Fix: correct the name, or declare the mart. Declared marts: "
                f"{_declared(marts)}"
            )
            errors.append(
                DanglingExposure(
                    f"exposure {name!r} depends on mart {mart!r}, {detail}", source_path=source_path
                )
            )

    return errors
