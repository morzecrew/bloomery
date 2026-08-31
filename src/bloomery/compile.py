"""The compile orchestration: ``compile_project`` (public API, spec §8) —
parsed specs in, byte-deterministic :class:`~bloomery.emit.EmittedArtifact`
tuple out. Pure data flow: resolve + typecheck + IR build (RFC 0004/0005),
fingerprint (RFC 0003), then the selected target emitter renders through the
selected dialect port under the naming policy (RFC 0008)."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from bloomery.dialects import get_dialect
from bloomery.emit import EmitContext, EmittedArtifact, get_emitter
from bloomery.errors import UnsupportedByTarget
from bloomery.ir import project_fingerprint
from bloomery.naming import DefaultNaming, NamingPolicy
from bloomery.quality.pattern import PATTERN_TARGET_DIALECTS, unsupported_dialects
from bloomery.resolve import build_project_ir
from bloomery.spec import Catalog, Project
from bloomery.steps import EMPTY_REGISTRY, StepRegistry

if TYPE_CHECKING:
    from bloomery.dialects import DialectPort
    from bloomery.ir import ProjectIR

# ----------------------- #

__all__ = [
    "Target",
    "compile_project",
]


class Target(StrEnum):
    """The emit targets shipped in core (RFC 0008 D5): SQLMesh (primary),
    Cube (semantic), and dbt — the port-abstraction proof (RFC 0008 §5.5),
    minimal but honest, documented as such. Extension targets registered via
    :func:`bloomery.emit.register_emitter` are addressed by their string
    name."""

    SQLMESH = "sqlmesh"
    CUBE = "cube"
    DBT = "dbt"


# ....................... #


def _check_pattern_transport(ir: ProjectIR, port: DialectPort) -> None:
    """RFC 0016 D56's explicit-argument hatch, applied at the one seam that
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
            f"dialect {port.name!r} cannot carry pattern rule(s): {listed} (RFC 0016 "
            "§5.3/D56) — the dialect declares no regex surface, or mangles the pattern "
            "literal in rendering. Fix: drop the rule(s), or extend the dialect port"
        )
        raise UnsupportedByTarget(msg)


# ....................... #


def compile_project(
    project: Project,
    *,
    target: Target | str,
    dialect: str,
    naming: NamingPolicy | None = None,
    catalog: Catalog | None = None,
    steps: StepRegistry = EMPTY_REGISTRY,
) -> tuple[EmittedArtifact, ...]:
    """Compile a parsed project into target artifacts (spec §8).

    Pure function of its inputs: same specs in ⇒ byte-identical artifacts
    out, across processes and hash seeds (RFC 0003). ``steps`` is the frozen
    step registry (RFC 0017 §5.3) — a compile *input*, because reading step
    files from disk would break that purity outright, and because a registry
    that cannot be assembled from a spec is a registry a spec cannot use to
    load code. ``naming`` defaults to
    :class:`~bloomery.naming.DefaultNaming` (the RFC 0008 signature spells
    the default inline; a ``None`` sentinel avoids a call in the signature).
    """
    ir = build_project_ir(project, catalog=catalog, steps=steps)
    emitter = get_emitter(str(target))
    context = EmitContext(
        dialect=get_dialect(dialect),
        naming=naming if naming is not None else DefaultNaming(),
        fingerprint=project_fingerprint(ir),
    )
    _check_pattern_transport(ir, context.dialect)
    return emitter.emit(ir, context)
