"""The Databricks SQL dialect (S-0016): the physical type map, the declared
capabilities, and the rewrites this engine needs.

Every assertion here is about **rendered text**, which is all the port produces
(S-0016/D-1). What the engine does with that text is the live lane's claim and
never this tier's: SQLGlot is broader and more permissive than any warehouse,
so a green run here says the port's own rewrites are what they say they are and
nothing more.
"""

from __future__ import annotations

import pytest
import sqlglot
from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.dialects import DatabricksDialect, DialectFeature
from bloomery.errors import UnsupportedByTarget
from bloomery.transforms import DIVIDE_MARKER
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

pytestmark = pytest.mark.unit

DIALECT = DatabricksDialect()


@pytest.mark.parametrize(
    ("logical", "physical"),
    [
        (StringType(), "STRING"),
        (IntType(), "BIGINT"),
        (DecimalType(12, 4), "DECIMAL(12, 4)"),
        (DecimalType(38, 0), "DECIMAL(38, 0)"),  # the engine's maximum precision
        (BoolType(), "BOOLEAN"),
        (DateType(), "DATE"),
        # S-0016/D-8: `timestamp` is UTC and zoneless, and Databricks'
        # `TIMESTAMP` is an instant rendered through the session zone.
        (TimestampType(), "TIMESTAMP_NTZ"),
        # Databricks has no JSON type; the `:` accessor reads JSON out of a
        # STRING column, so `variant` is carried as one.
        (VariantType(), "STRING"),
    ],
)
def test_physical_type_for_every_logical_type(logical: LogicalType, physical: str) -> None:
    assert DIALECT.physical_type(logical) == physical


def test_a_decimal_wider_than_the_engine_is_refused() -> None:
    """Databricks caps `DECIMAL` at precision 38.

    Refusing at compile time is the S-0025/D-3 answer: the alternatives are a
    `CREATE TABLE` the warehouse rejects on the first run, or a value silently
    rounded — a declared type the engine cannot hold is not a caveat.
    """
    with pytest.raises(UnsupportedByTarget, match="capped at 38"):
        DIALECT.physical_type(DecimalType(40, 2))


def test_render_is_the_databricks_generator() -> None:
    assert DIALECT.name == "databricks"
    assert DIALECT.sqlglot_dialect == "databricks"


@pytest.mark.parametrize(
    "feature", [feature for feature in DialectFeature if feature is not DialectFeature.UNICODE_NORMALIZE]
)
def test_every_capability_but_normalization_is_declared(feature: DialectFeature) -> None:
    assert DIALECT.supports(feature)


def test_unicode_normalization_is_refused_rather_than_approximated() -> None:
    """Databricks has neither `NORMALIZE` nor DuckDB's `nfc_normalize`.

    SQLGlot renders the neutral node verbatim, so the untouched AST would emit
    a call the engine has never heard of — the D83 shape, renders everywhere
    and is defined somewhere else. The capability flag is the answer a rewrite
    cannot give: a `normalize` rule refuses at emit instead (S-0025/D-3).
    """
    assert not DIALECT.supports(DialectFeature.UNICODE_NORMALIZE)
    assert "NORMALIZE" in exp.Normalize(
        this=exp.column("x"), form=exp.var("NFC")
    ).sql(dialect="databricks")


def test_arrays_are_first_class_so_quality_flags_stay_arrays() -> None:
    # S-0033/D-9: without this the flag columns lower to a comma-delimited
    # string, which changes the emitted artifacts and the reject table's shape.
    assert DIALECT.supports(DialectFeature.ARRAY)
    flags = exp.cast(exp.Array(expressions=[]), exp.DataType.build("TEXT[]"))
    assert DIALECT.render(flags) == "CAST(ARRAY() AS ARRAY<STRING>)"


def test_try_cast_survives_as_a_null_on_failure_cast() -> None:
    """The quality layer's coercion marker needs a cast that yields NULL rather
    than raising, and under the ANSI mode D-8's type choice pins on, a plain
    `CAST` raises. SQLGlot renders the neutral node as Databricks' own
    `TRY_CAST`, so the port adds nothing but the type rewrite.
    """
    node = exp.TryCast(this=exp.column("x"), to=exp.DataType.build("TIMESTAMP"))
    assert DIALECT.render(node) == "TRY_CAST(x AS TIMESTAMP_NTZ)"


def test_a_neutral_timestamp_cast_becomes_ntz() -> None:
    """The type map applied *inside* expressions (S-0016/D-8).

    A `timestamp` column is `TIMESTAMP_NTZ`, so a cast in the expression that
    fills it has to say the same thing. Left neutral it would build an instant
    and store a wall clock — the zone defect S-0045 removed from the three
    shipped ports, wearing the right column type.
    """
    node = exp.select(exp.alias_(exp.cast(exp.column("x"), exp.DataType.build("TIMESTAMP")), "t"))
    assert "CAST(x AS TIMESTAMP_NTZ)" in DIALECT.render(node)


def test_a_neutral_variant_cast_becomes_a_string() -> None:
    node = exp.cast(exp.column("payload"), exp.DataType.build("JSON"))
    assert DIALECT.render(node) == "CAST(payload AS STRING)"


def test_render_lowers_neutral_json_extraction_to_the_colon_accessor() -> None:
    node = sqlglot.parse_one("JSON_EXTRACT(payload, '$.a.b')")
    assert DIALECT.render(node) == "payload:a.b"


def test_render_quotes_reserved_relation_names() -> None:
    """`order` is a reserved word here and SQLGlot's databricks generator
    carries no reserved-word set at all, so the bare rendering does not parse
    on a warehouse with ANSI mode on — which is the default, and which D-8's
    type choice pins the surrogate to.
    """
    node = exp.Select().select("x").from_(exp.table_("order", db="silver"))
    assert DIALECT.render(node) == "SELECT\n  x\nFROM silver.`order`"


def test_zone_interpretation_uses_to_utc_timestamp_not_the_generators_default() -> None:
    """`to_utc` means *interpret this zoneless timestamp as being in zone*
    (S-0021) — the only door into the always-UTC `timestamp` type.

    SQLGlot lowers the neutral `AtTimeZone` on this dialect to
    `FROM_UTC_TIMESTAMP`, which is the **other direction**: it reads the value
    as UTC and renders it in the named zone. Left alone, every interpreted
    instant would be wrong by twice the offset with nothing to say so — the
    Trino finding (S-0045), in a dialect whose default is worse.
    """
    node = exp.AtTimeZone(
        this=exp.cast(exp.column("x"), exp.DataType.build("TIMESTAMP")),
        zone=exp.Literal.string("Europe/Paris"),
    )
    assert DIALECT.render(node) == (
        "CAST(TO_UTC_TIMESTAMP(CAST(x AS TIMESTAMP_NTZ), 'Europe/Paris') AS TIMESTAMP_NTZ)"
    )


def test_several_zone_interpretations_in_one_tree_are_all_rewritten() -> None:
    node = exp.select(
        exp.alias_(
            exp.AtTimeZone(this=exp.column("a"), zone=exp.Literal.string("Europe/Berlin")), "a"
        ),
        exp.alias_(
            exp.AtTimeZone(this=exp.column("b"), zone=exp.Literal.string("Asia/Kolkata")), "b"
        ),
    )
    rendered = DIALECT.render(node)
    assert rendered.count("TO_UTC_TIMESTAMP") == 2
    assert "FROM_UTC_TIMESTAMP" not in rendered


@pytest.mark.parametrize("nested", [False, True])
def test_rendering_does_not_mutate_the_input(nested: bool) -> None:
    """The port contract shares one neutral AST across every dialect, so a
    rewrite that edited in place would leave the next dialect rendering this
    one's spelling. The in-place branch is the *nested* one, since a root node
    is replaced by rebinding a local.
    """
    interpretation = exp.AtTimeZone(this=exp.column("x"), zone=exp.Literal.string("Europe/Paris"))
    node: Expression = exp.select(exp.alias_(interpretation, "t")) if nested else interpretation
    before = node.sql()
    DIALECT.render(node)
    assert node.sql() == before
    assert "AT TIME ZONE" in node.sql(dialect="duckdb")


def test_utc_now_states_the_zone_rather_than_inheriting_it() -> None:
    """Databricks has no `timezone(zone, ts)`, the base spelling's function.

    `CURRENT_TIMESTAMP()` is an instant, so its wall clock is the session's;
    naming that same zone as the one to interpret it in turns the session's
    clock into UTC's, and the cast keeps the clock rather than the instant. The
    session zone appears on both sides and cancels — which is what makes the
    value the same under every session (S-0045).
    """
    assert DIALECT.render(DIALECT.utc_now()) == (
        "CAST(TO_UTC_TIMESTAMP(CURRENT_TIMESTAMP(), CURRENT_TIMEZONE()) AS TIMESTAMP_NTZ)"
    )
    # Not the ports' zone door, which is for a zoneless local value being told
    # which clock it came off; this value already has one.
    assert "AT TIME ZONE" not in DIALECT.render(DIALECT.utc_now())


def test_text_sha256_needs_no_rewrite_here() -> None:
    """`sha2(expr, 256)` takes a string and returns the lowercase hex digest
    directly, so this port inherits the base construction — unlike Trino, whose
    `sha256` takes and returns varbinary, and Postgres, whose returns bytea.

    A rewrite point an engine needs nothing for is answered by nothing at all,
    and asserting that is how the *absence* of `TO_HEX`/`TO_UTF8` here stays a
    finding rather than an oversight.
    """
    rendered = DIALECT.render(DIALECT.text_sha256(exp.column("canon")))
    assert rendered == "SHA2(canon, 256)"


def test_json_object_is_a_serialized_named_struct() -> None:
    """Databricks has `json_object` in neither the positional form DuckDB and
    Postgres take nor the `KEY … VALUE` form Trino takes (S-0033/D-83)."""
    pairs = [("k", exp.column("v")), ("n", exp.Literal.number(1))]
    assert DIALECT.render(DIALECT.json_object(pairs)) == "TO_JSON(NAMED_STRUCT('k', v, 'n', 1))"


def _iso_cast(to: str = "TIMESTAMP") -> Expression:
    """What `{parse_ts: ISO8601}` lowers to: a cast over a marked operand."""
    return exp.cast(
        exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("x")]),
        exp.DataType.build(to),
    )


@pytest.mark.parametrize(("to", "expected"), [("TIMESTAMP", "TIMESTAMP_NTZ"), ("DATE", "DATE")])
def test_the_iso_text_marker_becomes_a_separator_rewrite(to: str, expected: str) -> None:
    """ISO 8601 permits `T`, `t` and the space form; this engine's parser takes
    the first and the last. Under the ANSI mode D-8's type choice pins, the
    lowercase spelling is a raised error rather than a NULL — so the rewrite is
    the difference between a value quarantined and a run stopped, on text the
    other three ports read.

    The offset guard rides with it (S-0052/D-3): it lives in `strip_iso_text`,
    so a port inherits it by calling the function every port must call, and its
    window is taken over an explicit cast because the marker also sits on a
    bronze column whose type is whatever the project landed.
    """
    assert DIALECT.render(_iso_cast(to)) == (
        "CAST(CASE\n"
        "  WHEN SUBSTRING(CAST(x AS STRING), 11) LIKE '%+%'\n"
        "  OR SUBSTRING(CAST(x AS STRING), 11) LIKE '%-%'\n"
        "  THEN NULL\n"
        "  ELSE REPLACE(REPLACE(CAST(x AS STRING), 'T', ' '), 't', ' ')\n"
        f"END AS {expected})"
    )


def test_the_marker_is_rewritten_inside_a_try_cast() -> None:
    """The shape a quality-carrying entity actually emits: the marker wraps the
    *operand*, so the `Cast → TryCast` rewrite still reaches the cast and this
    port's rewrite still reaches the text.
    """
    node = exp.TryCast(
        this=exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("created_at")]),
        to=exp.DataType.build("TIMESTAMP"),
    )
    rendered = DIALECT.render(node)
    assert rendered.startswith("TRY_CAST(CASE")
    assert rendered.endswith("END AS TIMESTAMP_NTZ)")


@pytest.mark.parametrize(
    ("group", "expected"),
    [(None, 0), (1, 1), (2, 2)],
)
def test_the_capture_index_is_always_stated(group: int | None, expected: int) -> None:
    """Two independent defects, either of which alone would need this.

    SQLGlot's databricks generator **drops** the capture index, exactly as its
    duckdb and trino generators did before S-0045/D-5 — and the index does not
    survive the canonical round trip as a `group` in the first place: it
    re-parses bound to `position`, which is why `capture_group` runs before
    this rewrite rather than after. And this engine's default index is **1**
    where DuckDB's and Trino's is 0, so an omitted argument means something
    different here; stating it is the only spelling that means one thing on
    all four ports.
    """
    text = "REGEXP_EXTRACT(sku, 'sku-([0-9]+)')" if group is None else (
        f"REGEXP_EXTRACT(sku, 'sku-([0-9]+)', {group})"
    )
    assert DIALECT.render(sqlglot.parse_one(text)) == (
        f"REGEXP_EXTRACT(sku, 'sku-([0-9]+)', {expected})"
    )


def test_a_formatted_parse_keeps_the_written_wall_clock() -> None:
    """`parse_ts` with a format parses a *local wall clock*, and `to_utc` is
    the only door into the always-UTC type.

    Databricks' `to_timestamp` returns a `TIMESTAMP` — the parsed clock with
    the **session** zone attached — so the same row would store a different
    instant depending on who ran it, the defect S-0046 measured on
    PostgreSQL's `to_timestamp`. The cast back to `TIMESTAMP_NTZ` takes the
    session-zone wall clock, which is the clock that was just attached to, so
    the two cancel.
    """
    node = exp.StrToTime(this=exp.column("x"), format=exp.Literal.string("%Y-%m-%d"))
    assert DIALECT.render(node) == "CAST(TO_TIMESTAMP(x, 'yyyy-MM-dd') AS TIMESTAMP_NTZ)"


def test_exact_division_is_not_widened_to_a_float() -> None:
    """The `divide` marker means "keep this exact" (S-0046/D-3). On Postgres
    and Trino the base rewrite exists to *suppress* a double cast SQLGlot would
    otherwise add; here the generator adds none and Databricks' `/` over two
    decimals is already decimal, so the marker costs this port nothing.
    """
    marked = exp.Anonymous(this=DIVIDE_MARKER, expressions=[exp.column("a"), exp.column("b")])
    assert DIALECT.render(marked) == "a / b"


@pytest.mark.parametrize("unit", ["DAY", "WEEK", "MONTH", "QUARTER", "YEAR"])
def test_date_truncation_stays_date_trunc_rather_than_becoming_trunc(unit: str) -> None:
    """Every bucket a mart builds renders as `DATE_TRUNC(unit, x)`.

    SQLGlot's databricks generator lowers the neutral call to `TRUNC(x, unit)`,
    which takes no unit finer than a week and returns NULL for the rest — so
    `ordered_day`, both the incremental time column and the partition key,
    would be empty with nothing saying so. The three shipped ports render
    `DATE_TRUNC`, and so does this one.
    """
    node = sqlglot.parse_one(f"CAST(DATE_TRUNC('{unit}', order_date) AS DATE)")
    assert DIALECT.render(node) == f"CAST(DATE_TRUNC('{unit}', order_date) AS DATE)"


def test_a_truncated_timestamp_keeps_the_zoneless_type() -> None:
    """The truncation rewrite leaves the operand's own rewrites alone: the cast
    inside it is still `TIMESTAMP_NTZ`, not the instant `TIMESTAMP`.
    """
    node = exp.TimestampTrunc(
        this=exp.cast(exp.column("x"), exp.DataType.build("TIMESTAMP")),
        unit=exp.var("HOUR"),
    )
    assert DIALECT.render(node) == "DATE_TRUNC('HOUR', CAST(x AS TIMESTAMP_NTZ))"


@pytest.mark.parametrize(
    "node",
    [
        _iso_cast(),
        exp.TryCast(this=exp.column("x"), to=exp.DataType.build("TIMESTAMP")),
        exp.AtTimeZone(this=exp.column("x"), zone=exp.Literal.string("Europe/Paris")),
        exp.StrToTime(this=exp.column("x"), format=exp.Literal.string("%Y-%m-%d")),
        exp.Select().select("x").from_(exp.table_("order", db="silver")),
        exp.cast(exp.Array(expressions=[]), exp.DataType.build("TEXT[]")),
        sqlglot.parse_one("CAST(DATE_TRUNC('DAY', order_date) AS DATE)"),
    ],
    ids=[
        "iso_parse",
        "try_cast",
        "zone_interpretation",
        "formatted_parse",
        "reserved",
        "array",
        "date_trunc",
    ],
)
def test_every_rewrite_re_parses_under_this_dialect(node: Expression) -> None:
    """The generated SQL goes back through the SQL-generation library as
    Databricks SQL, and re-rendering what comes back is a fixed point.

    This is a syntax claim and deliberately only that: SQLGlot is broader and
    more permissive than any live warehouse, so it catches a spelling that is
    not Databricks SQL *shaped* — an unbalanced rewrite, a function name the
    parser reads as something else, a type that does not survive the round
    trip — and cannot catch a function the engine lacks. What the warehouse
    does with this text is the live lane's claim (S-0016).

    The fixed point is taken from the *first* re-parse rather than against the
    port's output, because SQLGlot makes one coercion of its own explicit:
    `TO_UTC_TIMESTAMP(x, …)` comes back with its operand cast. That is the
    library restating a conversion, not the port's text changing meaning, and
    asserting stability from there still fails on every spelling it cannot
    read back.
    """
    rendered = DIALECT.render(node)
    once = sqlglot.parse_one(rendered, read="databricks").sql(dialect="databricks", pretty=True)
    twice = sqlglot.parse_one(once, read="databricks").sql(dialect="databricks", pretty=True)
    assert twice == once
    assert once.split("(")[0] == rendered.split("(")[0]


def test_regexp_extract_re_parses_with_its_index_intact() -> None:
    """The re-parse assertion above cannot be made for this one, and the reason
    is the defect itself: `REGEXP_EXTRACT(x, p, 1)` re-parses with the index
    bound to `position`, which the generator then drops. So the round trip is
    asserted through the port, which is where the repair lives.
    """
    rendered = DIALECT.render(sqlglot.parse_one("REGEXP_EXTRACT(sku, 'p', 1)"))
    assert DIALECT.render(sqlglot.parse_one(rendered, read="databricks")) == rendered
    assert rendered.endswith(", 1)")


def test_date_series_keeps_its_table_alias_outside_the_call() -> None:
    """`dim_date`'s calendar renders as an aliased table function, not as a
    two-argument `explode`.

    Left to SQLGlot the alias folds into the call — `EXPLODE(SEQUENCE(...),
    _u(date_day))` — naming an `explode` arity Databricks does not have, and
    losing the `date_day` column name the three shipped ports resolve.
    """
    rendered = DIALECT.render(
        sqlglot.parse_one(
            "SELECT date_day FROM GENERATE_SERIES("
            "CAST('2020-01-01' AS DATE), CAST('2030-12-31' AS DATE), INTERVAL '1' DAY"
            ") AS date_day(date_day)"
        )
    )
    assert "FROM EXPLODE(" in rendered
    assert "SEQUENCE(CAST('2020-01-01' AS DATE), CAST('2030-12-31' AS DATE), INTERVAL '1' DAY)" in (
        rendered
    )
    assert rendered.endswith(") AS date_day(date_day)")
    assert DIALECT.render(sqlglot.parse_one(rendered, read="databricks")) == rendered
