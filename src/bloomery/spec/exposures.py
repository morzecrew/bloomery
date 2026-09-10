"""The authored side of a downstream consumer (RFC 0056 §5.1).

An exposure is a leaf the spec declares: something outside the project that
reads what the project builds — a dashboard, a notebook, a reverse-ETL sync. It
names itself, its kind, its owner and the metrics and marts it depends on, and
that is the whole document. Nothing here is discovered and nothing here is
fetched (D1, D6): an exposure is a *claim* about the world, made by the author,
and a compiler that read a BI tool to check it would need a network and
credentials that RFC 0003 forbids it.

``kind`` is dbt's vocabulary rather than one invented here (D3). It is the only
one of these words with a consumer, so a bloomery-specific set would have to be
mapped onto it anyway — and the five values below are dbt's exact enum,
measured by handing it each one, which is how ``report`` (not a member) and
``analysis`` (one) ended up the right way round.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from bloomery.spec.common import IDENTIFIER_PATTERN, SpecModel

# ----------------------- #

__all__ = [
    "Exposure",
    "ExposureDependsOn",
    "ExposureKind",
    "ExposureName",
    "ExposureSet",
]

#: dbt's exposure types, verbatim (D3). A ``Literal`` rather than a tuple
#: beside one: ``typing.get_args`` reads the members back for anything that
#: needs to enumerate them, and a second declaration is a second thing to keep
#: in step with dbt.
ExposureKind = Literal["dashboard", "notebook", "analysis", "ml", "application"]

#: An exposure's name mints the lineage node id ``exposure.<name>`` and becomes
#: a dbt exposure's ``name:``, so it is held to the bare-identifier shape both
#: of those want — the same pattern :data:`~bloomery.spec.common.RelationName`
#: uses, minus the reserved-name check, which guards names that become
#: *relations*. An exposure never becomes one: nothing is built for it.
ExposureName = Annotated[str, StringConstraints(pattern=IDENTIFIER_PATTERN)]


class ExposureDependsOn(SpecModel):
    """What an exposure reads, grouped by kind.

    Grouped here and **flat** in the emitted dbt document, which is not an
    inconsistency: a spec reader needs to know which name is a metric and which
    is a mart — the two namespaces are separate and a bare list would make
    ``revenue`` ambiguous — while dbt's schema takes one list of ``ref()`` and
    ``metric()`` calls that carry the kind in the call itself (§5.1).
    """

    metrics: tuple[str, ...] = ()
    marts: tuple[str, ...] = ()

    # ....................... #

    @model_validator(mode="after")
    def _names_are_a_set(self) -> Self:
        """Neither list repeats a name.

        A repeat is not merely redundant: every edge and every impact row this
        document produces is derived per name, so a name listed twice is a
        graph edge built twice and an exposure reported twice against one
        change. Refused where it is written rather than deduplicated
        downstream, because silently collapsing it leaves the author's mistake
        in the document.
        """

        for kind, names in (("metrics", self.metrics), ("marts", self.marts)):
            if len(set(names)) != len(names):
                duplicated = sorted({name for name in names if names.count(name) > 1})
                msg = (
                    f"depends_on.{kind} repeats {', '.join(repr(n) for n in duplicated)}. "
                    f"Fix: name each {kind[:-1]} once"
                )
                raise ValueError(msg)

        return self


# ....................... #


class Exposure(SpecModel):
    """One declared consumer (RFC 0056 §5.1)."""

    kind: ExposureKind
    #: Who to tell when a change reaches this. A scalar here and an object in
    #: the emitted dbt document, which spells it ``owner: {email: …}``.
    owner: str = Field(min_length=1)
    #: Text, and only text (D6). Never fetched, never validated beyond being a
    #: string: a compiler that checked a URL would be making a network request
    #: to decide whether a spec is valid.
    url: str | None = None
    depends_on: ExposureDependsOn

    # ....................... #

    @model_validator(mode="after")
    def _depends_on_something(self) -> Self:
        """An exposure that names nothing is refused.

        Both of an exposure's jobs are edges — answering "what does this read"
        and putting a name to the consumers a breaking change reaches — so one
        with no dependency at all does neither, while still reporting clean.
        That is the failure mode D2 exists to remove, met one document earlier:
        D2 catches a dependency that resolves to nothing, and this catches the
        absence of one.
        """

        if not self.depends_on.metrics and not self.depends_on.marts:
            msg = (
                "an exposure must depend on at least one metric or mart — one that depends "
                "on nothing answers neither 'what does this read' nor 'who does this change "
                "reach', and reports clean while doing it (RFC 0056 §4). Fix: name what it "
                "reads under 'depends_on', or delete it"
            )
            raise ValueError(msg)

        return self


# ....................... #


class ExposureSet(SpecModel):
    """The per-project exposures document (``exposures_version``), at most one
    per project (RFC 0002 §5.5)."""

    #: Pinned to the one version bloomery implements, like every other document
    #: kind's (RFC 0018 D7): an unbounded ``int`` accepts a document written
    #: for a future bloomery and silently applies v1 semantics to it. Required,
    #: because this key is also the document-kind discriminator.
    exposures_version: Literal[1]
    exposures: dict[ExposureName, Exposure]
