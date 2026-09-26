"""The published surface of a project (S-0002 (§5.1), S-0002/D-1).

An export list is what a project says another project may read. It is the
upstream half of composition and, in this phase, the whole of it: nothing
consumes an export yet, so the document's entire job is to be explicit about a
boundary that today does not exist.

**Explicit, never "everything public by default"** (D1). A project that exports
its whole spec has no boundary at all, and its first refactor breaks every
consumer — so the surface is a list somebody wrote, and a name absent from it
is not exported however public it looks from inside.

**Three kinds, and the shape is what enforces that.** An entity, a mart or a
metric may be exported; a mapping, a step and a quality surface may not, because
those are how a thing is *built* rather than what it is (D2, §5.1). That rule
needs no check: there is no key to put a mapping under. The grouping is also
what disambiguates — the three namespaces are separate, so a bare list would
make ``revenue`` mean a metric or a mart depending on who read it, which is the
same argument :class:`~bloomery.spec.exposures.ExposureDependsOn` makes one
document over.

**Plus a name, optionally** (S-0002/D-10). The one identity a bloomery project
carries, and it lives here — on the producer's side of the boundary — because
exactly one target needs it: dbt's cross-project ``ref()`` names the producing
*project*, where SQLMesh names the relation and Cube and MetricFlow read a
mart. A project nothing imports over dbt never needs one, which is why it is
optional rather than required.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal, Self

from pydantic import ConfigDict, StringConstraints, model_validator

from bloomery.spec.common import IDENTIFIER_PATTERN, SpecModel

# ----------------------- #

__all__ = [
    "ExportSet",
    "Exports",
]


#: What the published schema must say so it refuses what the parser refuses:
#: at least one of the three lists carries a name. The mirror of
#: :data:`~bloomery.spec.imports._READS_SOMETHING`, and here for the same
#: reason — three defaulted arrays make ``minProperties`` useless, so the
#: constraint is an ``anyOf`` (S-0037/D-10: a pre-filter looser than the
#: parser passes documents the loader then rejects).
_PUBLISHES_SOMETHING: Final[dict[str, Any]] = {
    "anyOf": [
        {"properties": {kind: {"minItems": 1}}, "required": [kind]}
        for kind in ("entities", "marts", "metrics")
    ]
}


class Exports(SpecModel):
    """What a project publishes, grouped by kind (S-0002 (§5.1))."""

    model_config = ConfigDict(**SpecModel.model_config, json_schema_extra=_PUBLISHES_SOMETHING)

    #: The producer's dbt project name — the one identity a bloomery project
    #: carries, and only because one target needs it (S-0002/D-10). A
    #: downstream's dbt target spells the two-argument ``ref()`` and the
    #: ``dependencies.yml`` entry with it, while the local alias stays what
    #: keys the compile input and the resolution (D2). Optional: every other
    #: target names a relation or reads a mart and needs no name at all.
    #:
    #: Patterned, because it reaches two places nothing quotes: ``name:`` in
    #: the emitted ``dbt_project.yml`` and the first argument of a Jinja
    #: ``ref()`` call — the same argument :data:`~bloomery.spec.common.RelationName`
    #: makes one document over.
    name: Annotated[str, StringConstraints(pattern=IDENTIFIER_PATTERN)] | None = None
    entities: tuple[str, ...] = ()
    marts: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()

    # ....................... #

    @model_validator(mode="after")
    def _names_are_a_set(self) -> Self:
        """No list repeats a name.

        The same rule an exposure's dependencies carry, for a narrower reason:
        a repeat here produces one surface entry twice, and a downstream
        refusal that prints the export list would print it twice. Refused where
        it is written rather than deduplicated on the way into the IR, because
        collapsing it silently leaves the author's mistake in the document.
        """

        for kind, names in (
            ("entities", self.entities),
            ("marts", self.marts),
            ("metrics", self.metrics),
        ):
            if len(set(names)) != len(names):
                repeated = sorted({name for name in names if names.count(name) > 1})
                msg = (
                    f"exports.{kind} repeats {', '.join(repr(name) for name in repeated)}. "
                    f"Fix: name each {kind[:-1]} once"
                )
                raise ValueError(msg)

        return self


# ....................... #


class ExportSet(SpecModel):
    """The per-project exports document (``exports_version``), at most one per
    project (S-0002 (§5.1))."""

    #: Pinned to the one version bloomery implements, like every other document
    #: kind's (S-0035/D-7): an unbounded ``int`` accepts a document written for
    #: a future bloomery and silently applies v1 semantics to it. Required,
    #: because this key is also the document-kind discriminator.
    exports_version: Literal[1]
    exports: Exports

    # ....................... #

    @model_validator(mode="after")
    def _exports_something(self) -> Self:
        """A document that exports nothing is refused.

        Not a pedantic emptiness check. "This project publishes nothing" is
        already how a project with no exports document reads, so an empty one
        adds a file and changes no behaviour — and it reads, to anyone opening
        it, as a boundary that has been thought about. A reader who sees the
        document assumes a surface exists; the refusal keeps those two in step.
        """

        published = self.exports

        if not (published.entities or published.marts or published.metrics):
            msg = (
                "an exports document must export at least one entity, mart or metric — "
                "one that exports nothing says what a project with no exports document "
                "already says, while reading as a boundary somebody drew (S-0002/D-1). "
                "Fix: name what this project publishes, or delete the document"
            )
            raise ValueError(msg)

        return self
