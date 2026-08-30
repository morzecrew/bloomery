"""The dedupe lowering (RFC 0016 §5.4, D20): ``QUALIFY ROW_NUMBER() OVER
(PARTITION BY <entity key> ORDER BY …) = 1``.

**One neutral AST, per-dialect legal rendering.** ``QUALIFY`` is DuckDB-native;
Postgres and any engine without it get the equivalent ``ROW_NUMBER``-in-a-
subquery form from *this same* AST through SQLGlot's generators — the RFC 0008
doctrine, not a second template.

**The order is total.** ``field`` DESC, then each ``tie_break`` column DESC in
authored order, then the stable source-row identity ``_source_row_id`` DESC.
No two rows can compare equal *given the D21 metadata contract*
(``_source_row_id`` NOT NULL and unique per source row — a data property the
generated blocking audit enforces at run time). Null ordering is pinned
``NULLS LAST`` on **every** sort key, ``_source_row_id`` included: ``DESC``
defaults to ``NULLS FIRST`` on several engines, so an illegally-null identity
must still lose, never win — defense in depth behind the audit.

The same ordering is what replay merges by (D22), so it is built here once and
read by both the entity pipeline and the replay artifact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.errors import guaranteed
from bloomery.quality.catalogue import INGESTION_METADATA

if TYPE_CHECKING:
    from bloomery.ir import DedupeIR

# ----------------------- #

__all__ = [
    "ROW_ID_COLUMN",
    "dedupe_order",
    "dedupe_row_number",
    "dedupe_sort_columns",
    "with_dedupe_qualify",
]

#: The final, tie-breaking sort key — the stable source-row identity, drawn
#: from the ingestion-metadata contract so the two lists cannot drift.
ROW_ID_COLUMN = guaranteed(
    (name for name in INGESTION_METADATA if name == "_source_row_id"),
    expected="'_source_row_id' among the ingestion-metadata columns",
    by="INGESTION_METADATA itself (RFC 0016 D21)",
)


def dedupe_sort_columns(dedupe: DedupeIR) -> tuple[str, ...]:
    """The total order's columns, in order: recency field, tie-breaks
    (authored order — a sort order is semantic, RFC 0003 D4), row identity."""

    return (dedupe.field, *dedupe.tie_break, ROW_ID_COLUMN)


# ....................... #


def dedupe_order(dedupe: DedupeIR, *, table: str | None = None) -> tuple[exp.Ordered, ...]:
    """One ``DESC NULLS LAST`` term per sort column (D20)."""

    return tuple(
        exp.Ordered(this=exp.column(name, table=table), desc=True, nulls_first=False)
        for name in dedupe_sort_columns(dedupe)
    )


# ....................... #


def dedupe_row_number(
    dedupe: DedupeIR, key: tuple[str, ...], *, table: str | None = None
) -> Expression:
    """``ROW_NUMBER() OVER (PARTITION BY <key> ORDER BY <total order>)``.

    Partitioning is by the **entity key** — dedupe keeps one row per key, and
    replay merges by the same key (RFC 0016 §5.3).
    """

    return exp.Window(
        this=exp.RowNumber(),
        partition_by=[exp.column(name, table=table) for name in key],
        order=exp.Order(expressions=list(dedupe_order(dedupe, table=table))),
    )


# ....................... #


def with_dedupe_qualify(select: exp.Select, dedupe: DedupeIR, key: tuple[str, ...]) -> exp.Select:
    """Attach the winner-takes-all ``QUALIFY`` to a SELECT (stage 3 of the
    fixed pipeline order). Returns a new SELECT; the input is not mutated."""
    winner = exp.EQ(this=dedupe_row_number(dedupe, key), expression=exp.Literal.number(1))
    qualified = select.copy()
    qualified.set("qualify", exp.Qualify(this=winner))

    return qualified
