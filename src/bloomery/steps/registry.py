"""The step registry: manifests as a compile **input** (RFC 0017 §5.3, D3).

Bloomery must not read step files from disk — that would break the no-I/O
invariant (RFC 0003) outright. So the caller assembles the registry and hands
it to :func:`~bloomery.compile.compile_project`, and **there is no dynamic
loading path at all**: no import hooks, no entry points, no paths in specs.
That absence is the whole security property. An authored spec names a step by
``ref@version`` and cannot name anything else; it can no more load code than
a spelling of a metric name can.

The rule is scoped to **compile time** (D13). The generated wrapper for a
``python_model`` imports its manifest's ``entrypoint`` when SQLMesh runs it —
that is the ordinary execution path for platform-owned code, not an exception
to the rule, and registry *build* (caller-side tooling) is what verifies the
entrypoint resolves before any of it reaches the compiler.

**Why the snapshot** (D14). The registry copies its mappings into canonically
sorted tuples at construction, and every :class:`StepManifest` it holds is a
frozen model. Either alone would be insufficient theatre: the copy stops the
caller mutating the dict afterwards, the frozen leaves stop it mutating a
manifest in place. Together they make "same specs in ⇒ byte-identical
artifacts out" independent of anything the caller does next.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bloomery.errors import StepError, UnknownStep
from bloomery.steps.manifest import StepManifest

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "EMPTY_REGISTRY",
    "StepRegistry",
]

#: ``(ref, version)`` — a step's identity (§5.2).
StepKey = tuple[str, int]


def _snapshot(source: Mapping[StepKey, object] | None) -> tuple[tuple[StepKey, object], ...]:
    """A mapping frozen into canonically sorted pairs.

    Sorted rather than insertion-ordered because the registry is an input to a
    function whose output must not depend on how the caller happened to build
    a dict (RFC 0003: no ambient nondeterminism, tuples not sets).
    """
    if source is None:
        return ()
    return tuple(sorted(source.items()))


def _refuse_key_disagreement(steps: tuple[tuple[StepKey, StepManifest], ...]) -> None:
    """A step's key must be the identity its manifest declares (RFC 0017 D55).

    The registry is keyed by ``(ref, version)`` and the manifest carries the
    same pair, so nothing stops the two disagreeing — and when they do, the
    disagreement is silent rather than loud: ``lower_steps`` builds ``StepIR``
    from the *manifest* identity while the wiring's canonical links and
    ``on_fail: fail`` rules are keyed by the *wiring* identity, so those
    simply stop matching and are dropped without a word.

    Checked at construction because the registry is a frozen compile input:
    this is the one moment it can be checked once for every later reader,
    which is the same argument that makes collision an error in the transform
    registry (RFC 0004 D6).
    """
    for (ref, version), manifest in steps:
        if manifest.ref == ref and manifest.version == version:
            continue
        msg = (
            f"step registry key {ref}@{version} does not match the identity its manifest "
            f"declares ({manifest.ref}@{manifest.version}). Lowering reads the manifest's "
            "identity and the wiring reads the key, so a mismatch silently drops that step's "
            "canonical links and quality rules instead of failing (feature: steps). "
            "Fix: key each manifest by its own ref and version"
        )
        raise StepError(msg)


@dataclass(frozen=True, slots=True, init=False)
class StepRegistry:
    """Every step available to a compilation, keyed by ``(ref, version)``.

    ``macro_bodies`` and ``sql_bodies`` carry the SQL text of Tier 1 and Tier
    2 steps, which bloomery *parses* at compile (§5.8) — text in, AST out, no
    execution. A ``python_model`` has no body here at all: bloomery never sees
    its code, only the manifest that describes it.
    """

    _steps: tuple[tuple[StepKey, StepManifest], ...]
    _macro_bodies: tuple[tuple[StepKey, str], ...]
    _sql_bodies: tuple[tuple[StepKey, str], ...]

    def __init__(
        self,
        steps: Mapping[StepKey, StepManifest] | None = None,
        *,
        macro_bodies: Mapping[StepKey, str] | None = None,
        sql_bodies: Mapping[StepKey, str] | None = None,
    ) -> None:
        object.__setattr__(self, "_steps", _snapshot(steps))
        object.__setattr__(self, "_macro_bodies", _snapshot(macro_bodies))
        object.__setattr__(self, "_sql_bodies", _snapshot(sql_bodies))
        _refuse_key_disagreement(self._steps)

    @property
    def steps(self) -> tuple[tuple[StepKey, StepManifest], ...]:
        """Every ``((ref, version), manifest)`` pair, sorted."""
        return self._steps

    def get(self, ref: str, version: int) -> StepManifest | None:
        """The manifest for one ``ref@version``, or ``None``. Callers that
        want the refusal want :meth:`resolve`."""
        for (key_ref, key_version), manifest in self._steps:
            if key_ref == ref and key_version == version:
                return manifest
        return None

    def versions_of(self, ref: str) -> tuple[int, ...]:
        """Every version of ``ref`` this registry holds, ascending."""
        return tuple(sorted(version for (key_ref, version), _ in self._steps if key_ref == ref))

    def resolve(self, ref: str, version: int, *, source_path: str | None = None) -> StepManifest:
        """The manifest for ``ref@version``, or :class:`UnknownStep`.

        The message names the versions that *are* available (D3) — the whole
        point of the refusal is that an author who pinned ``@3`` against a
        registry holding ``@2`` learns that in one line, rather than reading
        "unknown step" and going to ask someone.
        """
        manifest = self.get(ref, version)
        if manifest is not None:
            return manifest
        available = self.versions_of(ref)
        if available:
            detail = f"step {ref!r} has no version {version}; available: " + ", ".join(
                f"@{candidate}" for candidate in available
            )
        elif self._steps:
            known = ", ".join(sorted({key_ref for (key_ref, _), _ in self._steps}))
            detail = f"no step {ref!r} is registered; registered steps: {known}"
        else:
            detail = (
                f"no step {ref!r} is registered, and the registry is empty — "
                "pass one to compile_project(steps=…)"
            )
        msg = f"{detail} (RFC 0017 §5.3)"
        # ``available`` is the same list the message renders (RFC 0020 §5.4):
        # the suggestion exposes a value already computed here, never a
        # second search that could disagree with the sentence beside it.
        raise UnknownStep(msg, source_path=source_path, available_versions=available)

    def macro_body(self, ref: str, version: int) -> str | None:
        return _lookup(self._macro_bodies, ref, version)

    def sql_body(self, ref: str, version: int) -> str | None:
        return _lookup(self._sql_bodies, ref, version)


def _lookup(pairs: tuple[tuple[StepKey, str], ...], ref: str, version: int) -> str | None:
    for (key_ref, key_version), body in pairs:
        if key_ref == ref and key_version == version:
            return body
    return None


#: The default for :func:`~bloomery.compile.compile_project`: a project that
#: references no step needs no registry, and must not be made to build one.
EMPTY_REGISTRY = StepRegistry()
