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
from bloomery.ir import project_fingerprint
from bloomery.naming import DefaultNaming
from bloomery.resolve import build_project_ir
from bloomery.steps import EMPTY_REGISTRY

if TYPE_CHECKING:
    from bloomery.naming import NamingPolicy
    from bloomery.spec import Catalog, Project
    from bloomery.steps import StepRegistry

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
    return emitter.emit(ir, context)
