"""The classification guard — what a sensitive column may not do (RFC 0055
D9–D11).

**Classification composes with `grants`, not with `redact`.** RFC 0055 §2
paired it with redaction because, when it was drafted, `quarantine.redact` was
the only PII-adjacent concept bloomery had. Phase 4 then shipped `grants`, the
one annotation in this framework with a mechanism behind it, and the pairing
was left aimed at the weaker half — D4, which turned out to refuse every legal
spelling at once (`logs/T-0050.md`). `redact:` governs what a *reject row*
keeps; this module governs a column that is *published*, and the two never
meet.

Two refusals and one advisory, graded by what the compiler can actually prove:

- `secret` on a column a published relation carries is a contradiction between
  two authored statements, so it is refused whatever else is declared (D10).
- A `pii`/`secret` column reaching a relation that **admits a role its source
  entity does not** is refused (D11) — a set difference rather than a superset
  test, so disjoint grant sets are refused too. Both sides must declare their
  grants: that is the only case where bloomery holds both halves of the
  contradiction.
- An undeclared audience is *unknown*, not wider, and is the advisory carried
  on :class:`~bloomery.SpecEvidence` instead (D11; RFC 0033 §5.1). Refusing it
  would refuse every project that manages its gold grants outside bloomery.

The published relations are marts and rollups. Silver entities are not: an
entity is where a classified column is *declared*, and refusing it there would
refuse the annotation for existing at all.

**Columns, not measures.** A mart carries the columns its measures are computed
from, so on a mart the distinction does not arise. A rollup drops them —
``keep`` names what survives the grouping — and keeps aggregates over them, and
those aggregates are deliberately **not** checked: `SUM(salary)` is not the
salary column, and refusing a mart that sums a sensitive measure for finance
would refuse the ordinary case. The exception worth knowing is that a
non-additive aggregate can disclose a value — `MAX(ssn)` over a group of one is
that row's `ssn` — and bloomery does not currently distinguish those (PR #113
review).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bloomery.errors import AudienceWidened, SecretPublished

if TYPE_CHECKING:
    from bloomery.errors import GuardrailError
    from bloomery.ir import EntityIR, GrantsIR, MartIR, ProjectIR

# ----------------------- #

__all__ = [
    "PublishedRelation",
    "check_classification",
    "published_columns",
    "sensitive_columns",
]

#: ``(column name, source entity, source column)`` — a published column and
#: where it came from.
type Column = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class PublishedRelation:
    """A relation this project publishes, and what it carries.

    ``kind`` is the authored document key — ``marts`` or ``rollups`` — because
    it is what a source path needs; the singular reaches messages as
    ``kind[:-1]``.
    """

    name: str
    kind: str
    grants: GrantsIR | None
    columns: tuple[Column, ...]


#: The classifications this guard acts on. `public` and `internal` route to
#: metadata and nothing else — `internal` says who *should* read a column,
#: which is a statement about people rather than one a compiler can enforce.
_SENSITIVE = frozenset({"pii", "secret"})


def sensitive_columns(ir: ProjectIR) -> dict[tuple[str, str], str]:
    """Every classified entity column, keyed by ``(entity, column)``.

    Public because the advisory producer reads the same map: one definition of
    "which columns are sensitive" rather than two that can disagree about a
    vocabulary member added later.
    """

    return {
        (entity.name, column.name): column.classification
        for entity in ir.entities
        for column in entity.columns
        if column.classification in _SENSITIVE
    }


# ....................... #


def _wider(published: GrantsIR | None, source: GrantsIR | None) -> tuple[str, ...]:
    """The roles the published relation admits that its source does not, or
    ``()`` when the comparison cannot be made.

    ``None`` on either side is the undeclared case and returns nothing: an
    absent ``grants:`` block means bloomery has no opinion and the warehouse's
    own grants stand (RFC 0055 D6), which is *unknown* rather than wider. The
    advisory covers it; a refusal here would be a refusal on a fact this
    compiler does not have.
    """

    if published is None or source is None:
        return ()

    return tuple(sorted(set(published.select) - set(source.select)))


# ....................... #


def published_columns(ir: ProjectIR) -> tuple[PublishedRelation, ...]:
    """Every relation this project *publishes*, with the provenance of each
    column it carries.

    One walk, two consumers: this guard and the `undeclared_audience` advisory
    read the same list, so they cannot come to different conclusions about
    which relations are published or which entity a column came from.

    A mart's own ``columns`` carry provenance already, and they cover measures
    as well as dimensions — the flattener resolves both. A rollup has no
    ``columns`` at all: ``keep`` names its parent's, so the provenance is the
    parent's filtered to what survives the grouping, and a dropped column is
    genuinely gone from the rollup's relation.
    """

    marts = {mart.name: mart for mart in ir.marts}

    def columns(mart: MartIR, kept: frozenset[str] | None) -> tuple[Column, ...]:
        return tuple(
            (column.name, column.source_entity, column.source_column)
            for column in mart.columns
            if kept is None or column.name in kept
        )

    published = [
        PublishedRelation(
            name=mart.name, kind="marts", grants=mart.grants, columns=columns(mart, None)
        )
        for mart in ir.marts
    ]
    published += [
        PublishedRelation(
            name=rollup.name,
            kind="rollups",
            grants=rollup.grants,
            columns=columns(parent, frozenset(rollup.keep)),
        )
        for rollup in ir.rollups
        # A rollup naming a parent this project does not build cannot be
        # reached: the rollup guardrail refused it long before this runs. Read
        # defensively anyway rather than raising from a guardrail, whose job is
        # to report rather than to crash.
        if (parent := marts.get(rollup.of)) is not None
    ]

    return tuple(published)


# ....................... #


def check_classification(ir: ProjectIR) -> list[GuardrailError]:
    """Every classification violation in the project, in deterministic order.

    Marts before rollups, each sorted by name on ``ProjectIR``, and columns in
    ``MartIR`` order (sorted by name) — so the batched aggregate reads the same
    way on every run and across processes (RFC 0003).
    """

    sensitive = sensitive_columns(ir)

    if not sensitive:
        # Nothing classified: no walk, and no cost on the overwhelming majority
        # of projects. Stated as an early return rather than left to the loops
        # because the mart-by-column walk below is the expensive part.
        return []

    entities: dict[str, EntityIR] = {entity.name: entity for entity in ir.entities}
    violations: list[GuardrailError] = []

    for relation in published_columns(ir):
        name, key, grants = relation.name, relation.kind, relation.grants
        where = f"marts: {key}.{name}"

        for column, source_entity, source_column in relation.columns:
            classification = sensitive.get((source_entity, source_column))

            if classification is None:
                continue

            if classification == "secret":
                msg = (
                    f"{key[:-1]} {name!r} carries column {column!r}, which is "
                    f"{source_entity}.{source_column} classified secret (RFC 0055 D10). A "
                    f"{key[:-1]} is the published surface, which is the one thing 'secret' "
                    "says this column is not part of. Fix: drop the column from the "
                    "flatten, or reclassify it if it is not secret"
                )
                violations.append(SecretPublished(msg, source_path=where))
                continue

            source_grants = entities[source_entity].grants if source_entity in entities else None
            widened = _wider(grants, source_grants)

            if widened:
                msg = (
                    f"{key[:-1]} {name!r} carries column {column!r}, which is "
                    f"{source_entity}.{source_column} classified {classification}, and grants "
                    f"select to {', '.join(widened)} — role(s) entity {source_entity!r} does "
                    f"not grant (RFC 0055 D11). The {key[:-1]} would publish a sensitive "
                    "column to an audience its source restricts. Fix: narrow the "
                    f"{key[:-1]}'s grants:, widen the entity's, or drop the column"
                )
                violations.append(AudienceWidened(msg, source_path=where))

    return violations
