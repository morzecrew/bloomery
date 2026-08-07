"""Shared SELECT lowering (RFC 0008 §5.2): the dialect-neutral SQLGlot ASTs
every SQL-emitting target renders through its ``DialectPort``.

SQLMesh and dbt emit the *same* silver/gold SELECT for the same entity or
mart under the same dialect — only the envelope differs (RFC 0008 D1: target
and dialect never collapse). Keeping the AST construction here makes that a
structural property instead of a convention: an emitter that built its own
SELECT would be reintroducing the N×M template duplication the three-port
split exists to prevent (RFC 0008 §2).

Everything here is one dialect-neutral AST per artifact — never per-dialect
templates. Where engines disagree syntactically (the ``dim_date`` calendar),
the neutral node is chosen so SQLGlot's generators produce legal SQL on every
shipped dialect; the choice is documented at the node.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlglot import exp, parse_one

from bloomery.ir import (
    AuditIR,
    DateDimensionIR,
    EntityIR,
    Layer,
    MartColumnIR,
    MartIR,
    generic_type,
)
from bloomery.typing import DecimalType, IntType, LogicalType

if TYPE_CHECKING:
    from bloomery.emit.base import EmitContext

__all__ = [
    "audit_predicate",
    "column_type",
    "dim_date_select",
    "entity_select",
    "enum_literal",
    "mart_select",
]


def entity_select(entity: EntityIR, ctx: EmitContext) -> exp.Select:
    """The silver SELECT: every lowered column expression aliased to its
    declared name, from the bronze relation under the naming policy."""
    namespace, relation = ctx.naming.relation(entity.source.relation, Layer.BRONZE)
    projections = [exp.alias_(column.expr.ast(), column.name) for column in entity.columns]
    return exp.Select().select(*projections).from_(exp.table_(relation, db=namespace))


# ....................... #
# Mart lowering (RFC 0010 / RFC 0008 D11) — the only join-emitting path.


def _column_owner(mart: MartIR, column: MartColumnIR) -> str:
    """The join alias owning a flattened column: the base entity for its own
    (and date-role) columns, else the prefix of the join that flattened it."""
    if column.source_entity == mart.base and (
        column.ref is not None or column.name == column.source_column
    ):
        return mart.base
    return next(
        join.prefix
        for join in mart.joins
        if join.entity == column.source_entity
        and column.name == f"{join.prefix}{column.source_column}"
    )


def _mart_projection(mart: MartIR, column: MartColumnIR) -> exp.Expression:
    source = exp.column(column.source_column, table=_column_owner(mart, column))
    if column.ref is None:
        # ``alias_`` is annotated with the ``Expr`` base, but always returns
        # an ``Expression`` here (cf. ir.nodes on ``parse_one``).
        return cast("exp.Expression", exp.alias_(source, column.name))
    # Date-role bucket (RFC 0010 D4): DATE_TRUNC over the base source column,
    # cast to DATE so the emitted column has the declared IR type everywhere.
    # Built via ``exp.func`` — ``exp.DateTrunc``'s custom ``__init__`` is
    # untyped in this sqlglot version.
    bucketed = exp.func("DATE_TRUNC", exp.Literal.string(column.ref.dimension), source)
    return cast(
        "exp.Expression", exp.alias_(exp.cast(bucketed, exp.DataType.build("DATE")), column.name)
    )


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
        conditions = [
            exp.EQ(
                this=exp.column(owners[from_column][1], table=owners[from_column][0]),
                expression=exp.column(to_column, table=join.prefix),
            )
            for from_column, to_column in join.on
        ]
        select = select.join(
            exp.table_(relation, db=namespace, alias=join.prefix),
            on=exp.and_(*conditions),
            join_type="LEFT",
        )
    return select


# ....................... #
# Date dimension (RFC 0008 D13, RFC 0013 R1 rule 4)

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


def dim_date_select(dim: DateDimensionIR) -> exp.Expression:
    """The deterministic ``dim_date`` calendar SELECT — a generate-series
    calendar over the catalog's year bounds, no clock involved."""
    body = _DIM_DATE_BODY.format(start_year=dim.start_year, end_year=dim.end_year)
    # ``parse_one`` is annotated with the ``Expr`` base, but every node it
    # returns is an ``Expression`` (cf. ir.nodes).
    return cast("exp.Expression", parse_one(body))


# ....................... #
# Audit predicates (RFC 0006 §5.6/D7)


def column_type(entity: EntityIR, name: str) -> LogicalType:
    """The declared logical type of one entity column."""
    return next(column.type for column in entity.columns if column.name == name)


def _bound_literal(value: str, bound_type: LogicalType) -> exp.Expression:
    """A typed literal for an audit bound: numeric columns take number
    literals, everything else a string literal cast to the column type (so
    temporal comparisons never rely on engine coercion)."""
    if isinstance(bound_type, (IntType, DecimalType)):
        return exp.Literal.number(value)
    return exp.cast(exp.Literal.string(value), generic_type(bound_type))


def enum_literal(value: str, member_type: LogicalType) -> exp.Expression:
    """An ``accepted_values`` member literal, typed by the audited column."""
    if isinstance(member_type, IntType):
        return exp.Literal.number(value)
    return exp.Literal.string(value)


def audit_predicate(entity: EntityIR, audit: AuditIR, *, violations: bool) -> exp.Expression:
    """The predicate for one custom-bodied audit kind (``min``/``max``/
    ``regex``/``reconcile``).

    ``violations=True`` selects the failing rows (SQLMesh audit bodies pass
    when the query returns none); ``violations=False`` is the row-level
    assertion that must hold (dbt ``expression_is_true``-shaped tests). Both
    forms are built here, side by side, so the two targets cannot drift.
    """
    column = exp.column(audit.column)
    params = dict(audit.params)
    if audit.kind == "min":
        bound = _bound_literal(params["value"], column_type(entity, audit.column))
        if violations:
            return exp.LT(this=column, expression=bound)
        return exp.GTE(this=column, expression=bound)
    if audit.kind == "max":
        bound = _bound_literal(params["value"], column_type(entity, audit.column))
        if violations:
            return exp.GT(this=column, expression=bound)
        return exp.LTE(this=column, expression=bound)
    if audit.kind == "regex":
        matches = exp.RegexpLike(this=column, expression=exp.Literal.string(params["pattern"]))
        return exp.Not(this=matches) if violations else matches
    # "reconcile" — the only remaining custom kind (RFC 0006 D7): row-level
    # disagreement between the derived column and its __direct shadow.
    shadow = exp.column(params["shadow"])
    if violations:
        return exp.NullSafeNEQ(this=column, expression=shadow)
    return exp.NullSafeEQ(this=column, expression=shadow)
