"""The retrieval guards (S-0011/the-guardrails): the six refusals that make a
declared retrieval surface mean something.

| Refusal | Because |
|---|---|
| field dimensions differ from space dimensions | the arithmetic cannot run |
| field scalar differs from space scalar | a float32 corpus scored against a float16 query is a silently different space |
| the vector field is not a vector type | "any array will do" is how a mixed-model corpus happens |
| the field's declared producer differs from the space's | dimensions agreeing is not spaces agreeing |
| the profile grain differs from the corpus relation's key | one vector per retrievable item, or the corpus is not a corpus |
| a filterable or returned field is absent from the corpus relation | the query cannot be served, and finding out at run time is the failure this project exists to move earlier |

The grain refusal is the grain violation's argument in another domain
(S-0011/D-8): a mart at document grain carrying chunk embeddings has either
duplicated a vector or collapsed several, and both make top-k meaningless.
Strict key equality against the corpus relation, the same rule already applied
to measures.

No encoder identity is resolved against anything (S-0011/D-2): the producer
refusal is a string comparison, and a compile that asked a provider whether a
model exists would read the network.

**Against the draft IR, not the authored documents**, unlike the exposure guard:
every refusal here needs a *type* or a *key*, and neither exists until the
entity model is resolved and the marts are flattened. A mart that failed its own
check is absent from the draft, and its profile then reports the relation as
unresolvable — one leaf in the same batch, beside the mart's own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bloomery.errors import GuardrailError
from bloomery.typing import VectorType, render_type

if TYPE_CHECKING:
    from bloomery.ir import ProjectIR
    from bloomery.spec.project import Project
    from bloomery.spec.retrieval import Encoder, RetrievalProfile, SemanticSpace
    from bloomery.typing import LogicalType

# ----------------------- #

__all__ = [
    "RetrievalViolation",
    "check_retrieval",
]


class RetrievalViolation(GuardrailError):
    """A declared retrieval profile that cannot be served (S-0011/the-guardrails).

    A :class:`~bloomery.errors.GuardrailError` subclass so the stage batches it
    with every other refusal. It lives here rather than in
    :mod:`bloomery.errors` because retrieval ships as its own kind and nothing
    outside this module raises it; promoting it into the taxonomy is a change to
    that module, which this phase does not touch.
    """


def _encoder(encoder: Encoder) -> str:
    """One encoder identity, spelled for a refusal. Opaque (S-0011/D-2)."""

    return f"{encoder.family}/{encoder.model} ({encoder.input_kind})"


def _absent(field: str, label: str, columns: dict[str, LogicalType]) -> str:
    """The message for a referenced field the corpus relation does not have.

    Ends on what the relation *does* carry, for the reason the exposure guard's
    does: the mistake is a column renamed in one document and not the other, and
    a nearest-match would name one candidate and hide the rename. Capped at
    eight, because a refusal that prints eighty column names is one nobody reads
    to the end.
    """

    shown = sorted(columns)
    listed = ", ".join(repr(name) for name in shown[:8]) or "(none)"
    suffix = f", … ({len(shown)} in total)" if len(shown) > 8 else ""
    return (
        f"names {field!r}, which {label} does not carry. A query naming a column the "
        f"corpus has not got cannot be served, and finding that out at run time is the "
        f"failure this refusal moves earlier (S-0011/the-guardrails). Fix: correct the "
        f"name, or add the column to the relation. Its columns: {listed}{suffix}"
    )


# ....................... #


def _check_profile(
    name: str,
    profile: RetrievalProfile,
    space: SemanticSpace,
    label: str,
    columns: dict[str, LogicalType],
    key: tuple[str, ...],
) -> list[GuardrailError]:
    source_path = f"retrieval: profiles.{name}"
    errors: list[GuardrailError] = []

    def refuse(message: str) -> None:
        errors.append(RetrievalViolation(f"profile {name!r} {message}", source_path=source_path))

    declared = columns.get(profile.vector.field)

    if declared is None:
        refuse(_absent(profile.vector.field, label, columns))
    elif not isinstance(declared, VectorType):
        refuse(
            f"retrieves on field {profile.vector.field!r}, declared "
            f"{render_type(declared)!r} rather than a vector. A field that is not a "
            f"declared vector carries no dimensions and no scalar, so nothing about the "
            f"space {profile.vector.space!r} can be checked against it — 'any array will "
            f"do' is how a corpus comes to hold two models' embeddings "
            f"(S-0011/the-guardrails). Fix: declare it as "
            f"'vector({space.scalar}, {space.dimensions})'"
        )
    else:
        if declared.dimensions != space.dimensions:
            refuse(
                f"retrieves on field {profile.vector.field!r} of {declared.dimensions} "
                f"dimensions in space {profile.vector.space!r}, which declares "
                f"{space.dimensions}. Fix: make the two agree — a distance over vectors "
                f"of different lengths cannot be computed at all"
            )

        if declared.scalar != space.scalar:
            refuse(
                f"retrieves on field {profile.vector.field!r} of scalar "
                f"{declared.scalar!r} in space {profile.vector.space!r}, which declares "
                f"{space.scalar!r}. Fix: make the two agree — a {declared.scalar} corpus "
                f"scored against a {space.scalar} query is a silently different space, "
                f"and it returns plausible neighbours while doing it"
            )

    producer = profile.vector.producer

    if producer is not None and producer != space.document_encoder:
        refuse(
            f"declares its vector produced by {_encoder(producer)}, while space "
            f"{profile.vector.space!r} declares its documents produced by "
            f"{_encoder(space.document_encoder)}. Dimensions agreeing is not spaces "
            f"agreeing (S-0011/D-2). Fix: name the same producer, or retrieve in the "
            f"space this producer writes"
        )

    if tuple(profile.grain) != key:
        refuse(
            f"declares grain {list(profile.grain)} over {label}, whose key is "
            f"{list(key)}. One vector per retrievable item, or the corpus is not a "
            f"corpus: a coarser grain has either duplicated a vector or collapsed "
            f"several, and both make top-k meaningless (S-0011/D-8). Fix: declare the "
            f"relation's key as the grain, or retrieve from a relation at the grain you "
            f"want"
        )

    lexical = () if profile.lexical is None else profile.lexical.fields

    for kind, fields in (
        ("lexical", lexical),
        ("filterable", profile.filterable),
        ("return", profile.return_),
    ):
        for field in fields:
            if field not in columns:
                refuse(f"{kind} {_absent(field, label, columns)}")

    return errors


# ....................... #


def check_retrieval(project: Project, draft: ProjectIR) -> list[GuardrailError]:
    """Refuse every retrieval profile the project cannot serve (S-0011/the-guardrails).

    A project with no retrieval document returns nothing, which is what keeps
    one that does not retrieve unchanged.

    Every disagreement is reported, not the first: a profile is authored as one
    block and is usually got wrong in more than one way at once — a space
    renamed, its dimensions bumped and a column dropped are one edit and would
    otherwise be three round-trips.
    """

    if project.retrieval is None:
        return []

    entities = {entity.name: entity for entity in draft.entities}
    marts = {mart.name: mart for mart in draft.marts}
    errors: list[GuardrailError] = []

    for name, profile in sorted(project.retrieval.profiles.items()):
        source_path = f"retrieval: profiles.{name}"
        # The grammar has already refused a profile naming an undeclared space,
        # so the lookup cannot miss.
        space = project.retrieval.semantic_spaces[profile.vector.space]
        relation = profile.relation

        if relation.entity is not None:
            entity = entities.get(relation.entity)
            resolved = (
                None
                if entity is None
                else (
                    f"entity {relation.entity!r}",
                    {column.name: column.type for column in entity.columns},
                    entity.key,
                )
            )
            kind, named = "entity", relation.entity
        else:
            # `relation` names exactly one of the two (grammar), so this is the
            # mart branch and `relation.mart` is set; the `or ""` is what says so
            # to a type checker without an assertion that could fire in a build.
            mart_name = relation.mart or ""
            mart = marts.get(mart_name)
            base = None if mart is None else entities.get(mart.base)
            resolved = (
                None
                if mart is None or base is None
                else (
                    f"mart {mart_name!r}",
                    {column.name: column.type for column in mart.columns},
                    # A mart's rows are its base entity's rows (S-0011/D-8): the
                    # flattener joins dimensions in without fanning out, so the
                    # key that identifies a row is the base entity's.
                    base.key,
                )
            )
            kind, named = "mart", mart_name

        if resolved is None:
            errors.append(
                RetrievalViolation(
                    f"profile {name!r} retrieves from {kind} {named!r}, which this project "
                    f"does not build. A profile over a relation that does not exist declares "
                    f"a surface nothing can serve, and every other check on it has nothing "
                    f"to read (S-0011/the-guardrails). Fix: correct the name, or declare the "
                    f"{kind}",
                    source_path=source_path,
                )
            )
            continue

        label, columns, key = resolved
        errors.extend(_check_profile(name, profile, space, label, columns, key))

    return errors
