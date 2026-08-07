"""The ``_quality_flags`` / ``failed_rules`` physical contract (RFC 0016 §5.5,
D23) and its **single-pass** construction (§5.4).

One contract, two lowerings, pinned so they agree observably:

- rule names are identifier-constrained (``[a-z0-9_]+``) at spec parse and at
  generation, so **no escaping is ever needed** in either shape;
- the column is **never NULL** — a clean row carries the empty array (array
  dialects) or the empty string (delimited fallback);
- the delimited fallback joins with ``,`` in **lexicographic rule-name order**,
  for deterministic bytes; the array shape uses the same order, so a
  flag-set comparison across the two lowerings is a straight equality;
- ``_quality_ok`` is generated per shape: ``CARDINALITY(flags) = 0`` against
  the array, ``flags = ''`` against the string.

Which shape applies is a **dialect** property (``DialectFeature.ARRAY``, D9) —
deliberately not a target capability: SQLMesh-on-DuckDB and dbt-on-DuckDB share
it (the RFC 0008 D1 split).

**Single pass.** §5.4's table says all flag rules land in *one*
array-construct pass, never N scans. :func:`flags_expression` therefore builds
exactly one expression per row, folding one ``CASE`` per rule into a single
concatenation — every predicate is evaluated once, in one projection, over one
scan of the deduped rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.quality.catalogue import FLAGS_COLUMN

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "DELIMITER",
    "FLAG_ARRAY_TYPE",
    "empty_flags",
    "flag_member",
    "flags_expression",
    "quality_ok",
]

#: The delimited fallback's separator (D23).
DELIMITER = ","

#: The neutral element type of the flag array. Rendered per dialect by
#: SQLGlot: ``TEXT[]`` (DuckDB/Postgres), ``ARRAY(VARCHAR)`` (Trino).
FLAG_ARRAY_TYPE = "TEXT[]"


def empty_flags(*, arrays: bool) -> Expression:
    """The clean-row value: an empty typed array, or the empty string.

    The cast on the empty array is not decoration — bare ``ARRAY[]`` has no
    inferable element type on Postgres, so an uncast empty literal would make
    the fallback-free dialects the ones that fail.
    """
    if not arrays:
        return exp.Literal.string("")
    return exp.cast(exp.Array(expressions=[]), exp.DataType.build(FLAG_ARRAY_TYPE))


def _array_flags(pairs: Sequence[tuple[str, Expression]]) -> Expression:
    """Nested ``ARRAY_CONCAT`` over one conditional singleton per rule.

    ``ARRAY_CONCAT`` is the neutral node SQLGlot renders as ``LIST_CONCAT``
    (DuckDB), ``ARRAY_CAT`` (Postgres) and ``CONCAT`` (Trino) — one AST, per
    dialect legal rendering, the RFC 0008 doctrine.
    """
    empty = empty_flags(arrays=True)
    node: Expression | None = None
    for name, predicate in pairs:
        singleton = exp.Case(
            ifs=[exp.If(this=predicate, true=exp.Array(expressions=[exp.Literal.string(name)]))],
            default=empty.copy(),
        )
        # ``exp.func`` is annotated with the ``Func`` base, but every node it
        # builds here is an ``Expression`` (cf. ir.nodes on ``parse_one``).
        node = (
            singleton
            if node is None
            else cast("Expression", exp.func("ARRAY_CONCAT", node, singleton))
        )
    return node if node is not None else empty


def _delimited_flags(pairs: Sequence[tuple[str, Expression]]) -> Expression:
    """``LTRIM(<one ',name' fragment per rule>, ',')``.

    Each rule contributes ``',' || name`` or ``''``; concatenating leaves at
    most one leading separator, which the trim removes. Trimming *leading*
    rather than trailing keeps the fragment shape uniform — every fragment is
    the same expression modulo its literal, which is what makes the pass
    single and the bytes deterministic.
    """
    fragments = [
        exp.Case(
            ifs=[exp.If(this=predicate, true=exp.Literal.string(f"{DELIMITER}{name}"))],
            default=exp.Literal.string(""),
        )
        for name, predicate in pairs
    ]
    if not fragments:
        return empty_flags(arrays=False)
    joined = fragments[0] if len(fragments) == 1 else exp.func("CONCAT", *fragments)
    return exp.Trim(this=joined, expression=exp.Literal.string(DELIMITER), position="LEADING")


def flags_expression(pairs: Sequence[tuple[str, Expression]], *, arrays: bool) -> Expression:
    """One expression producing the whole flag collection for a row.

    ``pairs`` is ``(rule name, violation predicate)``; callers pass it sorted
    lexicographically by name — the D23 order both shapes share. The result is
    never NULL: an unmatched ``CASE`` falls through to the empty element, not
    to ``NULL``, so a clean row carries the empty collection.
    """
    ordered = sorted(pairs, key=lambda pair: pair[0])
    return _array_flags(ordered) if arrays else _delimited_flags(ordered)


def flag_member(flags: Expression, name: str, *, arrays: bool) -> Expression:
    """Whether rule ``name`` fired on this row — read back off a *stored* flag
    collection, in whichever shape the dialect stores it (D23).

    The read side of :func:`flags_expression`, and the one place a stored
    ``_quality_flags`` / ``failed_rules`` value is interrogated: the quality
    mart counts per rule (RFC 0016 §5.8) over rows whose predicates were
    already evaluated upstream, so it *must* read the recorded names rather
    than re-evaluate — re-evaluating would be a second implementation of every
    rule, and the reject table no longer carries the source columns to do it
    with anyway.

    The delimited shape is matched by position, not ``LIKE``: rule names
    legitimately contain ``_``, which is ``LIKE``'s single-character wildcard,
    so a pattern match would report ``stock_level`` present when the row
    carries ``stockXlevel``. Wrapping both sides in the delimiter is what makes
    a substring search exact — ``,a,`` cannot occur inside ``,ab,``.
    """
    if arrays:
        return exp.ArrayContains(this=flags, expression=exp.Literal.string(name))
    delimiter = exp.Literal.string(DELIMITER)
    haystack = exp.func("CONCAT", delimiter.copy(), flags, delimiter.copy())
    needle = exp.Literal.string(f"{DELIMITER}{name}{DELIMITER}")
    return exp.GT(
        this=exp.StrPosition(this=haystack, substr=needle), expression=exp.Literal.number(0)
    )


def quality_ok(column: str = FLAGS_COLUMN, *, table: str | None = None, arrays: bool) -> Expression:
    """``_quality_ok``, generated per shape (D23) from the flag column."""
    reference = exp.column(column, table=table) if table else exp.column(column)
    if not arrays:
        return exp.EQ(this=reference, expression=exp.Literal.string(""))
    # ``exp.ArraySize`` is the neutral node: SQLGlot renders it ``ARRAY_LENGTH``
    # on DuckDB, ``ARRAY_LENGTH(x, 1)`` on Postgres and ``CARDINALITY`` on
    # Trino. Spelling ``CARDINALITY`` directly would look more like the RFC's
    # prose and be wrong — DuckDB's ``CARDINALITY`` operates on MAPs only.
    return exp.EQ(this=exp.ArraySize(this=reference), expression=exp.Literal.number(0))
