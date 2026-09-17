"""The zone guard (RFC 0074 §5.3, R018): a timestamp whose absolute position is
read, and which nothing says was ever on a known clock.

This stage does not decide anything. It **enumerates the sites** where an
instant's position decides an answer and asks
:func:`~bloomery.semantic.zone.prove_zone` about each one; the rule is R018's
and the batching is the guardrail stage's, which is what lets several
undeclared fields reach an author in one round-trip.

**The three sites, and why the list is the rule's real surface.** A timestamp
that is carried, projected, or compared with another column has no boundary to
fall the wrong side of. What has one:

* a **date role** — ``flatten: [{date: placed_at, role: placed}]`` buckets by
  an instant, and a bucket boundary *is* an instant;
* a **comparison against a literal instant** in a measure expression or a
  metric filter — the literal is in some zone and the column is in another;
* an **as-of anchor** — the version chosen is the one current at an instant;

and a **rollup's kept time column**, which is a date role one relation on.

Corpus case 011 fails at the second, and its mart's date role is incidental: a
rule scoped to time dimensions would refuse that fixture for a reason unrelated
to why it is wrong, and would miss the same bug in a project with no
``flatten:`` at all.

**Read from the draft, both sides.** The chain that made a column a wall clock
is in ``SourceFieldIR.transform``, per source, so a merged entity is answered
per mapping rather than per column — the mapping that declared is not sent to
fix anything. The authored documents are read for one thing only: the label a
refusal points at, which is derived from a mapping rather than stored on one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp

from bloomery.errors import UndeclaredZone
from bloomery.semantic import Refutation
from bloomery.semantic.zone import WallClock, prove_zone
from bloomery.spec.mapping import mapping_doc

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bloomery.errors import GuardrailError
    from bloomery.ir.nodes import EntityIR, MartIR, ProjectIR, SqlExpr
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "check_zones",
]

#: The comparison shapes an instant can be pinned against a literal by. Both
#: halves of ``BETWEEN`` reach the same test through :attr:`exp.Between.args`,
#: so it is listed once with the binary predicates rather than special-cased.
_COMPARISONS: tuple[type[exp.Expression], ...] = (
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.Between,
)

#: What a cast has to be *to* for the thing inside it to be an instant.
_INSTANT_TYPES = frozenset(
    {
        exp.DataType.Type.TIMESTAMP,
        exp.DataType.Type.TIMESTAMPTZ,
        exp.DataType.Type.TIMESTAMPNTZ,
    }
)


# ....................... #


def _readings(entity: EntityIR, column: str) -> tuple[WallClock, ...]:
    """How each of this entity's sources produced ``column``.

    One reading per source that lowers the column, and none for a source that
    does not carry it: a merged entity's columns are the *union* over its
    mappings (RFC 0024 §5.2), so a mapping that never heard of this field has
    nothing to declare about it.
    """

    readings: list[WallClock] = []

    for source in entity.sources:
        for field in source.fields:
            if field.target_field != column:
                continue

            names = {step.name for step in field.transform}
            readings.append(
                WallClock(
                    relation=source.relation,
                    parsed="parse_ts" in names,
                    converted="to_utc" in names,
                    declared=field.zone_in,
                )
            )

    return tuple(readings)


# ....................... #


def _is_instant_literal(side: exp.Expression) -> bool:
    """Whether this side of a comparison fixes a point on the clock.

    Two shapes, and both are one authored ``TIMESTAMP '…'``: the canonical form
    is a cast around a string, and a bare string literal compared to a
    timestamp column is the same comparison with the cast left to the engine.
    A side naming a *column* is neither — two columns compared have no literal
    to be in the wrong zone, which is why R018 does not fire there.
    """

    if isinstance(side, exp.Literal) and side.is_string:
        return True

    return any(
        isinstance(cast.to, exp.DataType) and cast.to.this in _INSTANT_TYPES
        for cast in side.find_all(exp.Cast)
    )


# ....................... #


def _pinned_columns(expr: SqlExpr, columns: frozenset[str]) -> frozenset[str]:
    """The entity columns this expression compares against a literal instant.

    ``columns`` is what the entity holds, so a name the expression invents
    reaches nothing. It is deliberately **not** filtered to timestamp columns:
    what makes a value a wall clock is the chain that produced it, and
    ``[{parse_ts: ISO8601}, to_string]`` is a wall clock rendered back to text
    — still five hours out, still compared to a literal. The provenance test
    downstream is the one that decides, and a column no chain ever parsed
    discharges it without an argument.

    The walk is over the whole tree rather than the top node because case 011's
    comparison is nested two levels inside a ``CASE``.
    """

    pinned: set[str] = set()

    for node in expr.ast().find_all(*_COMPARISONS):
        operands = [
            operand
            for key in ("this", "expression", "low", "high")
            if isinstance(operand := node.args.get(key), exp.Expression)
        ]
        named = {
            operand.name
            for operand in operands
            if isinstance(operand, exp.Column) and operand.name in columns
        }

        if named and any(_is_instant_literal(operand) for operand in operands):
            pinned |= named

    return frozenset(pinned)


# ....................... #


def _mart_sites(mart: MartIR, demand: dict[tuple[str, str], set[str]]) -> None:
    """A mart's date roles and as-of anchors, traced back to entity columns.

    Both go through ``MartColumnIR``, which carries the source entity and
    column for every flattened column — the mart's own namespace is prefixed
    and re-derived, so this is the only place the two names are joined.
    """

    for column in mart.columns:
        if column.ref is not None and column.ref.role is not None:
            demand.setdefault((column.source_entity, column.source_column), set()).add(
                f"mart {mart.name!r} buckets it as the {column.ref.role!r} date role"
            )

    by_name = {column.name: column for column in mart.columns}

    for join in mart.joins:
        anchor = by_name.get(join.as_of) if join.as_of is not None else None

        if anchor is not None:
            demand.setdefault((anchor.source_entity, anchor.source_column), set()).add(
                f"mart {mart.name!r} reads {join.entity!r} as of it"
            )


# ....................... #


def check_zones(project: Project, draft: ProjectIR) -> list[GuardrailError]:
    """Refuse every timestamp read for its position that nothing declared a
    clock for (R018).

    One refusal per column rather than per site: the fix is a single key on a
    single field however many marts and metrics read it, and a refusal per
    reader would make an author fix one mapping four times. The sites are
    named in the message anyway, because "somewhere its position matters" is a
    refusal an author cannot act on.
    """

    entities = {entity.name: entity for entity in draft.entities}
    marts = {mart.name: mart for mart in draft.marts}
    demand: dict[tuple[str, str], set[str]] = {}

    for mart in draft.marts:
        _mart_sites(mart, demand)

    for rollup in draft.rollups:
        parent = marts.get(rollup.of)

        # Unreachable from an authored project: `rollups: {of: not_a_mart}` is a
        # parse error naming the marts the document does declare, so a rollup that
        # reaches the draft names a mart that reached it too.
        if parent is None:  # pragma: no cover
            continue

        kept = {column.name: column for column in parent.columns}

        for name in rollup.keep:
            column = kept.get(name)

            if column is not None and (column.ref is not None and column.ref.role is not None):
                demand.setdefault((column.source_entity, column.source_column), set()).add(
                    f"rollup {rollup.name!r} keeps it as a bucket"
                )

    for metric in draft.metrics:
        entity = entities.get(metric.grain)

        if entity is None:
            continue

        columns = frozenset(column.name for column in entity.columns)
        pinned = _pinned_columns(metric.expr, columns) if metric.expr is not None else ()

        for name in pinned:
            demand.setdefault((entity.name, name), set()).add(
                f"metric {metric.name!r} compares it against a literal instant"
            )

        for restriction in metric.filter:
            if restriction.dimension in columns:
                demand.setdefault((entity.name, restriction.dimension), set()).add(
                    f"metric {metric.name!r} filters on it by a literal instant"
                )

    return _refusals(project, entities, demand)


# ....................... #


def _refusals(
    project: Project,
    entities: Mapping[str, EntityIR],
    demand: Mapping[tuple[str, str], set[str]],
) -> list[GuardrailError]:
    """Ask R018 about each consumed column, and phrase what it refuses."""

    documents = {(one.source, one.target): mapping_doc(one) for one in project.mappings}
    errors: list[GuardrailError] = []

    for (entity_name, column), sites in sorted(demand.items()):
        entity = entities.get(entity_name)

        if entity is None:  # pragma: no cover — a mart cannot flatten an absent entity
            continue

        where = ", and ".join(sorted(sites))
        answer = prove_zone(
            _readings(entity, column), entity=entity_name, column=column, site=where
        )

        if not isinstance(answer, Refutation):
            continue

        (obligation,) = answer.obligations
        blamed = sorted(
            fact.source.removeprefix("mapping:").removesuffix(f".{column}")
            for fact in answer.rejected
        )
        errors.append(
            UndeclaredZone(
                f"{entity_name}.{column} is parsed from a wall clock and {where} — "
                f"{obligation.found}. A wall clock read as UTC is out by the offset of "
                "whatever clock it was written on, which moves rows across the boundary "
                "and leaves every check passing (RFC 0074 §5.3, R018). Fix: "
                f"{answer.remediation}",
                source_path=(
                    f"{documents.get((blamed[0], entity_name), blamed[0])}: fields.{column}"
                ),
            )
        )

    return errors
