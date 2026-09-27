"""The compile orchestration: ``compile_project`` (public API, spec §8) —
parsed specs in, byte-deterministic :class:`~bloomery.emit.EmittedArtifact`
tuple out. Pure data flow: resolve + typecheck + IR build (S-0021, S-0022),
fingerprint (S-0020), then the selected target emitter renders through the
selected dialect port under the naming policy (S-0025)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from bloomery.dialects import get_dialect
from bloomery.emit import EmitContext, EmittedArtifact, get_emitter
from bloomery.errors import UnsupportedByTarget
from bloomery.ir import ProjectIR, project_fingerprint
from bloomery.naming import DefaultNaming, NamingPolicy
from bloomery.quality.pattern import PATTERN_TARGET_DIALECTS, unsupported_dialects
from bloomery.resolve import build_project_ir
from bloomery.spec import Catalog, Project
from bloomery.steps import EMPTY_REGISTRY, StepRegistry

if TYPE_CHECKING:
    from bloomery.dialects import DialectPort

# ----------------------- #

__all__ = [
    "Target",
    "compile_project",
]

#: Per-target artifact counts (S-0004 (§4)). Here rather than inside each
#: emitter: the count is the same question for every target, and asking it in
#: one place is what keeps a new emitter narrated without its author
#: remembering to.
_LOG = logging.getLogger("bloomery.emit")


class Target(StrEnum):
    """The emit targets shipped in core (S-0025/D-5): SQLMesh (primary),
    Cube (semantic), dbt — the port-abstraction proof (S-0025/dbt-emitter-compatibility), which
    since S-0060 refuses two constructs and no artifact family — and
    MetricFlow, which emits the
    semantic manifest rather than models (S-0059/D-1). Extension targets
    registered via :func:`bloomery.emit.register_emitter` are addressed by
    their string name.

    ``RETRIEVAL`` (S-0011/D-6) is the one member naming an *artifact* rather
    than a consumer: it emits the retrieval manifest, which no framework reads.
    A vendor-oriented vector emitter is deliberately **not** a member — it is
    :func:`bloomery.emit.register_emitter`, out of tree, until it has an
    artifact contract someone has run (S-0011/D-10)."""

    SQLMESH = "sqlmesh"
    CUBE = "cube"
    DBT = "dbt"
    METRICFLOW = "metricflow"
    RETRIEVAL = "retrieval"


# ....................... #


def _check_pattern_transport(ir: ProjectIR, port: DialectPort) -> None:
    """S-0033/D-56's explicit-argument hatch, applied at the one seam that
    knows the requested dialect.

    The guardrail stage vets ``pattern`` rules against the *shipped* ports
    only — deliberately never the mutable registry, so a registered extension
    dialect cannot change a compile verdict ambiently. But the dialect named
    here is a declared input, not ambient state, so an extension port gets the
    same two mechanical checks (a regex surface, literal transport) the
    shipped three passed at the guardrail — instead of rendering a pattern it
    was never checked against.
    """
    if port.name in PATTERN_TARGET_DIALECTS:
        return

    failures = sorted(
        (entity.name, rule.column or rule.name, regex)
        for entity in ir.entities
        for rule in entity.quality
        if rule.kind == "pattern"
        for key, regex in rule.params
        if key == "regex" and unsupported_dialects(regex, dialects=(port,))
    )

    if failures:
        listed = "; ".join(
            f"entity {entity!r} field {field!r}: {regex!r}" for entity, field, regex in failures
        )
        msg = (
            f"dialect {port.name!r} cannot carry pattern rule(s): {listed} (S-0033 "
            "§5.3/D56) — the dialect declares no regex surface, or mangles the pattern "
            "literal in rendering. Fix: drop the rule(s), or extend the dialect port"
        )
        raise UnsupportedByTarget(msg)


# ....................... #


def _retrieval(project: Project) -> Mapping[str, Any] | None:
    """The authored retrieval document as plain data, for the target that writes
    the manifest (S-0011/D-6).

    Dumped here, at the one seam that sees both the specs and the emitters,
    because the emit side consumes IR and never spec models — and the retrieval
    kind reaches no IR node: nothing in the compile pipeline lowers a profile,
    and the refusals that need types and keys have already fired at the
    guardrail stage. ``by_alias`` because the projection key is spelled
    ``return`` in the document and in the manifest, and ``exclude_none`` because
    a manifest key meaning "no lexical side" is the key's absence, not a null.

    ``None`` for a project that authored no retrieval document, which is what
    keeps one that does not retrieve unchanged in every target.
    """

    if project.retrieval is None:
        return None

    return project.retrieval.model_dump(mode="json", by_alias=True, exclude_none=True)


# ....................... #


def compile_project(
    project: Project,
    *,
    target: Target | str,
    dialect: str,
    naming: NamingPolicy | None = None,
    catalog: Catalog | None = None,
    steps: StepRegistry = EMPTY_REGISTRY,
    upstream: Mapping[str, ProjectIR] = MappingProxyType({}),
) -> tuple[EmittedArtifact, ...]:
    """Compile a parsed project into target artifacts (spec §8).

    Pure function of its inputs: same specs in ⇒ byte-identical artifacts
    out, across processes and hash seeds (S-0020). ``steps`` is the frozen
    step registry (S-0034/purity-the-registry-is-a-compile-input) — a compile *input*, because reading step
    files from disk would break that purity outright, and because a registry
    that cannot be assembled from a spec is a registry a spec cannot use to
    load code. ``naming`` defaults to
    :class:`~bloomery.naming.DefaultNaming` (the S-0025 signature spells
    the default inline; a ``None`` sentinel avoids a call in the signature).
    """
    ir = build_project_ir(project, catalog=catalog, steps=steps, upstream=upstream)
    emitter = get_emitter(str(target))
    context = EmitContext(
        dialect=get_dialect(dialect),
        naming=naming if naming is not None else DefaultNaming(),
        fingerprint=project_fingerprint(ir),
        fx_rates=ir.fx_rates,
        retrieval=_retrieval(project),
    )
    _check_pattern_transport(ir, context.dialect)
    artifacts = emitter.emit(ir, context)
    _LOG.info("emit: %d artifact(s) for target %s on dialect %s", len(artifacts), target, dialect)
    if _LOG.isEnabledFor(logging.DEBUG):
        # Guarded because the join walks every artifact to build a string no
        # INFO listener will read — the one sanctioned read of logger state
        # (D3), and the reason it is sanctioned is exactly this shape.
        _LOG.debug("emit: %s", ", ".join(artifact.path for artifact in artifacts))
    return artifacts
