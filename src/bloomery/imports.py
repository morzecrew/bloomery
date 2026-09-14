"""Reading an external semantic artifact into bloomery relationships (RFC 0070).

``IMPORTED_VERIFIED`` was a provenance nothing produced: RFC 0039 minted it,
RFC 0065 graded it, and every fact the compile path reached graded ``LOCKED``
anyway — so the refusal a strict consumer asks for could not be tripped by any
project a person could write. This is its producer.

**Pure, and the reads stay in the CLI.** A manifest arrives here as text and a
``relationships:`` block leaves as text; nothing here opens a file. That is not
tidiness — it is what lets the importer be a *command* without weakening
RFC 0003: what it produces is specs, the author commits them, and compilation
stays a function of what is on disk rather than of an artifact nobody reviewed.

**Nothing is inferred.** Each row of RFC 0070 §5.2 maps one artifact field to
one bloomery fact, and where the artifact is silent the import refuses instead
of emitting a weaker edge — there is no weaker edge in the basis vocabulary to
emit (RFC 0044 D3). A ``foreign`` element nothing declares unique, an absent
``expr``, two models claiming one target: all of them are the artifact failing
to state a cardinality, and guessing one is exactly the failure this document
was split out of RFC 0044 to prevent.

**Two things in MetricFlow are called entities and they are not the same
thing.** A *semantic model* is the relation and corresponds to a bloomery
entity; an *entity element* — a row under ``entities:`` — is a join identity
several models share and corresponds to nothing here. A ``foreign`` element
``E`` in model ``M`` paired with a ``primary`` or ``unique`` ``E`` in model
``N`` is a ``many_to_one`` from ``M`` to ``N``. Reading the element names as
endpoints is the mistake that makes an importer look like it works.
"""

from __future__ import annotations

import re
import textwrap
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import yaml
from metricflow_semantic_interfaces.implementations.semantic_manifest import (
    PydanticSemanticManifest,
)
from metricflow_semantic_interfaces.type_enums.entity_type import EntityType

from bloomery.errors import ArtifactImportError, BloomeryError
from bloomery.spec.common import IDENTIFIER_PATTERN
from bloomery.spec.entity import Relationship

if TYPE_CHECKING:
    from collections.abc import Mapping

    from metricflow_semantic_interfaces.implementations.semantic_model import (
        PydanticSemanticModel,
    )

    from bloomery.spec import Project

# ----------------------- #

__all__ = [
    "metricflow_relationships",
    "render",
]

#: The element types that assert *at most one row per value*, which is the
#: whole of what ``many_to_one`` needs on the to-side. ``natural`` is
#: deliberately absent: MetricFlow's own docs call it a key that is *not*
#: unique, so no cardinality follows from it and a relationship pointing at one
#: would be the guessed edge RFC 0044 D3 forbids. It contributes nothing rather
#: than refusing, because an artifact carrying one alongside a valid pair is a
#: well-formed artifact.
_UNIQUE_SIDE: Final[frozenset[EntityType]] = frozenset({EntityType.PRIMARY, EntityType.UNIQUE})

#: An ``expr`` bloomery can put in a ``via:`` map. MetricFlow allows an
#: arbitrary SQL expression there — ``lower(customer_id)``, ``a || b`` — and a
#: relationship's ``via`` is a column *name* on both sides, read by the
#: reference checker against an entity's declared fields. Pinned to the
#: grammar ``RelationName`` and ``DimensionName`` already use, so "a bare
#: column name" is one answer in this codebase rather than a second opinion.
#:
#: Read with :meth:`~re.Pattern.fullmatch` and not :meth:`~re.Pattern.match`,
#: even though the pattern is anchored at both ends: ``$`` also matches *before*
#: a final newline, so ``"order_id\n"`` passed an anchored ``match`` and became
#: a ``via`` column no entity declares. The anchors stay because the constant is
#: shared and is read by pydantic elsewhere.
_BARE_COLUMN: Final[re.Pattern[str]] = re.compile(IDENTIFIER_PATTERN)

#: What the generated ``imported_from:`` says. The scheme rather than the bare
#: path, so a project importing from two kinds of artifact reads back which was
#: which, and so the refusal a strict consumer sees names something a reader
#: can go and open.
_ORIGIN = "metricflow:{artifact}"


# ....................... #


def _refuse(errors: list[BloomeryError], message: str, *, source_path: str) -> None:
    errors.append(ArtifactImportError(message, source_path=source_path))


# ....................... #


def _parse(manifest: str, *, artifact: str) -> PydanticSemanticManifest:
    """The artifact, as the library that owns its schema reads it.

    The library's own models rather than a hand-rolled walk of the JSON, for
    the reason the emitter uses them: the schema is MetricFlow's, and a second
    reading of it here would be a second opinion about what a manifest is. It
    is checked, once, for the property that matters — it preserves an absent
    ``expr`` as ``None`` rather than defaulting it to the element's name, which
    is the one way a parser could invent the column this module refuses to
    guess (``test_a_missing_expr_survives_the_parse_as_none``).

    ``ValueError`` covers both failures: ``json`` raises ``JSONDecodeError``
    and the pydantic-v1 shim raises ``ValidationError``, and both derive from
    it. Caught rather than left to escape because an unreadable artifact is a
    refusal — the caller handed us a file — and not a bug in bloomery.
    """

    try:
        # Annotated rather than returned bare: these are pydantic-v1 shim
        # models, so `parse_raw` is untyped and mypy reads the result as `Any`
        # — the same reason the emitter spells out `manifest.json()`'s type.
        parsed: PydanticSemanticManifest = PydanticSemanticManifest.parse_raw(manifest)
    except ValueError as exc:
        msg = (
            f"{artifact} is not a readable MetricFlow semantic manifest: {exc}. "
            "Fix: point this at the semantic_manifest.json a MetricFlow project "
            "produces"
        )
        raise ArtifactImportError(msg, source_path=artifact) from exc

    return parsed


# ....................... #


def _targets(manifest: PydanticSemanticManifest) -> dict[str, list[tuple[str, str | None]]]:
    """Per entity element, every model declaring it ``primary`` or ``unique``.

    A list rather than one model, because "two models claim one target" is a
    refusal condition and a dict keyed by element name would have silently kept
    the last of them — which is the shape of every ambiguity this corpus has
    had to refuse afterwards.
    """

    found: dict[str, list[tuple[str, str | None]]] = {}

    for model in manifest.semantic_models:
        for element in model.entities:
            if element.type in _UNIQUE_SIDE:
                found.setdefault(element.name, []).append((model.name, element.expr))

    return found


# ....................... #


def _entity(
    model: str,
    mapping: Mapping[str, str],
    project: Project,
    errors: list[BloomeryError],
    *,
    source_path: str,
) -> str | None:
    """The bloomery entity a semantic model names, or ``None`` having refused.

    The map is the whole of the translation and there is deliberately no
    fallback beyond identity: a MetricFlow project names its models after its
    source relations and a bloomery project names its entities for itself, so
    the two agreeing is luck. Inferring the pairing — comparing a primary
    element's ``expr`` to an entity's ``key``, or singularising a model name —
    is the guessed default RFC 0044 D3 forbids, with the added property that it
    would be wrong silently rather than loudly.
    """

    name = mapping.get(model, model)

    if name not in project.entity_model.entities:
        _refuse(
            errors,
            f"semantic model {model!r} names no entity this project declares"
            + (f" (mapped to {name!r})" if name != model else "")
            + f". Fix: declare entity {name!r}, or pass --entity {model}=<entity>",
            source_path=source_path,
        )
        return None

    return name


# ....................... #


def _column(
    element: str,
    expr: str | None,
    model: str,
    errors: list[BloomeryError],
    *,
    source_path: str,
) -> str | None:
    """One side's join column, or ``None`` having refused.

    Both refusals are the artifact declining to name a column: an absent
    ``expr`` names none, and an expression names a computation instead. A
    relationship's ``via`` is checked against an entity's declared fields, so
    either would produce a relationship that refuses at resolution with a
    message about the *spec* rather than about the artifact it came out of.

    Takes the two values rather than the element, because the to-side's expr
    comes from a *different* model's element and passing a stand-in object to
    say so would be a second shape for one question.
    """

    if expr is None:
        _refuse(
            errors,
            f"entity element {element!r} of semantic model {model!r} declares no expr, "
            "so the artifact names no column to join on. Fix: give it an expr in the "
            "source project, or author this relationship here",
            source_path=source_path,
        )
        return None

    if _BARE_COLUMN.fullmatch(expr) is None:
        _refuse(
            errors,
            f"entity element {element!r} of semantic model {model!r} has expr "
            f"{expr!r}, which is an expression rather than a bare column name. "
            "A relationship joins columns, and bloomery has nowhere to put the "
            "computation. Fix: author this relationship here",
            source_path=source_path,
        )
        return None

    return expr


# ....................... #


def _declares(
    entity: str,
    column: str,
    model: str,
    project: Project,
    errors: list[BloomeryError],
    *,
    source_path: str,
) -> bool:
    """Whether the mapped entity declares the column the artifact joins on.

    The reference checker already refuses a ``via`` naming a column an entity
    does not have, so without this the importer prints a block that parses,
    pastes cleanly and then refuses at resolution — with a message about the
    author's spec rather than about the artifact it came out of, which is the
    wrong file to send them to.

    The same test `resolve` makes, deliberately: one answer to "does this entity
    have this column", asked earlier. An artifact spelling a column
    ``customer_id`` against an entity declaring ``customer_key`` is the ordinary
    way this happens, and it is the mapping being wrong rather than the column
    being missing.
    """

    if column in project.entity_model.entities[entity].fields:
        return True

    _refuse(
        errors,
        f"semantic model {model!r} joins on column {column!r}, which entity "
        f"{entity!r} does not declare. Fix: correct the mapping for {model!r}, or "
        f"declare {column!r} on {entity!r}",
        source_path=source_path,
    )
    return False


# ....................... #


def _generated_names(edges: list[tuple[str, str, dict[str, str]]]) -> list[str]:
    """One name per edge: ``<from>__<to>``, widened where that is not unique.

    A name is a key — a mart's ``via:``, an entity's referential rule and the
    plan diff all refer to a relationship by it, and ``resolve`` refuses two of
    one name (RFC 0070 row 10). So the scheme has to survive a project with two
    edges between the same pair of entities, which a manifest produces whenever
    one model carries two ``foreign`` elements resolving to one target.

    Widened with the join columns rather than with an index, because an index
    depends on the order the artifact happens to list its models: adding an
    unrelated semantic model would renumber an existing relationship, and a
    re-import would then diff against the last one for no reason.
    """

    collisions = {
        f"{one}__{other}"
        for index, (one, other, _) in enumerate(edges)
        if any(pair[:2] == (one, other) for pair in edges[index + 1 :])
    }

    return [
        f"{one}__{other}"
        + (
            "__" + "_".join(f"{key}_{value}" for key, value in sorted(via.items()))
            if f"{one}__{other}" in collisions
            else ""
        )
        for one, other, via in edges
    ]


# ....................... #


def metricflow_relationships(
    manifest: str,
    project: Project,
    *,
    artifact: str,
    entities: Mapping[str, str] = MappingProxyType({}),
) -> tuple[Relationship, ...]:
    """The relationships a MetricFlow semantic manifest states exactly.

    ``project`` is what the model names are checked against and what a conflict
    is judged against; ``artifact`` is the path that reaches ``imported_from:``
    and every refusal, so a reader can open the file the fact came from.
    ``entities`` maps a semantic model's name to a bloomery entity's.

    Every refusal is collected rather than raised at the first one: an import
    is a bulk operation and fixing a manifest one message per run is the
    experience batching exists to prevent (RFC 0002 §5.3). The aggregate is a
    single :class:`~bloomery.errors.ArtifactImportError` whose ``collected``
    holds each one.

    A relationship the project already declares identically is **not** returned
    — two statements that agree are not a contradiction, and returning it would
    ask the author to paste a duplicate that ``resolve`` then refuses by name
    (RFC 0070 D4). A disagreement about cardinality on the same ``(from, to,
    via)`` refuses, naming both.
    """

    errors: list[BloomeryError] = []
    parsed = _parse(manifest, artifact=artifact)
    targets = _targets(parsed)

    # Both halves of every mapping, before any edge is built. Checking the
    # target lazily — where `_edges_of` happens to reach it — means a model
    # carrying no `foreign` element never has its mapping checked at all, so
    # `--entity customers=nonesuch` was accepted in full whenever `customers`
    # was only ever a target.
    for model_name, entity_name in sorted(entities.items()):
        if all(model.name != model_name for model in parsed.semantic_models):
            _refuse(
                errors,
                f"--entity {model_name}={entity_name} names no semantic model in this "
                "artifact. Fix: check the spelling against the manifest's "
                "semantic_models",
                source_path=artifact,
            )
        if entity_name not in project.entity_model.entities:
            _refuse(
                errors,
                f"--entity {model_name}={entity_name} names no entity this project "
                f"declares. Fix: declare entity {entity_name!r}, or correct the mapping",
                source_path=artifact,
            )

    edges: list[tuple[str, str, dict[str, str]]] = []

    for model in sorted(parsed.semantic_models, key=lambda one: one.name):
        edges.extend(_edges_of(model, targets, entities, project, artifact, errors))

    if errors:
        raise _aggregate(errors)

    # Two semantic models can map to one entity, and when they state the same
    # join they state one relationship twice. Collapsed here rather than
    # refused, on §5.4's rule that agreement is not a contradiction — and
    # before naming, because `_generated_names` would widen both to the same
    # string and `render` would print a duplicate name that `resolve` refuses.
    edges = [
        (one, other, dict(via))
        for one, other, via in dict.fromkeys(
            (one, other, tuple(sorted(via.items()))) for one, other, via in edges
        )
    ]

    names = _generated_names(edges)
    declared = {
        (one.from_, one.to, tuple(sorted(one.via.items()))): one
        for one in project.entity_model.relationships
    }
    taken = {one.name for one in project.entity_model.relationships}
    imported: list[Relationship] = []

    for name, (from_name, to_name, via) in zip(names, edges, strict=True):
        existing = declared.get((from_name, to_name, tuple(sorted(via.items()))))

        if existing is not None:
            if existing.cardinality != "many_to_one":
                _refuse(
                    errors,
                    f"relationship {existing.name!r} is declared here as "
                    f"{existing.cardinality!r} and stated by {artifact} as 'many_to_one'. "
                    "Neither wins by default: a contradiction is a finding about the "
                    "model. Fix: settle which cardinality is true and correct the other "
                    "side",
                    source_path=f"entity_model: relationships[{existing.name}]",
                )
            continue

        if name in taken:
            _refuse(
                errors,
                f"the generated name {name!r} for {from_name} -> {to_name} is already a "
                "relationship in this project, describing a different join. Fix: rename "
                "the declared relationship, or author this edge by hand",
                source_path=artifact,
            )
            continue

        imported.append(
            Relationship.model_validate(
                {
                    "name": name,
                    "from": from_name,
                    "to": to_name,
                    "via": via,
                    "cardinality": "many_to_one",
                    "imported_from": _ORIGIN.format(artifact=artifact),
                }
            )
        )

    if errors:
        raise _aggregate(errors)

    return tuple(imported)


# ....................... #


def _edges_of(
    model: PydanticSemanticModel,
    targets: Mapping[str, list[tuple[str, str | None]]],
    entities: Mapping[str, str],
    project: Project,
    artifact: str,
    errors: list[BloomeryError],
) -> list[tuple[str, str, dict[str, str]]]:
    """One model's ``foreign`` elements, resolved into edges.

    Sorted by element name so the output does not depend on the order the
    artifact lists them, which nothing in MetricFlow constrains.
    """

    found: list[tuple[str, str, dict[str, str]]] = []
    path = f"{artifact}: semantic_models[{model.name}]"

    for element in sorted(model.entities, key=lambda one: one.name):
        if element.type is not EntityType.FOREIGN:
            continue

        # The model's own declaration is excluded before the count, not after:
        # a model may carry `E` as both primary and foreign (measured — the
        # library accepts it), and the edge that would produce joins a relation
        # to itself on one column, which is every row matching itself. Counting
        # it would also turn "nothing declares E unique" into a self-join
        # instead of a refusal.
        declarers = [
            (name, expr) for name, expr in targets.get(element.name, []) if name != model.name
        ]

        if not declarers:
            _refuse(
                errors,
                f"entity element {element.name!r} is foreign in semantic model "
                f"{model.name!r} and no other model declares it primary or unique, so "
                "the artifact states no target for it. A relationship whose to-side is "
                "not unique determines nothing. Fix: declare it in the source project, "
                "or author this relationship here",
                source_path=path,
            )
            continue

        if len(declarers) > 1:
            named = ", ".join(repr(name) for name, _ in sorted(declarers))
            _refuse(
                errors,
                f"entity element {element.name!r} is declared primary or unique by "
                f"{len(declarers)} semantic models ({named}), so the target of "
                f"{model.name!r}'s foreign {element.name!r} is ambiguous. Fix: author "
                "this relationship here, naming the one you mean",
                source_path=path,
            )
            continue

        (target_model, target_expr) = declarers[0]
        target_path = f"{artifact}: semantic_models[{target_model}]"
        from_column = _column(element.name, element.expr, model.name, errors, source_path=path)
        to_column = _column(
            element.name, target_expr, target_model, errors, source_path=target_path
        )
        from_entity = _entity(model.name, entities, project, errors, source_path=path)
        to_entity = _entity(target_model, entities, project, errors, source_path=target_path)

        if None in (from_column, to_column, from_entity, to_entity):
            continue

        assert from_column is not None and to_column is not None  # noqa: S101 — narrowing
        assert from_entity is not None and to_entity is not None  # noqa: S101 — narrowing

        declares = [
            _declares(entity, column, model_name, project, errors, source_path=where)
            for entity, column, model_name, where in (
                (from_entity, from_column, model.name, path),
                (to_entity, to_column, target_model, target_path),
            )
        ]

        if not all(declares):
            continue

        found.append((from_entity, to_entity, {from_column: to_column}))

    return found


# ....................... #


def _aggregate(errors: list[BloomeryError]) -> BloomeryError:
    if len(errors) == 1:
        return errors[0]
    return ArtifactImportError.from_collected(tuple(errors))


# ....................... #


def render(relationships: tuple[Relationship, ...]) -> str:
    """The ``relationships:`` block, as an author would paste it.

    Not a whole document: a project holds exactly one ``EntityModel`` and this
    is a fragment of the one it already has. Printing a second document would
    print something ``load_project`` refuses two ways — as an unknown kind
    without a version key, and as a second entity model with one.

    ``sort_keys=False`` for the reason the dbt emitter gives: the insertion
    order here is the order a reader expects to find the keys in, and sorting
    would file ``cardinality`` above ``from``.

    The sequence is indented by hand afterwards because PyYAML does not indent
    a sequence under its mapping key at any ``indent=`` setting, and this text
    is pasted into a file whose own ``relationships:`` block is indented. Both
    spellings parse; only one of them stops the author reformatting what they
    just pasted.
    """

    if not relationships:
        return ""

    block = [
        {
            "name": one.name,
            "from": one.from_,
            "to": one.to,
            "via": dict(sorted(one.via.items())),
            "cardinality": one.cardinality,
            "imported_from": one.imported_from,
        }
        for one in relationships
    ]

    body = yaml.safe_dump(
        block, sort_keys=False, default_flow_style=False, width=100, allow_unicode=True
    )

    return "relationships:\n" + textwrap.indent(body, "  ")
