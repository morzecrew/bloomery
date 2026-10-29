"""Dialect-neutral lowering primitives shared by the IR builder (S-0022),
the mart flattener (S-0027), and the guardrail stage's path-conflict
amendment (S-0023/D-7).

Three tiny pure functions: JSONPath-lite extraction against the bronze
relation, the canonical-text wrap into :class:`~bloomery.ir.nodes.SqlExpr`,
and the spec-string → :class:`~bloomery.ir.nodes.PartitionSpec` parse. They
live in the IR layer because every consumer sits above it and the results are
IR values — physical DDL types remain the dialect port's job (S-0025).

The neutral SQLGlot type for a logical type is **not** here. It is
:func:`bloomery.transforms.neutral_type`, which a builder declaring ``types``
needs as well; this module used to re-export it under a second name, which is
one definition and two spellings for callers to disagree over.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, date, datetime

from sqlglot import exp, jsonpath
from sqlglot.expressions.core import Expression

from bloomery.ir.nodes import (
    ColumnIR,
    EntityIR,
    MartIR,
    MetricIR,
    PartitionSpec,
    ProjectIR,
    SqlExpr,
    with_imported,
)
from bloomery.spec.common import PARTITION_SPEC_PATTERN
from bloomery.typing import DateType, LogicalType, TimestampType

# ----------------------- #

__all__ = [
    "bind_columns",
    "bound_name",
    "canon",
    "canonical_bindings",
    "extraction",
    "mart_expr",
    "partition_specs",
    "temporal_text",
    "unbound",
]

_PARTITION_RE = re.compile(PARTITION_SPEC_PATTERN)


def canon(node: Expression) -> SqlExpr:
    """Canonical dialect-neutral text (S-0020/sql-expressions-in-the-ir-sqlexpr)."""

    return SqlExpr(node.sql(pretty=False))


#: What a temporal literal must look like by the time it reaches a ``CAST``.
#:
#: **Trino will not cast an ISO 8601 timestamp.** Measured on Trino 483,
#: ``CAST('2024-01-01T00:00:00' AS TIMESTAMP)`` is an `INVALID_CAST_ARGUMENT`;
#: the space-separated form and a bare date both parse, and DuckDB and
#: PostgreSQL take either. The separator is not the only spelling that reaches
#: here, though — ``datetime.fromisoformat`` also accepts a lowercase ``t``, a
#: space, a trailing ``Z`` and an explicit offset, so substituting one character
#: fixes one of four inputs. The value is parsed and re-rendered instead.
#:
#: An offset is *converted*, not dropped: S-0045 makes ``timestamp`` zoneless
#: UTC on every port, so ``2024-01-01T09:00:00+02:00`` is the instant
#: ``2024-01-01 07:00:00`` and comparing it as though it were 09:00 would be
#: wrong by the offset. Refusing the spelling instead would lose a legitimate
#: one for no gain.
#:
#: One rule, every caller: an audit bound (S-0023/range-sanity), a metric filter
#: (S-0050/D-8) and a mapping's constant (S-0019/D-16) build the same construct — a text literal cast to the column's
#: neutral type — and the audit path carried the un-normalized form too,
#: pre-existing and unexercised because no fixture asserts a ``min``/``max`` on
#: a timestamp column.
#:
#: Rendered with ``isoformat`` rather than ``strftime``: ``%Y`` delegates year
#: padding to the C library, which is free to write ``1-01-01`` for year 1, and
#: S-0020 requires the same specs to produce byte-identical artifacts *across
#: machines*. It does pad on this platform — the point is that nothing promises
#: it will on the next one, and ``isoformat`` needs no promise. It also picks
#: the microsecond suffix itself, so there is no second branch to keep in step.


def temporal_text(value: str, declared: LogicalType) -> str:
    """One temporal literal in the spelling every shipped dialect casts.

    Gated on the declared type rather than on whether the text happens to look
    like a date: a ``string`` column may hold ``"2024-01-01T09:00:00"`` as data,
    and rewriting it there would silently change what the comparison matches.

    A value that does not parse is returned untouched — the metric-filter
    guardrail and the constant typecheck have already refused those (S-0050/D-9,
    S-0019/D-16), and an audit bound has its own validation, so this is not the
    place to invent a second refusal.
    """

    if isinstance(declared, DateType):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            return value

    if not isinstance(declared, TimestampType):
        return value

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)

    return parsed.isoformat(sep=" ", timespec="auto")


# ....................... #


def canonical_bindings(names: tuple[str, ...], columns: tuple[ColumnIR, ...]) -> dict[str, str]:
    """Each of ``names`` that one of ``columns`` links as its canonical, to that
    column's name, where the two are spelled differently (S-0022/D-10).

    A metric's ``expr`` is written over its ``requires:`` canonicals, and these
    are the grain entity's spellings of them. A canonical two columns link is
    left unbound, since neither is the one the expression means. So is one whose
    spelling is a name the expression still reads as written: binding ``a`` to a
    field ``b`` while canonical ``b`` stays unbound would read ``a + b`` as
    ``b + b``. Dropping one binding can strand another on the name it freed, so
    the drop runs until nothing changes.
    """

    linked: dict[str, list[str]] = {}

    for column in columns:
        if column.canonical is not None and column.canonical in names:
            linked.setdefault(column.canonical, []).append(column.name)

    bindings = {
        canonical: fields[0]
        for canonical, fields in sorted(linked.items())
        if len(fields) == 1 and fields[0] != canonical
    }

    while stranded := {
        canonical
        for canonical, field in bindings.items()
        if field in names and field not in bindings
    }:
        bindings = {
            canonical: field for canonical, field in bindings.items() if canonical not in stranded
        }

    return bindings


# ....................... #


def bound_name(name: str, columns: tuple[ColumnIR, ...]) -> str:
    """The grain column a metric's filter dimension or ``semi_additive.over``
    reads (S-0022/D-11): the column spelled ``name`` where the grain has one,
    else the one column that links ``name`` as its canonical, else ``name``.

    The column spelled as written comes first because, unlike an ``expr``, a
    dimension name declares no canonical: it names a mart column, and a
    template's canonical spelling is the fallback for a grain that lacks one.
    """

    if any(column.name == name for column in columns):
        return name

    return canonical_bindings((name,), columns).get(name, name)


# ....................... #


def mart_expr(metric: MetricIR, mart: MartIR, ir: ProjectIR) -> SqlExpr | None:
    """``metric``'s expression as ``mart`` reads it (S-0022/D-12).

    The IR build binds a canonical to the grain column that links it (D-10).
    One that a joined entity's column links reaches a mart only through a
    flatten, under that mart's prefix, so it is bound here, per mart: each
    canonical the expression still names and the mart carries no column of
    reads the one mart column flattened from another entity's column linking
    it. The grain's own columns are D-10's, including the bindings it declined.
    So are D-10's rules: a date bucket is not such a column, a canonical two
    columns could stand for is left as written, and so is one whose column is
    spelled as a name the expression reads as written. The measure check
    refuses whatever is left.
    """

    if metric.expr is None:
        return None

    carried = {column.name for column in mart.columns}
    links = {
        (entity.name, column.name): column.canonical
        for entity in with_imported(ir).entities
        for column in entity.columns
    }
    flattened: dict[str, list[str]] = {}

    for column in mart.columns:
        canonical = links.get((column.source_entity, column.source_column))
        if (
            column.ref is None
            and column.source_entity != metric.grain
            and canonical is not None
            and canonical in metric.depends_on
            and canonical not in carried
            and column.name not in metric.depends_on
        ):
            flattened.setdefault(canonical, []).append(column.name)

    bindings = {canonical: names[0] for canonical, names in flattened.items() if len(names) == 1}

    return canon(bind_columns(metric.expr.ast(), bindings)) if bindings else metric.expr


# ....................... #


def bind_columns(node: Expression, bindings: dict[str, str]) -> Expression:
    """``node`` with each unqualified column ``bindings`` names renamed, outside
    any subquery: a scalar subquery reads its own relation, not the mart."""

    def renamed(child: Expression) -> Expression:
        if (
            isinstance(child, exp.Column)
            and not child.table
            and child.name in bindings
            and child.find_ancestor(exp.Select) is None
        ):
            return exp.column(bindings[child.name])

        return child

    return node.transform(renamed)


# ....................... #


def unbound(metric: MetricIR, entities: tuple[EntityIR, ...]) -> MetricIR:
    """``metric`` with its expression back in the canonical spelling it was
    written in, undoing :func:`canonical_bindings` against this IR's own grain,
    and its filter dimensions and ``semi_additive.over`` in the canonical of the
    column each reads, undoing :func:`bound_name` (S-0022/D-11).

    Binding follows the field: renaming a linked field respells every metric
    bound to it and changes no number. Two versions compared in this form agree
    wherever the authored expression does, which is what ``plan()`` and
    ``timeline`` mean by a metric that did not move (S-0022/D-10).
    """

    columns = next((entity.columns for entity in entities if entity.name == metric.grain), ())
    spelled = {
        field: canonical
        for canonical, field in canonical_bindings(metric.depends_on, columns).items()
    }

    def canonical(name: str) -> str:
        # A dimension name back in the canonical a template would have written:
        # the canonical of the column it reads, where `bound_name` reads that
        # column for it (S-0022/D-11).
        link = next((column.canonical for column in columns if column.name == name), None)
        return link if link is not None and bound_name(link, columns) == name else name

    semi_additive = metric.semi_additive

    return replace(
        metric,
        expr=(
            canon(bind_columns(metric.expr.ast(), spelled))
            if metric.expr is not None and spelled
            else metric.expr
        ),
        filter=tuple(
            replace(
                clause,
                dimension=canonical(clause.dimension),
                column=None if clause.column is None else canonical(clause.column),
            )
            for clause in metric.filter
        ),
        semi_additive=(
            None
            if semi_additive is None
            else replace(
                semi_additive,
                over=replace(semi_additive.over, dimension=canonical(semi_additive.over.dimension)),
            )
        ),
    )


# ....................... #


def extraction(path: str) -> Expression:
    """Lower a JSONPath-lite ``$.a.b`` against the bronze relation: the first
    segment is the physical column, deeper segments are JSON extraction."""
    segments = path.removeprefix("$.").split(".")
    column = exp.column(segments[0])

    if len(segments) == 1:
        return column

    remainder = "$." + ".".join(segments[1:])
    return exp.JSONExtractScalar(this=column, expression=jsonpath.parse(remainder))


# ....................... #


def partition_specs(entries: tuple[str, ...]) -> tuple[PartitionSpec, ...]:
    """Parse spec-layer partition entries (``col`` or ``fn(col)``, S-0019
    §5.5) into :class:`PartitionSpec` values, authored order preserved
    (S-0020/D-4)."""
    specs: list[PartitionSpec] = []

    for entry in entries:
        match = _PARTITION_RE.match(entry)
        if match is None or match.group(2) is None:  # bare column form
            specs.append(PartitionSpec(transform=None, column=entry))
        else:
            specs.append(PartitionSpec(transform=match.group(1), column=match.group(2)))

    return tuple(specs)
