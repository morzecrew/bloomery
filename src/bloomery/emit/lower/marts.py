"""Mart lowering and the date dimension (RFC 0010, RFC 0008 D11/D13).

The only join-emitting path, plus the canonical calendar body. Also home to
the cheapest-mart measure-ownership rule, which is shared lowering rather than
any one target's: Cube, the MetricFlow manifest and the planner's coverage
precheck all apply it, so the three surfaces cannot disagree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlglot import exp, parse_one
from sqlglot.expressions.core import Expression

from bloomery.emit.lower.predicates import as_of_conditions
from bloomery.errors import guaranteed
from bloomery.ir import (
    VALID_FROM,
    VALID_TO,
    DateDimensionIR,
    Layer,
    MartColumnIR,
    MartIR,
    MartJoinIR,
    ProjectIR,
)
from bloomery.marts import HAS_QUALITY_FLAGS

if TYPE_CHECKING:
    from bloomery.emit.base import EmitContext

# ....................... #
# Mart lowering (RFC 0010 / RFC 0008 D11) — the only join-emitting path.


def _column_owner(mart: MartIR, column: MartColumnIR) -> str:
    """The join alias owning a flattened column: the base entity for its own
    (and date-role, and ``has_quality_flags``) columns, else the prefix of the
    join that flattened it."""

    if column.source_entity == mart.base and (
        column.ref is not None
        or column.name == column.source_column
        or column.name == HAS_QUALITY_FLAGS
    ):
        return mart.base

    return guaranteed(
        (
            join.prefix
            for join in mart.joins
            if join.entity == column.source_entity
            and column.name == f"{join.prefix}{column.source_column}"
        ),
        expected=f"the join that flattened column {column.name!r} onto mart {mart.name!r}",
        by="the mart flattener, which names every column after the join it came from",
    )


# ....................... #


def _mart_projection(mart: MartIR, column: MartColumnIR) -> Expression:
    source = exp.column(column.source_column, table=_column_owner(mart, column))

    if column.name == HAS_QUALITY_FLAGS:
        # RFC 0016 §5.5: an ordinary dimension, *derived* from the base's
        # generated ``_quality_ok`` (D23) rather than re-evaluated. ``NOT`` is
        # two-valued here by construction — ``_quality_ok`` is generated from
        # a never-NULL flag collection, so it is never NULL either.
        return cast("Expression", exp.alias_(exp.Not(this=source), column.name))

    if column.ref is None:
        # ``alias_`` is annotated with the ``Expr`` base, but always returns
        # an ``Expression`` here (cf. ir.nodes on ``parse_one``).
        return cast("Expression", exp.alias_(source, column.name))

    # Date-role bucket (RFC 0010 D4): DATE_TRUNC over the base source column,
    # cast to DATE so the emitted column has the declared IR type everywhere.
    # Built via ``exp.func`` — ``exp.DateTrunc``'s custom ``__init__`` is
    # untyped in this sqlglot version.
    bucketed = exp.func("DATE_TRUNC", exp.Literal.string(column.ref.dimension), source)
    return cast(
        "Expression", exp.alias_(exp.cast(bucketed, exp.DataType.build("DATE")), column.name)
    )


# ....................... #


def mart_select(mart: MartIR, ctx: EmitContext) -> exp.Select:
    """The wide SELECT: base silver relation LEFT-joined once per resolved
    ``MartJoinIR``, projecting the full flattened column set."""
    owners = {
        column.name: (_column_owner(mart, column), column.source_column)
        for column in mart.columns
        if column.ref is None
    }
    base_namespace, base_relation = ctx.naming.relation(mart.base, Layer.SILVER)
    select = (
        exp.Select()
        .select(*[_mart_projection(mart, column) for column in mart.columns])
        .from_(exp.table_(base_relation, db=base_namespace, alias=mart.base))
    )

    for join in mart.joins:
        namespace, relation = ctx.naming.relation(join.entity, Layer.SILVER)
        conditions: list[Expression] = [
            exp.EQ(
                this=_owned(owners, from_column),
                expression=exp.column(to_column, table=join.prefix),
            )
            for from_column, to_column in join.on
        ]
        conditions.extend(_as_of_conditions(join, owners))
        select = select.join(
            exp.table_(relation, db=namespace, alias=join.prefix),
            on=exp.and_(*conditions),
            join_type="LEFT",
        )

    return select


# ....................... #


def _owned(owners: dict[str, tuple[str, str]], column: str) -> exp.Column:
    """A mart-namespace column name, resolved to the join alias that owns it.

    Both halves of a join's ``ON`` read through here — the equality's left
    side and an as-of anchor — because both are names in the mart's namespace
    that have to be traced back to the relation they came from.

    The lookup cannot miss, and :func:`guaranteed` is where that claim is
    written down rather than left implicit in a ``KeyError``. Two separate
    stages make it true: the flattener seeds every base column into the mart
    (so an anchor, which it accepts only when it names one, is always there),
    and it refuses a date role whose bucket would collide with an existing
    column — which is what stops a ``ref``-carrying bucket from displacing the
    base column this map is keyed on. Those guards live in another module, and
    before this helper nothing here said they were being relied upon.
    """
    return guaranteed(
        (
            exp.column(owners[name][1], table=owners[name][0])
            for name in (column,)
            if name in owners
        ),
        expected=f"mart column {column!r} among the columns the flattener resolved",
        by="the mart flattener, which seeds every base column and refuses a colliding role",
    )


# ....................... #


def _as_of_conditions(join: MartJoinIR, owners: dict[str, tuple[str, str]]) -> list[Expression]:
    """The validity-interval half of an as-of join (RFC 0023 §5.3), or ``[]``.

    The predicate itself is :func:`as_of_conditions` in the lowering base,
    shared with the currency conversion that reads a rate's interval the same
    way (D6). What is local here is only what a *mart join* names: the
    dimension's interval columns are the two IR constants, under this join's
    prefix, and the anchor is a mart column resolved to the relation that owns
    it.
    """
    if join.as_of is None:
        return []

    return as_of_conditions(
        _owned(owners, join.as_of),
        table=join.prefix,
        valid_from=VALID_FROM,
        valid_to=VALID_TO,
    )


# ....................... #
# Date dimension (RFC 0008 D13, RFC 0013 R1 rule 4)


# ....................... #


# Canonical dialect-neutral calendar body, re-parsed at emit like any SqlExpr
# (RFC 0003 D2). Bounds interpolate as spec-validated integers only — the SQL
# is a pure function of the catalog definition, never of a clock.
#
# The series is a FROM-clause table function, not a projection-level UNNEST:
# ``SELECT UNNEST(...)`` is illegal on Trino (UNNEST is FROM-only there) and
# on Postgres (``UNNEST`` takes an array, ``generate_series`` returns a set).
# From this one neutral node SQLGlot generates ``GENERATE_SERIES(...) AS
# date_day(date_day)`` on DuckDB/Postgres and ``UNNEST(SEQUENCE(...))`` on
# Trino. Trino's generator carries only the *table* alias onto the UNNEST
# column, so the alias is named ``date_day`` — making the column resolve to
# the same name on every shipped dialect.
_DIM_DATE_BODY = (
    "SELECT"
    " CAST(date_day AS DATE) AS date_day,"
    " CAST(DATE_TRUNC('month', date_day) AS DATE) AS date_month,"
    " CAST(DATE_TRUNC('quarter', date_day) AS DATE) AS date_quarter,"
    " CAST(DATE_TRUNC('week', date_day) AS DATE) AS date_week,"
    " CAST(DATE_TRUNC('year', date_day) AS DATE) AS date_year"
    " FROM GENERATE_SERIES("
    "CAST('{start_year}-01-01' AS DATE), CAST('{end_year}-12-31' AS DATE),"
    " INTERVAL '1' DAY) AS date_day(date_day)"
)


def dim_date_select(dim: DateDimensionIR) -> Expression:
    """The deterministic ``dim_date`` calendar SELECT — a generate-series
    calendar over the catalog's year bounds, no clock involved."""
    body = _DIM_DATE_BODY.format(start_year=f"{dim.start_year:04d}", end_year=f"{dim.end_year:04d}")
    # ``parse_one`` is annotated with the ``Expr`` base, but every node it
    # returns is an ``Expression`` (cf. ir.nodes).
    return cast("Expression", parse_one(body))


# ....................... #
# Measure ownership (RFC 0010 D8). Shared lowering, not any one
# target's: Cube's measure emission, the MetricFlow manifest and the
# planner's coverage precheck all apply this rule, so the three
# surfaces cannot disagree. It lived in emit/metricflow/ and made Cube
# import a sibling target — the one violation of RFC 0019's contract 3
# on the tree it was written against.


# ....................... #


def measure_owners(ir: ProjectIR) -> dict[str, MartIR]:
    """Metric name → the single mart its measure is emitted on: cheapest
    ``cost_hint``, ties lexicographic by mart name (RFC 0010 D8).

    Public on purpose: the planner's coverage precheck (RFC 0013 R3) imports
    this exact function, so the emitter's measure placement and the planner's
    mart selection cannot disagree."""
    owners: dict[str, MartIR] = {}

    for mart in ir.marts:
        for name in mart.measures:
            current = owners.get(name)
            if current is None or (mart.cost_hint, mart.name) < (
                current.cost_hint,
                current.name,
            ):
                owners[name] = mart

    return owners
