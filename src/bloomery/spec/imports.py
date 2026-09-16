"""What a project reads from another project's published surface (RFC 0059
§5.1, D1).

The downstream half of composition, and the mirror of
:mod:`~bloomery.spec.exports`: one names what a project publishes, the other
what a project reads, and the two lists are compared when a compile is handed
both sides.

**Keyed by a local alias.** The upstream is addressed by whatever name this
project calls it, because the upstream has no name of its own to be addressed
by — a project carries no identity, and inventing one here would be a much
larger claim than a dependency needs. The alias is also how the compile input
is keyed: ``compile_project(…, upstream={"platform": platform_ir})`` supplies
the IR the aliases name (D2, D8).

**Three kinds, and the shape is what enforces that.** An entity, a mart or a
metric may be imported, because those are what may be exported (§5.1) — a
list that could name a mapping would be a list that can name something no
export list can hold.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from bloomery.spec.common import IDENTIFIER_PATTERN, SpecModel

# ----------------------- #

__all__ = [
    "ImportSet",
    "Imports",
    "UpstreamAlias",
]

#: The local name for an upstream project. Held to the bare-identifier shape
#: because P3 gives an imported node's lineage id a project component built
#: from it, and a lineage id is ``<kind>.<rest>`` with no quoting anywhere.
UpstreamAlias = Annotated[str, StringConstraints(pattern=IDENTIFIER_PATTERN)]


#: What the published schema must say so it refuses what the parser refuses:
#: at least one of the three lists carries a name. Three defaulted arrays make
#: ``minProperties`` useless — ``{"entities": []}`` has one property and reads
#: nothing — so the constraint is an ``anyOf`` over the three, spelled here
#: because pydantic generates the shape and not the rule (RFC 0020 D10: the
#: schema is a pre-filter, and a pre-filter looser than the parser is one that
#: passes documents the loader then rejects).
_READS_SOMETHING: Final[dict[str, Any]] = {
    "anyOf": [
        {"properties": {kind: {"minItems": 1}}, "required": [kind]}
        for kind in ("entities", "marts", "metrics")
    ]
}


class Imports(SpecModel):
    """What this project reads from one upstream, grouped by kind."""

    model_config = ConfigDict(**SpecModel.model_config, json_schema_extra=_READS_SOMETHING)

    entities: tuple[str, ...] = ()
    marts: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()

    # ....................... #

    @model_validator(mode="after")
    def _names_are_a_set(self) -> Self:
        """No list repeats a name.

        The rule :class:`~bloomery.spec.exports.Exports` carries, for the
        mirrored reason: a repeat is one dependency stated twice, and the
        refusal that prints an import list would print it twice.
        """

        for kind, names in (
            ("entities", self.entities),
            ("marts", self.marts),
            ("metrics", self.metrics),
        ):
            if len(set(names)) != len(names):
                repeated = sorted({name for name in names if names.count(name) > 1})
                msg = (
                    f"repeats {', '.join(repr(name) for name in repeated)} under {kind}. "
                    f"Fix: name each {kind[:-1]} once"
                )
                raise ValueError(msg)

        return self


# ....................... #


class ImportSet(SpecModel):
    """The per-project imports document (``imports_version``), at most one per
    project (RFC 0059 §5.1)."""

    #: Pinned to the one version bloomery implements, like every other document
    #: kind's (RFC 0018 D7): an unbounded ``int`` accepts a document written for
    #: a future bloomery and silently applies v1 semantics to it. Required,
    #: because this key is also the document-kind discriminator.
    imports_version: Literal[1]
    #: ``additionalProperties: false`` beside the generated ``patternProperties``
    #: is what makes the alias pattern bite in the published schema: on its own,
    #: ``patternProperties`` constrains only the keys that *match*, and a
    #: non-matching ``Platform Team`` falls through to the default
    #: ``additionalProperties: true``. ``minProperties`` carries the other half
    #: of :meth:`_imports_something` across.
    imports: dict[UpstreamAlias, Imports] = Field(
        json_schema_extra={"additionalProperties": False, "minProperties": 1}
    )

    # ....................... #

    @model_validator(mode="after")
    def _imports_something(self) -> Self:
        """A document that imports nothing, from anyone, is refused.

        Both emptinesses, and they are the same mistake at two depths: a
        document with no upstreams says what a project with no imports document
        already says, and an upstream that names no entity, mart or metric
        declares a dependency on nothing. Either one reads, to somebody opening
        the file, as a boundary that was drawn.
        """

        if not self.imports:
            msg = (
                "an imports document must declare at least one upstream — one that declares "
                "none says what a project with no imports document already says, while "
                "reading as a dependency somebody drew (RFC 0059 D1). Fix: name what this "
                "project reads, or delete the document"
            )
            raise ValueError(msg)

        for alias, read in sorted(self.imports.items()):
            if not (read.entities or read.marts or read.metrics):
                msg = (
                    f"imports {alias!r} and reads nothing from it. An upstream that supplies "
                    f"no entity, mart or metric is a dependency on nothing (RFC 0059 D1). "
                    f"Fix: name what this project reads from {alias!r}, or drop the upstream"
                )
                raise ValueError(msg)

        return self
