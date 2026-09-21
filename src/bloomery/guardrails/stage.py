"""The guardrail stage: ``check_guardrails(draft, project=…, catalog=…)``
(S-0023/stage-shape, S-0023/D-2, S-0023/D-9).

Stage four of the pipeline, invoked from ``build_project_ir``'s seam after
typecheck. Pure: seven guards are read-only checks whose violations are
collected project-wide — together with the mart-level leaves the flattener
reports (``GrainViolation``, ``FanoutRisk``, ``MartMissingTimeDimension`` —
S-0023/D-10, S-0027/validation-compile-errors-batched-with-guardrails) — and raised as **one** :class:`GuardrailError`
aggregate, its leaves sorted by ``(source_path, type name)`` — authors fix a
spec in one round-trip (S-0019/D-6). The only amendments are the eighth
guard's path-conflict handling (shadow column + reconcile audit, S-0023
D7) and the lowering of valid ``assert:`` clauses into entity audits
(S-0023/D-8); a project with neither returns the draft unchanged.

The seventh is the metric-shape guard (S-0050), which replaced the blanket
``cumulative:`` refusal when that surface stopped being reserved.
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING

from bloomery.errors import GuardrailError, guaranteed
from bloomery.guardrails.additivity import check_additivity
from bloomery.guardrails.arithmetic import check_arithmetic
from bloomery.guardrails.asserts import lower_asserts
from bloomery.guardrails.classification import check_classification
from bloomery.guardrails.conflict import Shadow, path_conflict_amendments
from bloomery.guardrails.evidence import check_evidence
from bloomery.guardrails.exports import check_export_targets
from bloomery.guardrails.exposures import check_exposure_targets
from bloomery.guardrails.grain import check_grain
from bloomery.guardrails.imports import check_imports
from bloomery.guardrails.lineage import check_lineage_names
from bloomery.guardrails.metrics import check_metrics
from bloomery.guardrails.operands import collect_derivations
from bloomery.guardrails.quality import check_quality
from bloomery.guardrails.zone import check_zones
from bloomery.ir.nodes import with_imported
from bloomery.marts import lower_marts, lower_rollups

if TYPE_CHECKING:
    from collections.abc import Mapping

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
    # Both halves move together (S-0041/D-26): a schema column with no
    # projection is a column the SELECT cannot produce, which would compile
    # clean and fail on the first run. On a merged entity each branch takes
    # the projection of *its own* mapping's ``direct:`` path (D36) — the other
    # branch's path need not exist on this relation, which is what made D28
    # refuse the combination while one shadow stood for every source.
    #
    # ``guaranteed`` rather than a ``.get``: ``path_conflict_amendments``
    # completes every shadow over the entity's own sources, so a missing entry
    # here is that completion having stopped working — and what a ``.get``
    # would produce instead is a branch with no projection for a column the
    # schema carries, which compiles clean and fails on the first run.
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
                                    "path_conflict_amendments, which projects a path or a "
                                    "typed NULL for every source of the entity (S-0041/D-36)"
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


def check_guardrails(
    draft: ProjectIR,
    *,
    project: Project,
    catalog: Catalog | None,
    upstream: Mapping[str, ProjectIR] = MappingProxyType({}),
) -> ProjectIR:
    """Run all eight guardrails plus the data-quality leaves, the
    lineage-namespace guard and the dangling-exposure guard over the draft IR
    (S-0023/D-9; S-0033/guardrails-vs-quality-the-boundary; S-0059/the-node-id-collision-refused-at-its-cause; S-0063/D-2).

    Raises one aggregated :class:`GuardrailError` if any violation exists;
    otherwise returns the draft amended only by path-conflict handling and
    ``assert:`` lowering. Idempotent: re-running on the amended IR is the
    identity.
    """
    derivations = collect_derivations(project, catalog)
    # The resolver's view of the draft (S-0002/D-2): the same nodes plus the
    # ones this compile imported, for the three checks that resolve a name a
    # mart or a rollup wrote. Every other guard below takes the draft itself,
    # because what it judges is what this project declared — an imported node
    # was judged where it was authored, and refusing it again would send an
    # author to a document in another project.
    composed = with_imported(draft)
    violations = check_arithmetic(derivations, draft.metrics, catalog)
    violations.extend(check_grain(derivations, draft, project, catalog))
    violations.extend(check_additivity(draft))
    violations.extend(check_metrics(draft))
    violations.extend(check_lineage_names(draft))
    # Classification against grants (S-0062/D-9 S-0062/D-11): a published relation
    # carrying a `secret` column, or one granted wider than the entity the
    # column came from. Reads the draft alone — both sides are in the IR.
    violations.extend(check_classification(draft))
    # Exposure references (S-0063/D-2, `LOCKED`), asked of the authored
    # documents rather than the draft — see the module docstring for why the
    # draft is the wrong side of the flattener to ask.
    violations.extend(check_exposure_targets(project))
    # Exported names (S-0002/D-1, `LOCKED`), asked of the authored documents
    # for the reason the exposure guard is — a mart that failed to flatten is
    # absent from the draft while very much declared.
    violations.extend(check_export_targets(project))
    # Declared dependencies (S-0002/D-1, S-0002/D-8): the upstream side read from the
    # IR it arrived as, the local side from the authored documents.
    violations.extend(check_imports(project, draft, upstream))
    # Declared source zones (S-0076/r018-and-where-it-fires, S-0076 R018): asked of the draft, which
    # carries one transform chain per source — so a merged entity is answered
    # per mapping, and the mapping that declared is not sent to fix anything.
    violations.extend(check_zones(project, draft))
    # Consumer evidence (S-0070/D-4, `LOCKED`): the requirement is read from
    # the authored marts document and the facts from the draft, which is the
    # one guardrail that needs both sides — the key never enters `MartIR` (D3).
    violations.extend(check_evidence(project, draft))
    # Mart-level checks (S-0023/D-10): the flattener re-runs here as a pure
    # sibling stage; its leaves batch into the same aggregate as the rest.
    violations.extend(lower_marts(project.marts, composed).violations)
    # Rollup-level checks (S-0065/D-5, `LOCKED`): the same sibling-stage shape,
    # asked against the draft's already-resolved marts. An unprovable rollup is
    # refused rather than warned about — it is read instead of the detail table,
    # so a wrong one answers quickly and plausibly.
    violations.extend(lower_rollups(project.marts, composed).violations)
    # Data-quality leaves (S-0033/guardrails-vs-quality-the-boundary): the model-is-wrong half of this
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
