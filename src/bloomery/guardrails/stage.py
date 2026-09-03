"""The guardrail stage: ``check_guardrails(draft, project=…, catalog=…)``
(RFC 0006 §5.1, D2, D9).

Stage four of the pipeline, invoked from ``build_project_ir``'s seam after
typecheck. Pure: seven guards are read-only checks whose violations are
collected project-wide — together with the mart-level leaves the flattener
reports (``GrainViolation``, ``FanoutRisk``, ``MartMissingTimeDimension`` —
RFC 0006 D10, RFC 0010 §5.5) — and raised as **one** :class:`GuardrailError`
aggregate, its leaves sorted by ``(source_path, type name)`` — authors fix a
spec in one round-trip (RFC 0002 D6). The only amendments are the eighth
guard's path-conflict handling (shadow column + reconcile audit, RFC 0006
D7) and the lowering of valid ``assert:`` clauses into entity audits
(RFC 0006 D8); a project with neither returns the draft unchanged.

The seventh is the metric-shape guard (RFC 0034), which replaced the blanket
``cumulative:`` refusal when that surface stopped being reserved.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from bloomery.errors import GuardrailError, guaranteed
from bloomery.guardrails.additivity import check_additivity
from bloomery.guardrails.arithmetic import check_arithmetic
from bloomery.guardrails.asserts import lower_asserts
from bloomery.guardrails.conflict import Shadow, path_conflict_amendments
from bloomery.guardrails.grain import check_grain
from bloomery.guardrails.metrics import check_metrics
from bloomery.guardrails.operands import collect_derivations
from bloomery.guardrails.quality import check_quality
from bloomery.marts import lower_marts

if TYPE_CHECKING:
    from bloomery.ir import AuditIR, EntityIR, ProjectIR
    from bloomery.spec.catalog import Catalog
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "check_guardrails",
]


def _amended_entity(
    entity: EntityIR,
    lowered: dict[str, list[AuditIR]],
    shadows: dict[str, list[Shadow]],
    reconcile: dict[str, list[AuditIR]],
) -> EntityIR:
    audits = tuple(
        sorted(
            lowered.get(entity.name, []) + reconcile.get(entity.name, []),
            key=lambda audit: (audit.kind, audit.column),
        )
    )
    present = {column.name for column in entity.columns}
    extra = [shadow for shadow in shadows.get(entity.name, []) if shadow.column.name not in present]

    if audits == entity.audits and not extra:
        return entity

    columns = tuple(
        sorted(
            [*entity.columns, *(shadow.column for shadow in extra)], key=lambda column: column.name
        )
    )
    # Both halves move together (RFC 0024 D26): a schema column with no
    # projection is a column the SELECT cannot produce, which would compile
    # clean and fail on the first run. On a merged entity each branch takes
    # the projection of *its own* mapping's ``direct:`` path (D36) — the other
    # branch's path need not exist on this relation, which is what made D28
    # refuse the combination while one shadow stood for every source.
    #
    # ``guaranteed`` rather than a ``.get``: every mapping producing the column
    # records a path or the entity was refused in ``resolve.build``, so a
    # missing entry here is that refusal having stopped working, and the
    # NULL-filled column it would produce is exactly the silence D28 named.
    sources = tuple(
        replace(
            source,
            columns=tuple(
                sorted(
                    [
                        *source.columns,
                        *(
                            guaranteed(
                                (
                                    projection
                                    for relation, projection in shadow.projections.items()
                                    if relation == source.relation
                                ),
                                expected=(
                                    f"a {shadow.column.name!r} projection for source "
                                    f"{source.relation!r} of entity {entity.name!r}"
                                ),
                                by=(
                                    "the D36 agreement refusal, which requires every mapping "
                                    "producing the column to record a 'direct:' path"
                                ),
                            )
                            for shadow in extra
                        ),
                    ],
                    key=lambda column: column.name,
                )
            ),
        )
        for source in entity.sources
    )
    return replace(entity, columns=columns, sources=sources, audits=audits)


# ....................... #


def check_guardrails(draft: ProjectIR, *, project: Project, catalog: Catalog | None) -> ProjectIR:
    """Run all eight guardrails plus the data-quality leaves over the draft IR
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
    violations.extend(check_metrics(draft))
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
