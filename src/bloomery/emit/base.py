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

if TYPE_CHECKING:
    from bloomery.dialects import DialectPort
    from bloomery.ir import ProjectIR
    from bloomery.naming import NamingPolicy

__all__ = [
    "ArtifactKind",
    "EmitContext",
    "EmittedArtifact",
    "Feature",
    "TargetCapabilities",
    "TargetEmitter",
]


class Feature(StrEnum):
    """The closed capability vocabulary (RFC 0008 D10, amended by pivot R8
    with :attr:`CUMULATIVE` and :attr:`DERIVED_METRIC`). Shared by targets
    and, later, the planner port (RFC 0011/0013)."""

    SEMI_ADDITIVE = "semi_additive"
    NON_ADDITIVE = "non_additive"
    CUMULATIVE = "cumulative"
    DERIVED_METRIC = "derived_metric"
    ROLE_PLAYING_DIM = "role_playing_dim"
    MULTI_FACT = "multi_fact"
    QUERY_TIME_JOIN = "query_time_join"
    ROW_LEVEL_SECURITY = "row_level_security"
    VARIANT_COLUMN = "variant_column"
    SCD_TYPE_2 = "scd_type_2"
    INCREMENTAL = "incremental"
    AUDITS = "audits"


@dataclass(frozen=True, slots=True)
class TargetCapabilities:
    """A target's declared support: membership-checked; any output-reaching
    iteration must be ``sorted()`` (RFC 0008 D10)."""

    supported: frozenset[Feature]

    def supports(self, feature: Feature) -> bool:
        return feature in self.supported


class ArtifactKind(StrEnum):
    """What an emitted artifact is, for callers routing the stream."""

    MODEL = "model"
    AUDIT = "audit"


@dataclass(frozen=True, slots=True)
class EmittedArtifact:
    """One file-shaped artifact as data (RFC 0008 D2): a relative ``path``,
    the full ``content`` (single trailing newline, ``\\n`` endings — RFC 0003
    §5.5 rule 5), its kind, and the SHA-256 ``checksum`` of the content."""

    path: str
    content: str
    kind: ArtifactKind
    checksum: str

    @classmethod
    def create(cls, *, path: str, content: str, kind: ArtifactKind) -> EmittedArtifact:
        """Build an artifact, computing the content checksum."""
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return cls(path=path, content=content, kind=kind, checksum=checksum)


@dataclass(frozen=True, slots=True)
class EmitContext:
    """Everything an emitter needs beyond the IR: the dialect port, the
    naming policy, and the project fingerprint stamped into every artifact
    header (RFC 0008 D9 — applied-vs-spec drift detection downstream)."""

    dialect: DialectPort
    naming: NamingPolicy
    fingerprint: str


class TargetEmitter(Protocol):
    """IR → framework artifacts. Knows nothing about SQL dialects (RFC 0008
    D1) — SQL arrives pre-neutral in the IR and renders through
    ``ctx.dialect``."""

    name: str

    def capabilities(self) -> TargetCapabilities: ...

    def emit(self, ir: ProjectIR, ctx: EmitContext) -> tuple[EmittedArtifact, ...]: ...
