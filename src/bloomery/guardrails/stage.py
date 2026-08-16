"""The guardrail stage: ``check_guardrails(draft, project=…, catalog=…)``
(RFC 0006 §5.1, D2, D9).

Stage four of the pipeline, invoked from ``build_project_ir``'s seam after
typecheck. Pure: six guards are read-only checks whose violations are
collected project-wide — together with the mart-level leaves the flattener
reports (``GrainViolation``, ``FanoutRisk``, ``MartMissingTimeDimension`` —
RFC 0006 D10, RFC 0010 §5.5) — and raised as **one** :class:`GuardrailError`
aggregate, its leaves sorted by ``(source_path, type name)`` — authors fix a
spec in one round-trip (RFC 0002 D6). The only amendments are the seventh
guard's path-conflict handling (shadow column + reconcile audit, RFC 0006
D7) and the lowering of valid ``assert:`` clauses into entity audits
(RFC 0006 D8); a project with neither returns the draft unchanged.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from bloomery.errors import GuardrailError
from bloomery.guardrails.additivity import check_additivity
from bloomery.guardrails.arithmetic import check_arithmetic
from bloomery.guardrails.asserts import lower_asserts
from bloomery.guardrails.conflict import path_conflict_amendments
from bloomery.guardrails.grain import check_grain
from bloomery.guardrails.operands import collect_derivations
from bloomery.guardrails.quality import check_quality
from bloomery.marts import lower_marts

if TYPE_CHECKING:
    from bloomery.ir import AuditIR, ColumnIR, EntityIR, ProjectIR, SourceColumnIR
    from bloomery.spec.catalog import Catalog
    from bloomery.spec.project import Project

__all__ = [
    "check_guardrails",
]


def _amended_entity(
    entity: EntityIR,
    lowered: dict[str, list[AuditIR]],
    shadows: dict[str, list[tuple[ColumnIR, SourceColumnIR]]],
    reconcile: dict[str, list[AuditIR]],
) -> EntityIR:
    audits = tuple(
        sorted(
            lowered.get(entity.name, []) + reconcile.get(entity.name, []),
            key=lambda audit: (audit.kind, audit.column),
        )
    )
    present = {column.name for column in entity.columns}
    extra = [pair for pair in shadows.get(entity.name, []) if pair[0].name not in present]
    if audits == entity.audits and not extra:
        return entity
    columns = tuple(
        sorted([*entity.columns, *(column for column, _ in extra)], key=lambda column: column.name)
    )
    # Both halves move together (RFC 0024 D26): a schema column with no
    # projection is a column the SELECT cannot produce, which would compile
    # clean and fail on the first run. ``direct:`` is refused on a merged
    # entity (D28), so ``extra`` is empty for every entity with more than one
    # source and the comprehension amends the only one there is — written over
    # ``sources`` rather than over ``sources[0]`` so that the day D28 lifts,
    # this reads as an unfinished fan-out instead of a silent single-branch
    # amendment.
    sources = tuple(
        replace(
            source,
            columns=tuple(
                sorted(
                    [*source.columns, *(projection for _, projection in extra)],
                    key=lambda column: column.name,
                )
            ),
        )
        for source in entity.sources
    )
    return replace(entity, columns=columns, sources=sources, audits=audits)


def check_guardrails(draft: ProjectIR, *, project: Project, catalog: Catalog | None) -> ProjectIR:
    """Run all seven guardrails plus the data-quality leaves over the draft IR
    (RFC 0006 D9; RFC 0016 §5.9).

    Raises one aggregated :class:`GuardrailError` if any violation exists;
    otherwise returns the draft amended only by path-conflict handling and
    ``assert:`` lowering. Idempotent: re-running on the amended IR is the
    identity.
    """
    derivations = collect_derivations(project, catalog)
    violations = check_arithmetic(derivations, draft.metrics, catalog)
    violations.extend(check_grain(derivations, draft, project, catalog))
    violations.extend(check_additivity(draft))
    # Mart-level checks (RFC 0006 D10): the flattener re-runs here as a pure
    # sibling stage; its leaves batch into the same aggregate as the rest.
    violations.extend(lower_marts(project.marts, draft).violations)
    # Data-quality leaves (RFC 0016 §5.9): the model-is-wrong half of this
    # RFC, batched into the same aggregate as everything else.
    violations.extend(check_quality(draft, project))
    assert_errors, lowered = lower_asserts(project, draft)
    violations.extend(assert_errors)
    if violations:
        ordered = tuple(sorted(violations, key=lambda v: (v.source_path or "", type(v).__name__)))
        raise GuardrailError.from_collected(ordered)
    shadows, reconcile = path_conflict_amendments(derivations, draft)
    entities = tuple(
        _amended_entity(entity, lowered, shadows, reconcile) for entity in draft.entities
    )
    if entities == draft.entities:
        return draft
    return replace(draft, entities=entities)
