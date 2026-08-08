"""The disposition-precedence warehouse (RFC 0016 D18/D20/D22, §5.6, §5.8).

The spec side lives in ``tests/fixtures/quality_precedence/``; this module is
the data side and the build. The numbers are small and hand-checkable on
purpose — every count the quality-mart suite asserts is derivable from the
table below by reading it:

===========  ====================================================
``q__lines``  10 rows; ``r01``/``r03`` lose their key to a later
              delivery, so **8** survive dedupe. ``r05``/``r06``/
              ``r07`` share a ``code``, so ``code_unique`` diverts
              **3** rows; ``r07`` also carries a ``status`` outside
              the declared set, so the per-rule diversion counts
              sum to **4** over **3** distinct rows. ``r07`` and
              ``r09`` carry a negative ``amount``, the fixture's one
              ``fail`` rule — one of them diverted, one of them
              kept, which is exactly D18's precedence case.
===========  ====================================================

Two seeds are deliberately *not* the same shape as ``dirty_corpus``'s: this
module hands out explicit row tuples rather than reading a CSV, because the
point here is a population whose expected counts a reviewer can verify without
opening a data file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from support.compiling import FIXTURES, compile_fixture, fixture_sources, load_fixture
from support.execution import materialize, warehouse

from bloomery import Target, build_project_ir, compile_project, load_catalog, load_project

if TYPE_CHECKING:
    import duckdb

    from bloomery.emit import EmittedArtifact
    from bloomery.ir import ProjectIR
    from bloomery.spec import Project

__all__ = [
    "BELOW_BOUND",
    "DEDUPED",
    "DIVERTED",
    "DUPLICATED_KEY",
    "DUPLICATE_WINNER",
    "EVALUATED",
    "FIXTURE",
    "KEPT",
    "NARROW_SET",
    "NULL_SOURCE_ROW",
    "QUARANTINED",
    "WIDE_SET",
    "build",
    "compile_widened",
    "project_ir",
    "seed",
]

FIXTURE = "quality_precedence"

#: What the ``q__lines`` seed below *is*, stated once so a suite asserts the
#: fixture's design rather than re-deriving it (and so a change to the seed
#: fails loudly here instead of quietly moving an expectation).
EVALUATED = 8
DEDUPED = 2
QUARANTINED = 3
KEPT = EVALUATED - QUARANTINED

#: The membership set ``q_dup`` declares, and the widening the replay test
#: applies — spelled as the literal spec text, so the "diff" the test applies
#: is the diff a reviewer would see in a pull request.
NARROW_SET = "values: [open, closed]"
WIDE_SET = "values: [open, closed, legacy]"

#: ``(_load_id, _ingested_at, _source_row_id, order_id, line_no, order_date,
#: amount, code, status)``. Timestamps and dates are text: the mapping casts
#: them, and bronze in this project is always-text by contract.
_LINES: tuple[tuple[str | None, ...], ...] = (
    # Two keys delivered twice — the earlier delivery loses the dedupe QUALIFY.
    ("load_a", "2024-01-01T00:00:01Z", "r01", "O1", "1", "2024-01-01", "10", "C01", "open"),
    ("load_a", "2024-01-01T00:00:02Z", "r02", "O1", "1", "2024-01-01", "11", "C02", "open"),
    ("load_a", "2024-01-01T00:00:01Z", "r03", "O1", "2", "2024-01-01", "12", "C03", "open"),
    ("load_a", "2024-01-01T00:00:02Z", "r04", "O1", "2", "2024-01-01", "13", "C04", "open"),
    # Three rows sharing a code — `unique` diverts all three.
    ("load_a", "2024-01-01T00:00:03Z", "r05", "O2", "1", "2024-01-01", "14", "DUP", "open"),
    ("load_a", "2024-01-01T00:00:03Z", "r06", "O2", "2", "2024-01-01", "15", "DUP", "open"),
    # …and this one also fails `in_set` **and** the `fail`-disposition bound.
    ("load_a", "2024-01-01T00:00:03Z", "r07", "O3", "1", "2024-01-01", "-5", "DUP", "bad"),
    ("load_a", "2024-01-01T00:00:03Z", "r08", "O3", "2", "2024-01-01", "16", "C08", "open"),
    # Below the bound but diverted by nothing: the `fail` rule's other row, and
    # therefore the fixture's one row that reaches a **mart** carrying a flag.
    # Everything else the rules fire on is diverted before the mart sees it, so
    # without this row `has_quality_flags` would be constant FALSE on live data
    # — which is exactly how an inverted polarity ships green (RFC 0016 §5.5).
    ("load_a", "2024-01-01T00:00:03Z", "r09", "O4", "1", "2024-01-01", "-7", "C09", "open"),
    ("load_a", "2024-01-01T00:00:03Z", "r10", "O4", "2", "2024-01-01", "18", "C10", "open"),
)

#: The identities the split diverts, and the two the `fail` rule fires on.
DIVERTED = ("r05", "r06", "r07")
BELOW_BOUND = ("r07", "r09")

#: ``(_load_id, _ingested_at, _source_row_id, code_id, code_flag, code_quar,
#: code_fail)`` — one duplicated pair per disposition, disjoint so each
#: disposition's outcome is readable without the others interfering.
_CODES: tuple[tuple[str | None, ...], ...] = (
    ("load_a", "2024-01-01T00:00:00Z", "c01", "K1", "SAME", "q1", "f1"),
    ("load_a", "2024-01-01T00:00:00Z", "c02", "K2", "SAME", "q2", "f2"),
    ("load_a", "2024-01-01T00:00:00Z", "c03", "K3", "a3", "SAME", "f3"),
    ("load_a", "2024-01-01T00:00:00Z", "c04", "K4", "a4", "SAME", "f4"),
    ("load_a", "2024-01-01T00:00:00Z", "c05", "K5", "a5", "q5", "SAME"),
    ("load_a", "2024-01-01T00:00:00Z", "c06", "K6", "a6", "q6", "SAME"),
)

#: ``(_load_id, _ingested_at, _source_row_id, group_id, status, note)`` — two
#: rows on one entity key, both outside the declared set. ``d02`` wins the D20
#: order on both counts (later recency, higher identity), so a replay that
#: picks a winner at all has exactly one right answer. ``d04`` carries a
#: genuinely NULL ``note``: not a coercion failure, and the `coercible`-at-
#: `fail` audit must not mistake it for one.
_DUPS: tuple[tuple[str | None, ...], ...] = (
    ("load_a", "2024-01-01T00:00:01Z", "d01", "G1", "legacy", "earlier"),
    ("load_a", "2024-01-02T00:00:01Z", "d02", "G1", "legacy", "later"),
    ("load_a", "2024-01-01T00:00:01Z", "d03", "G2", "open", "clean"),
    ("load_a", "2024-01-01T00:00:01Z", "d04", "G3", "open", None),
)

#: The one entity key ``q_dup`` delivers twice, and the D20 winner among them.
DUPLICATED_KEY = "G1"
DUPLICATE_WINNER = "later"
NULL_SOURCE_ROW = "d04"

_SEEDS: tuple[tuple[str, tuple[str, ...], tuple[tuple[str | None, ...], ...]], ...] = (
    (
        "q__lines",
        (
            "_load_id",
            "_ingested_at",
            "_source_row_id",
            "order_id",
            "line_no",
            "order_date",
            "amount",
            "code",
            "status",
        ),
        _LINES,
    ),
    (
        "q__codes",
        (
            "_load_id",
            "_ingested_at",
            "_source_row_id",
            "code_id",
            "code_flag",
            "code_quar",
            "code_fail",
        ),
        _CODES,
    ),
    (
        "q__dups",
        ("_load_id", "_ingested_at", "_source_row_id", "group_id", "status", "note"),
        _DUPS,
    ),
)


def seed(conn: duckdb.DuckDBPyConnection) -> None:
    """Fill every bronze relation the fixture maps, all columns text."""
    for relation, columns, rows in _SEEDS:
        declaration = ", ".join(f"{column} VARCHAR" for column in columns)
        conn.execute(f"DROP TABLE IF EXISTS bronze.{relation}")
        conn.execute(f"CREATE TABLE bronze.{relation} ({declaration})")
        placeholders = ", ".join("?" for _ in columns)
        conn.executemany(
            f"INSERT INTO bronze.{relation} VALUES ({placeholders})", [list(row) for row in rows]
        )


def build() -> duckdb.DuckDBPyConnection:
    """Seed bronze, compile the fixture, materialize every model."""
    conn = warehouse()
    seed(conn)
    materialize(conn, compile_fixture(FIXTURE))
    return conn


def _sources(*, widened: bool) -> dict[str, str]:
    sources = dict(fixture_sources(FIXTURE))
    if widened:
        assert NARROW_SET in sources["mapping_dups"]
        sources["mapping_dups"] = sources["mapping_dups"].replace(NARROW_SET, WIDE_SET)
    return sources


def project_ir(*, widened: bool = False) -> tuple[Project, ProjectIR]:
    """The fixture's project and IR, optionally with ``q_dup``'s set widened."""
    project = load_project(_sources(widened=widened))
    catalog = load_catalog((FIXTURES / FIXTURE / "catalog.yaml").read_text())
    return project, build_project_ir(project, catalog)


def compile_widened() -> tuple[EmittedArtifact, ...]:
    """The artifacts of the widened project — the spec fix that turns
    ``q_dup``'s two reject rows into two replay candidates for one key."""
    _spec, catalog = load_fixture(FIXTURE)
    project, _ir = project_ir(widened=True)
    return compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog)
