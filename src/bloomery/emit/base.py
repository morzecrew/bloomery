"""Emitter port surface (RFC 0008 §5.1, amended per ``_bloomery-changes.md``
D6 + pivot R8): the :class:`TargetEmitter` protocol, the closed
:class:`Feature` vocabulary with :class:`TargetCapabilities`, the
:class:`EmitContext` handed to every emitter, and the file-shaped
:class:`EmittedArtifact` (settles open question #1: artifacts are data —
no filesystem writes, no live-context registration in core, RFC 0008 D2).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from bloomery.errors import EmitError

if TYPE_CHECKING:
    from sqlglot import exp

    from bloomery.dialects import DialectPort
    from bloomery.ir import ProjectIR
    from bloomery.naming import NamingPolicy

# ----------------------- #

__all__ = [
    "ArtifactKind",
    "AuditBody",
    "EmitContext",
    "EmittedArtifact",
    "Feature",
    "TargetCapabilities",
    "TargetEmitter",
    "assert_unique_paths",
]


class Feature(StrEnum):
    """The closed capability vocabulary (RFC 0008 D10, amended by pivot R8
    with :attr:`CUMULATIVE` and :attr:`DERIVED_METRIC`, and by RFC 0015
    D-Q6 with :attr:`SORT_NULLS_PLACEMENT`). Shared by targets and the
    planner port (RFC 0011/0013)."""

    SEMI_ADDITIVE = "semi_additive"
    NON_ADDITIVE = "non_additive"
    CUMULATIVE = "cumulative"
    DERIVED_METRIC = "derived_metric"
    ROLE_PLAYING_DIM = "role_playing_dim"
    MULTI_FACT = "multi_fact"
    QUERY_TIME_JOIN = "query_time_join"
    ROW_LEVEL_SECURITY = "row_level_security"
    #: RFC 0015 D-Q6: NULLS FIRST/LAST ordering control. Deliberately
    #: **not** declared by the MetricFlow planner capabilities —
    #: ``order_by_names`` is direction-only, so a non-default placement is
    #: refused (``UnsupportedSortNulls``), never silently dropped.
    SORT_NULLS_PLACEMENT = "sort_nulls_placement"
    VARIANT_COLUMN = "variant_column"
    SCD_TYPE_2 = "scd_type_2"
    INCREMENTAL = "incremental"
    AUDITS = "audits"


# ....................... #


@dataclass(frozen=True, slots=True)
class TargetCapabilities:
    """A target's declared support: membership-checked; any output-reaching
    iteration must be ``sorted()`` (RFC 0008 D10)."""

    supported: frozenset[Feature]

    # ....................... #

    def supports(self, feature: Feature) -> bool:
        return feature in self.supported


# ....................... #


class ArtifactKind(StrEnum):
    """What an emitted artifact is, for callers routing the stream:
    ``MODEL`` for anything defining a relation or semantic surface, ``AUDIT``
    for custom audit bodies, ``CONFIG`` for framework scaffolding
    (``dbt_project.yml``, ``sources.yml``, ``schema.yml``), ``REPLAY`` for the
    quarantine replay merge (RFC 0016 §5.6).

    ``REPLAY`` is its own kind rather than a model because it is a *statement
    the caller runs*, not a relation the framework maintains: bloomery emits
    the merge artifact and **never** executes it (a hard invariant), and a
    caller routing the stream must be able to tell "build this" from "run this
    when you replay" without parsing SQL.
    """

    MODEL = "model"
    AUDIT = "audit"
    CONFIG = "config"
    REPLAY = "replay"


# ....................... #


@dataclass(frozen=True, slots=True)
class EmittedArtifact:
    """One file-shaped artifact as data (RFC 0008 D2): a relative ``path``,
    the full ``content`` (single trailing newline, ``\\n`` endings — RFC 0003
    §5.5 rule 5), its kind, and the SHA-256 ``checksum`` of the content."""

    path: str
    content: str
    kind: ArtifactKind
    checksum: str

    # ....................... #

    @classmethod
    def create(cls, *, path: str, content: str, kind: ArtifactKind) -> EmittedArtifact:
        """Build an artifact, computing the content checksum."""
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return cls(path=path, content=content, kind=kind, checksum=checksum)


# ....................... #


def assert_unique_paths(artifacts: list[EmittedArtifact]) -> None:
    """No two artifacts may claim one path.

    A general guard rather than a per-namespace prefix, because the namespaces
    that can collide are not obvious in advance: RFC 0016 names quality audits
    ``<entity>_<rule>``, RFC 0016 D89 names mart assertions
    ``<mart>_<assertion>``, and RFC 0017 names consistency audits after their
    outputs — all from author-chosen parts, and an emitter otherwise just
    sorts, so two artifacts at one path compiled clean and the last writer won.
    That is the two-writers-one-path collision D8/D28 refuse for relations,
    reached through the audit namespace instead.

    **Neither name is checkable alone; only the pair is.** A mart ``a``
    asserting ``b_c`` and a mart ``a_b`` asserting ``c`` are both legitimate
    declarations that produce one audit name — which is why this is a guard
    over the assembled set rather than a rule about any single name.

    Shared rather than SQLMesh's, because it stopped being SQLMesh's problem:
    until RFC 0026 the dbt emitter wrote no audit artifacts at all, so it had
    nothing to collide. Now it writes ``tests/<check>.sql`` across five
    families and needs the same guard — and a second copy of it would be the
    two-implementations-of-one-rule drift the shared lowering exists to
    prevent. Cube is not a caller: its paths are ``model/cubes/<mart>.yml`` and
    ``model/views/<mart>_view.yml`` over mart names that are already unique by
    construction, so the map is injective and the guard would have no instance.
    """
    seen: dict[str, int] = {}

    for artifact in artifacts:
        seen[artifact.path] = seen.get(artifact.path, 0) + 1

    duplicated = sorted(path for path, count in seen.items() if count > 1)

    if duplicated:
        msg = (
            f"two or more artifacts claim the same path: {', '.join(duplicated)}. "
            "Emission would write one over the other, so whichever ran last would "
            "silently win"
        )
        raise EmitError(msg)


# ....................... #


@dataclass(frozen=True, slots=True)
class AuditBody:
    """One audit as the parts a target still has to wrap (RFC 0026 D10).

    A producer in shared code returns this rather than an
    :class:`EmittedArtifact`, because an artifact carries an envelope and every
    envelope belongs to a target: SQLMesh writes ``AUDIT (name …);``, dbt writes
    a ``{{ config(severity=…) }}`` header into a file under ``test-paths``. A
    shared producer that returned a finished artifact had therefore already
    chosen a target — which is how :mod:`bloomery.emit.steps` came to be
    target-neutral by position and SQLMesh-shaped by content, and why one
    audit body could not reach dbt at all.

    ``select`` is the **unrendered** AST, not SQL text, though RFC 0026 D10
    says "rendered SELECT". Rendering here would shut the door D5 needs open:
    the dbt emitter rewrites every relation in a body to a ``ref()`` so the
    audit becomes a participant in dbt's DAG, and it can only do that to a
    tree. See ``logs/T-0003.md`` D-012.

    ``owner`` is the relation whose rows the audit judges. SQLMesh needs it to
    list the audit under that model's ``audits`` — a bare ``AUDIT`` block loads
    as a model audit and runs nowhere until something names it.
    """

    owner: str
    name: str
    select: exp.Select | exp.Union
    blocking: bool = True


# ....................... #


@dataclass(frozen=True, slots=True)
class EmitContext:
    """Everything an emitter needs beyond the IR: the dialect port, the
    naming policy, and the project fingerprint stamped into every artifact
    header (RFC 0008 D9 — applied-vs-spec drift detection downstream)."""

    dialect: DialectPort
    naming: NamingPolicy
    fingerprint: str


# ....................... #


class TargetEmitter(Protocol):
    """IR → framework artifacts. Knows nothing about SQL dialects (RFC 0008
    D1) — SQL arrives pre-neutral in the IR and renders through
    ``ctx.dialect``."""

    name: str

    # ....................... #

    def capabilities(self) -> TargetCapabilities: ...

    def emit(self, ir: ProjectIR, ctx: EmitContext) -> tuple[EmittedArtifact, ...]: ...
