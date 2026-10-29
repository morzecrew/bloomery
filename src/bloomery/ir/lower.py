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

# ----------------------- #

__all__ = [
    "bind_columns",
    "canon",
    "canonical_bindings",
    "extraction",
    "mart_expr",
    "partition_specs",
    "unbound",
]

_PARTITION_RE = re.compile(PARTITION_SPEC_PATTERN)


def canon(node: Expression) -> SqlExpr:
    """Canonical dialect-neutral text (S-0020/sql-expressions-in-the-ir-sqlexpr)."""

    return SqlExpr(node.sql(pretty=False))


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
    written in, undoing :func:`canonical_bindings` against this IR's own grain.

    Binding follows the field: renaming a linked field respells every metric
    bound to it and changes no number. Two versions compared in this form agree
    wherever the authored expression does, which is what ``plan()`` and
    ``timeline`` mean by a metric that did not move (S-0022/D-10).
    """

    if metric.expr is None:
        return metric

    columns = next((entity.columns for entity in entities if entity.name == metric.grain), ())
    spelled = {
        field: canonical
        for canonical, field in canonical_bindings(metric.depends_on, columns).items()
    }

    if not spelled:
        return metric

    return replace(metric, expr=canon(bind_columns(metric.expr.ast(), spelled)))


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
