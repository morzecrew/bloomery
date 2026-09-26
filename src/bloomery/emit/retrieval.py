"""The retrieval manifest (S-0011/the-manifest, S-0011/D-6): one artifact,
``retrieval_manifest.json``, carrying every declared retrieval profile with its
semantic space inlined.

A target of its own rather than a file alongside another target's tree
(S-0011/D-6): a project's retrieval contract is independent of which analytical
framework it compiles for, and :class:`~bloomery.emit.metricflow.MetricFlowEmitter`
already established that a target may emit one manifest and no models. What this
member names is an artifact rather than a consumer — no framework reads it, and
that asymmetry in the enum is the reason the row carrying it is graded
``ASSUMED``.

The space is **inlined** on every profile rather than referenced by name
(S-0011/D-7): the consumer is a runtime with no access to the spec tree, so a
manifest naming ``chunk_space`` and nothing else would send its reader looking
for a file bloomery does not emit. The cost is a space repeated once per profile
that claims it.

Nothing here reads a vector, resolves an encoder identity, or names a vector
store (S-0011/D-2, S-0011/where-the-boundary-would-break). An encoder is three
strings copied through.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from bloomery.emit.base import ArtifactKind, EmittedArtifact
from bloomery.ir import Layer

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bloomery.emit.base import EmitContext
    from bloomery.ir import ProjectIR
    from bloomery.naming import NamingPolicy

# ----------------------- #

__all__ = [
    "MANIFEST_PATH",
    "RetrievalEmitter",
    "manifest",
    "manifest_json",
]

#: The one artifact this target emits, at the root for the reason the semantic
#: manifest sits there (S-0059/D-5): a project holds one retrieval contract, and
#: nothing else in the emitted tree competes for the name.
MANIFEST_PATH = "retrieval_manifest.json"

#: The manifest's own version, beside the profiles rather than in the filename.
#: A consumer reads one key to know whether it understands the document, which is
#: what ``retrieval_version`` does for the authored side.
MANIFEST_VERSION = 1


def _relation(relation: Mapping[str, str], naming: NamingPolicy) -> dict[str, str]:
    """One corpus relation, resolved through the naming policy.

    The logical name is kept beside the physical pair: a runtime interpolates
    ``namespace``/``table``, and a human reading the manifest against the specs
    needs the name the documents use. Split rather than dotted because the
    grammar promises nothing about quoting — a consumer that has to quote each
    part cannot recover them from one string.

    A profile's relation names exactly one of a mart or an entity (the spec
    grammar refuses anything else), so the single pair is the whole of it.
    """

    kind, name = next(iter(sorted(relation.items())))
    namespace, table = naming.relation(name, Layer.GOLD if kind == "mart" else Layer.SILVER)
    return {"kind": kind, "name": name, "namespace": namespace, "table": table}


# ....................... #


def manifest(retrieval: Mapping[str, Any], *, naming: NamingPolicy) -> dict[str, Any]:
    """The manifest payload for one authored retrieval document.

    ``retrieval`` is the document as plain data, carried on
    :class:`~bloomery.emit.EmitContext` — the emit side consumes no spec models
    (``pyproject.toml``'s "Emitters never import the spec layer"). Two things
    happen to it here and nothing else does: the relation is resolved under the
    naming policy, and the profile's space is inlined under its own name.
    """

    spaces: Mapping[str, Mapping[str, Any]] = retrieval["semantic_spaces"]
    profiles: dict[str, Any] = {}

    for name in sorted(retrieval["profiles"]):
        profile = dict(retrieval["profiles"][name])
        vector = dict(profile["vector"])
        space = vector["space"]
        vector["space"] = {"name": space, **spaces[space]}
        profiles[name] = {
            **profile,
            "relation": _relation(profile["relation"], naming),
            "vector": vector,
        }

    return {"retrieval_manifest_version": MANIFEST_VERSION, "profiles": profiles}


# ....................... #


def manifest_json(payload: Mapping[str, Any]) -> str:
    """Sorted-keys JSON, the serialization every emitted JSON artifact uses.

    ``sort_keys`` is what makes the bytes independent of the order pydantic
    happened to hand the document over in, which is the property the
    cross-process, cross-``PYTHONHASHSEED`` guard measures (S-0020).
    """

    return json.dumps(payload, indent=2, sort_keys=True)


# ....................... #


class RetrievalEmitter:
    """S-0011/D-6: the declared retrieval surface as one JSON artifact.

    Emits **nothing** for a project that authored no retrieval document, the
    rule :class:`~bloomery.emit.metricflow.MetricFlowEmitter` applies to a
    project with no marts: an empty manifest is a file claiming a retrieval
    contract that is not there.

    Carries no ``-- fingerprint:`` header for the reason the semantic manifest
    carries none (S-0059/D-5): a comment line would make the JSON invalid rather
    than annotated, and :class:`~bloomery.emit.EmittedArtifact` still carries the
    content checksum.
    """

    name = "retrieval"

    # ....................... #

    def emit(self, ir: ProjectIR, ctx: EmitContext) -> tuple[EmittedArtifact, ...]:
        """The manifest, or nothing. ``ir`` is read for no part of it — every
        refusal that needs a type or a key has already fired at the guardrail
        stage (:mod:`bloomery.guardrails.retrieval`), and a second reading of
        the same facts here is how two accounts of one rule come to disagree."""

        if ctx.retrieval is None:
            return ()

        content = manifest_json(manifest(ctx.retrieval, naming=ctx.naming))

        return (
            EmittedArtifact.create(
                path=MANIFEST_PATH,
                content=content.rstrip("\n") + "\n",
                kind=ArtifactKind.MODEL,
            ),
        )
