"""The Redshift dialect (S-0015): physical types, the capabilities the port
declares, and every rewrite it carries — asserted at the rendering level so the
default suite covers them.

The offline rungs for a port whose engine no tier runs: a sabotage sweep on the
PostgreSQL port found that neutering a rewrite left every non-Docker tier green,
and here there is no engine tier at all (S-0015/D-2 — the surrogate lane is
PostgreSQL wearing a Redshift shape, and it cannot speak to `SUPER`, PartiQL or
Redshift's own functions). So each rewrite is pinned here, and the rendered SQL
is re-parsed under the dialect as a syntax floor.
"""

from __future__ import annotations

import pytest
import sqlglot
from sqlglot import exp, parse_one

from bloomery.dialects import PostgresDialect, RedshiftDialect
from bloomery.dialects.base import DialectFeature
from bloomery.errors import UnsupportedByTarget
from bloomery.ir.lower import canon
from bloomery.transforms import DEFAULT_REGISTRY
from bloomery.typing import (
    BoolType,
    DateType,
    DecimalType,
    IntType,
    LogicalType,
    StringType,
    TimestampType,
    VariantType,
)
from support.compiling import compile_fixture, extract_select

pytestmark = pytest.mark.unit

DIALECT = RedshiftDialect()


def _rendered(transform: str, *args: object, input_type: LogicalType | None = None) -> str:
    """A transform as this port emits it, through the canonical round trip the
    IR performs at emit (S-0020/D-2)."""
    spec = DEFAULT_REGISTRY[transform]
    extra = {"input_type": input_type} if spec.types else {}
    return DIALECT.render(canon(spec.builder(exp.column("x"), *args, **extra)).ast())


@pytest.mark.parametrize(
    ("logical", "physical"),
    [
        # Not `TEXT`: Redshift accepts the word and quietly means
        # `VARCHAR(256)` by it, which truncates at the 257th character
        # (S-0025/D-3 refuses silent data loss).
        (StringType(), "VARCHAR(MAX)"),
        (IntType(), "BIGINT"),
        (DecimalType(12, 4), "DECIMAL(12, 4)"),
        (DecimalType(38, 0), "DECIMAL(38, 0)"),
        (BoolType(), "BOOLEAN"),
        (DateType(), "DATE"),
        (TimestampType(), "TIMESTAMP"),
        (VariantType(), "SUPER"),  # not JSONB, which Redshift does not have
    ],
)
def test_physical_type_for_every_logical_type(logical: LogicalType, physical: str) -> None:
    assert DIALECT.physical_type(logical) == physical


def test_render_is_the_redshift_generator() -> None:
    assert DIALECT.name == "redshift"
    assert DIALECT.sqlglot_dialect == "redshift"


def test_the_declared_capabilities_are_the_three_redshift_lacks() -> None:
    """The capability set is what an emitter reads before lowering, so a wrong
    flag is a silent approximation rather than a refusal.

    `ARRAY` (S-0015/D-6) — Redshift has no array *column* type, so
    `_quality_flags` and `failed_rules` take the delimited-string fallback.
    `UNICODE_NORMALIZE` — no normalization function exists at all.
    `JSON_EXTRACT` — `SUPER` is navigated with PartiQL, not with `jsonb`'s
    operators (S-0015/D-4).
    """
    assert set(DialectFeature) - DIALECT.features == {
        DialectFeature.ARRAY,
        DialectFeature.UNICODE_NORMALIZE,
        DialectFeature.JSON_EXTRACT,
    }
    # Declared, and so owed: the `coercible` marker needs a cast that yields
    # NULL rather than raising, including over `SUPER`.
    assert DIALECT.supports(DialectFeature.TRY_CAST)


def test_render_never_mutates_the_shared_ast() -> None:
    # One neutral AST renders on every dialect (S-0025/D-1); this port rewrites
    # more of it than any other, so a missed copy would leak into the next.
    node = parse_one("SELECT STARTS_WITH(x, 'a'), CAST(y AS JSON) FROM t")
    before = node.sql()
    DIALECT.render(node)
    assert node.sql() == before


# ....................... #
# The rewrites. Each is here because the PostgreSQL spelling is either rejected
# by Redshift or read differently by it — which is why S-0015/D-1 forbids
# inheriting them.


def test_a_neutral_variant_cast_becomes_json_parse() -> None:
    """`variant` is `SUPER` and its *neutral* type is `JSON`, and SQLGlot's
    redshift generator renders `CAST(x AS JSON)` as a **no-op** — the cast
    disappears and the value stays whatever it was, usually `VARCHAR`.
    `JSON_PARSE` is Redshift's text-to-`SUPER` constructor (S-0015/D-4).
    """
    assert _rendered("coalesce", "{}", input_type=VariantType()) == (
        "COALESCE(x, JSON_PARSE('{}'))"
    )


def test_a_try_cast_to_variant_keeps_its_null_on_failure_meaning() -> None:
    """`TryCast` is a `Cast` subclass, so a rewrite that reads `isinstance(node,
    exp.Cast)` and stops there catches both — and a bare `JSON_PARSE` *raises*
    on malformed input where the quality system needs NULL.

    The `coercible` rule's failure marker is "the cast produced NULL", so a cast
    that cannot produce one can never fire it: the malformed row aborts the run
    instead of being quarantined, which is the degradation the port's own
    `TRY_CAST` declaration says it does not make. `CAN_JSON_PARSE` accepts
    exactly what `JSON_PARSE` accepts — `pg_input_is_valid`'s argument reached
    from the other side.
    """
    node = parse_one("SELECT TRY_CAST(x AS JSON) AS v")
    assert "CASE WHEN CAN_JSON_PARSE(x) THEN JSON_PARSE(x) END" in DIALECT.render(node)
    # The plain cast stays unguarded: nothing asked for a failure marker.
    assert "CAN_JSON_PARSE" not in DIALECT.render(parse_one("SELECT CAST(x AS JSON) AS v"))


def test_json_path_is_refused_rather_than_translated() -> None:
    """SQLGlot renders the neutral extraction as `JSON_EXTRACT_PATH_TEXT`, which
    Redshift defines and which returns **text** — so the transform would declare
    `variant` and produce a string. A translation that mostly works is what
    S-0015/D-4 refuses.
    """
    with pytest.raises(UnsupportedByTarget, match="no json_path lowering"):
        _rendered("json_path", "$.a")


def test_the_bronze_scalar_extraction_still_renders() -> None:
    # A bronze path lowers to `JSONExtractScalar`, is declared `string`, and
    # `JSON_EXTRACT_PATH_TEXT` over text returns text correctly. Refusing it
    # would refuse every mapping this port can emit.
    assert DIALECT.render(parse_one("payload ->> '$.a.b'")) == (
        "JSON_EXTRACT_PATH_TEXT(payload, 'a', 'b', TRUE)"
    )


def test_a_malformed_json_source_yields_null_rather_than_an_abort() -> None:
    """Redshift's `JSON_EXTRACT_PATH_TEXT` raises on a value that is not JSON,
    before any `TRY_CAST` around it runs, so one bad row would abort the load
    the quality system says to quarantine. Its `null_if_invalid` argument is
    the engine's own answer; a path with an index or a wildcard is left to the
    generator."""
    assert DIALECT.render(parse_one("payload ->> '$.a'")) == (
        "JSON_EXTRACT_PATH_TEXT(payload, 'a', TRUE)"
    )
    assert "TRUE" not in DIALECT.render(parse_one("payload ->> '$.items[0]'"))


def test_to_utc_is_one_convert_timezone_call() -> None:
    """Redshift's three-argument `CONVERT_TIMEZONE(source, target, ts)` reads a
    zoneless clock as being in `source` and returns a zoneless `TIMESTAMP`
    (S-0021).

    Deliberately not PostgreSQL's `AT TIME ZONE` chain: Redshift promotes
    through the *session* zone the way Trino does (S-0025/D-3), so the double
    application does not cancel.
    """
    assert _rendered("to_utc", "Europe/Paris") == "CONVERT_TIMEZONE('Europe/Paris', 'UTC', x)"


def test_utc_now_runs_on_the_compute_nodes_and_still_converts_a_zone() -> None:
    """`CURRENT_TIMESTAMP` is leader-node-only on Redshift, and the replay
    `INSERT … SELECT FROM silver.<entity>__reject` that stamps the clock reads
    a user table, so it must not appear. `GETDATE()` runs on the compute nodes
    but is zoneless in the session's zone; the cast to `TIMESTAMPTZ` attaches
    that same zone, so `CONVERT_TIMEZONE` has a real zone to convert from and
    the instant lands in UTC under any session (S-0045).
    """
    sql = DIALECT.render(DIALECT.utc_now())
    # A current-instant node the emit layer builds directly (the replay's
    # `resolved_at` stamps) gets the same spelling, not the generator's
    # session-zone `GETDATE()`.
    assert DIALECT.render(exp.CurrentTimestamp()) == sql
    assert sql == (
        "CAST(CONVERT_TIMEZONE('UTC', CAST(GETDATE() AS TIMESTAMP WITH TIME ZONE)) AS TIMESTAMP)"
    )
    assert "CURRENT_TIMESTAMP" not in sql


def test_the_calendar_series_becomes_a_cross_join_generator() -> None:
    """Redshift's `GENERATE_SERIES` takes integers only and is leader-node-only,
    so the calendar's neutral series cannot be the row source of a `dim_date`
    model. The port renders the engine's own idiom — a ten-row relation
    cross-joined once per decimal digit of the count, numbered and cut — with
    the count read from the literal bounds, inclusive at both ends."""
    node = sqlglot.parse_one(
        "SELECT CAST(date_day AS DATE) AS date_day FROM GENERATE_SERIES("
        "CAST('2020-01-01' AS DATE), CAST('2020-01-10' AS DATE), INTERVAL '1' DAY"
        ") AS date_day(date_day)"
    )
    sql = DIALECT.render(node)
    sqlglot.parse_one(sql, read="redshift")
    assert "GENERATE_SERIES" not in sql
    assert "DATEADD(DAY, n, CAST('2020-01-01' AS DATE)) AS date_day" in sql
    assert "ROW_NUMBER() OVER () - 1 AS n" in sql
    assert sql.count("UNION ALL") == 9  # ten rows, one relation: 10 >= 10 days
    assert "WHERE\n    n < 10" in sql or "WHERE n < 10" in sql
    assert sql.rstrip().endswith(") AS date_day")

    weekly = sqlglot.parse_one(
        "SELECT d FROM GENERATE_SERIES(CAST('2020-01-01' AS DATE), CAST('2020-03-01' AS DATE),"
        " INTERVAL '7' DAY) AS t(d)"
    )
    with pytest.raises(UnsupportedByTarget, match="one-day calendar"):
        DIALECT.render(weekly)


def test_json_object_is_redshifts_super_constructor() -> None:
    """Redshift has no `JSON_OBJECT`; SQLGlot inherits PostgreSQL's handling and
    renders the SQL-standard `JSON_OBJECT('k': v)`, which Redshift does not
    parse. `OBJECT` takes the same positional sequence and yields `SUPER`.
    """
    assert DIALECT.render(DIALECT.json_object([("a", exp.column("x"))])) == "OBJECT('a', x)"


def test_strip_prefix_uses_left_because_redshift_has_no_starts_with() -> None:
    """SQLGlot's redshift generator does supply one — `x LIKE p || '%'` — and it
    is wrong here: `LIKE` reads `%` and `_` in the prefix as wildcards, so a
    prefix containing either would match values it must not. `LEFT`/`LENGTH` is
    exact.
    """
    rendered = _rendered("strip_prefix", "sku-")
    assert "LEFT(x, LENGTH('sku-')) = 'sku-'" in rendered
    assert "LIKE" not in rendered


def test_strip_suffix_shares_the_postgres_helper() -> None:
    """`ends_with_as_right` is imported by name, which is what S-0015/D-1
    permits and S-0015/D-7 draws the line for: the *argument* for this spelling
    is engine-neutral, so the two ports agree here rather than one inheriting
    the other.
    """
    assert "RIGHT(x, LENGTH('-eu')) = '-eu'" in _rendered("strip_suffix", "-eu")


def test_parse_ts_with_a_format_is_cast_back_to_a_zoneless_timestamp() -> None:
    """Redshift's `TO_TIMESTAMP(text, text)` returns `TIMESTAMPTZ` having
    attached the session zone, as PostgreSQL's does — the same defect, so
    `zoneless_parse` is the second shared helper (S-0015/D-7).
    """
    assert _rendered("parse_ts", "%Y-%m-%d %H:%M:%S") == (
        "CAST(TO_TIMESTAMP(x, 'YYYY-MM-DD HH24:MI:SS') AS TIMESTAMP)"
    )
    assert _rendered("parse_date", "%d/%m/%Y") == "TO_DATE(x, 'DD/MM/YYYY')"


def test_regex_extract_expresses_the_group_as_a_match_parameter() -> None:
    """Redshift's `regexp_substr` is **not** PostgreSQL 15's: it takes
    `(source, pattern, position, occurrence, parameters)` and stops there, so
    the PostgreSQL sixth argument has no counterpart and SQLGlot's
    `REGEXP_SUBSTR(x, p, 1)` binds the `1` to *position* — the group silently
    gone. `'e'` extracts the pattern's first subexpression; `'c'` is plain
    case-sensitive matching.
    """
    assert _rendered("regex_extract", "sku-([0-9]+)", 1) == (
        "REGEXP_SUBSTR(x, 'sku-([0-9]+)', 1, 1, 'e')"
    )
    assert _rendered("regex_extract", "sku-[0-9]+", 0) == (
        "REGEXP_SUBSTR(x, 'sku-[0-9]+', 1, 1, 'c')"
    )


def test_a_group_that_is_not_a_literal_index_is_refused_by_name() -> None:
    """A recipe's raw `expr:` can hand the group as anything — a column, a
    string — and the canonical reparse binds it as the group without looking.
    The match parameter can only name the first subexpression, so a group the
    port cannot read at emit is refused as such, never a `ValueError`."""
    with pytest.raises(UnsupportedByTarget, match="literal capture-group index"):
        DIALECT.render(parse_one("REGEXP_EXTRACT(x, 'a(b)', n)"))
    with pytest.raises(UnsupportedByTarget, match="literal capture-group index"):
        DIALECT.render(parse_one("REGEXP_EXTRACT(x, 'a(b)', 'first')"))


def test_a_group_above_the_first_is_refused_not_approximated() -> None:
    # `'e'` reaches the first subexpression and Redshift can name no other, so
    # the whole match would be a wrong answer wearing a right shape.
    with pytest.raises(UnsupportedByTarget, match="capture group 2"):
        _rendered("regex_extract", "(a)-(b)", 2)


def test_the_iso_text_marker_is_stripped() -> None:
    """Redshift's datetime input takes the `T` separator, so the marker adds no
    rewrite on this port — what is left is the offset guard every port carries.
    A port that left the marker in place would emit `BLM_ISO_TEXT(x)`, which no
    engine defines (S-0044).
    """
    marked = exp.cast(
        exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("x")]),
        exp.DataType.build("TIMESTAMP"),
    )
    rendered = DIALECT.render(marked)
    assert "BLM_ISO_TEXT" not in rendered
    assert "LIKE '%+%'" in rendered


def test_no_postgres_only_spelling_survives_this_port() -> None:
    """The one assertion S-0015/D-1 is about: the PostgreSQL port's rewrites are
    audited, not inherited, so a shared AST that renders `PG_INPUT_IS_VALID` or
    `JSONB` on PostgreSQL must render neither here.
    """
    node = parse_one("SELECT TRY_CAST(x AS JSON) AS v, ENDS_WITH(y, 'z') AS e")
    postgres = PostgresDialect().render(node)
    redshift = DIALECT.render(node)
    assert "PG_INPUT_IS_VALID" in postgres and "JSONB" in postgres
    assert "PG_INPUT_IS_VALID" not in redshift
    assert "JSONB" not in redshift


# ....................... #
# The syntax floor.


@pytest.mark.parametrize(
    "fixture_name",
    ["ecom_basic", "minimal", "multi_source", "multi_source_quality", "role_playing_dates"],
)
def test_every_emitted_statement_reparses_under_the_dialect(fixture_name: str) -> None:
    """Rendered SQL is fed back to SQLGlot's redshift *parser*.

    A weak floor — it catches shape, not semantics, and a parser is not an
    engine — but the only offline one available to a port whose engine no tier
    runs: the surrogate lane is PostgreSQL (S-0015/D-2) and never reaches the
    `redshift-native` class at all (S-0015/D-3), so a construct like
    `JSON_PARSE` or `CONVERT_TIMEZONE` has nothing else standing behind it here.
    """
    statements = [
        (artifact.path, extract_select(artifact.content))
        for artifact in compile_fixture(fixture_name, dialect="redshift")
        if artifact.path.endswith(".sql")
    ]
    assert statements, f"{fixture_name} emitted no SQL to check"

    for path, sql in statements:
        # The SQLMesh envelope is a model DSL rather than SQL, so what is parsed
        # is the statement after it; the macros the engine expands at run time
        # are expanded here the way the execution tier expands them.
        assert sqlglot.parse(sql, read="redshift"), f"{fixture_name}/{path} parsed to nothing"
