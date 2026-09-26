"""The BigQuery dialect (S-0014): physical types for all seven logical types,
the rewrites this port decides rather than inherits, its declared capabilities,
and the rung-3 sanity that every rendered statement re-parses under SQLGlot's
``bigquery`` reader.

Every assertion here is rung 1–3 — SQLGlot's generator and reader, not the
engine. Nothing in this module is evidence about BigQuery itself; the dry-run
lane is what answers for that (S-0014/the-authoritative-layers).
"""

from __future__ import annotations

import pytest
from sqlglot import exp, parse_one
from sqlglot.expressions.core import Expression

from bloomery.dialects import BigQueryDialect, DialectFeature, get_dialect
from bloomery.errors import UnsupportedByTarget
from bloomery.quality.pattern import PATTERN_TARGET_DIALECTS
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

DIALECT = BigQueryDialect()


@pytest.mark.parametrize(
    ("logical", "physical"),
    [
        (StringType(), "STRING"),
        (IntType(), "INT64"),
        (BoolType(), "BOOL"),
        (DateType(), "DATE"),
        (TimestampType(), "DATETIME"),
        (VariantType(), "JSON"),
        (DecimalType(12, 4), "NUMERIC(12, 4)"),
    ],
)
def test_physical_type_for_every_logical_type(logical: LogicalType, physical: str) -> None:
    assert DIALECT.physical_type(logical) == physical


def test_the_port_is_registered_under_its_own_name() -> None:
    assert DIALECT.name == "bigquery"
    assert DIALECT.sqlglot_dialect == "bigquery"
    assert isinstance(get_dialect("bigquery"), BigQueryDialect)


def test_a_pattern_rule_is_checked_against_this_port_too() -> None:
    """A shipped port belongs in the checked set, or a project carrying a
    regex BigQuery cannot transport compiles for the other three and refuses
    only on the day somebody targets this one (S-0033/D-56)."""
    assert "bigquery" in PATTERN_TARGET_DIALECTS


# ----------------------- #
# S-0014/D-1 — DATETIME, not TIMESTAMP


def test_a_bloomery_timestamp_is_a_datetime() -> None:
    """The locked choice, at the type layer (S-0014/D-1).

    bloomery's ``timestamp`` is a zoneless UTC wall clock
    (S-0021/logical-types-bloomery-typing-types-py). BigQuery's ``DATETIME`` is a wall clock with no
    instant and its ``TIMESTAMP`` is an instant with no zone of its own,
    rendered and compared through the *session's* zone — so a ``TIMESTAMP``
    mapping would make ``DATE(ts)`` and every bucket derived from it depend on
    the reader, which is the defect S-0045 measured on the other three ports
    arriving through the type instead of through the conversion.
    """
    assert DIALECT.physical_type(TimestampType()) == "DATETIME"
    assert DIALECT.render(exp.cast(exp.column("x"), exp.DataType.build("TIMESTAMP"))) == (
        "CAST(x AS DATETIME)"
    )


def test_zone_interpretation_converts_to_utc_before_dropping_the_zone() -> None:
    """``to_utc`` means *interpret this zoneless wall clock as being in zone*,
    and it is the only door into the always-UTC ``timestamp`` type (S-0045).

    GoogleSQL spells the two halves as two conversions in this order:
    ``TIMESTAMP(<datetime>, <zone>)`` reads the wall clock in that zone and
    yields the instant, then ``DATETIME(<timestamp>, 'UTC')`` reads the instant
    back off the UTC clock. SQLGlot's own rendering of ``AtTimeZone`` nests the
    same two functions the other way round — ``TIMESTAMP(DATETIME(x, zone))``
    — which converts *from* UTC and so moves the value by the offset in the
    wrong direction.
    """
    node = exp.AtTimeZone(
        this=exp.cast(exp.column("x"), exp.DataType.build("TIMESTAMP")),
        zone=exp.Literal.string("Europe/Paris"),
    )
    assert DIALECT.render(node) == "DATETIME(TIMESTAMP(CAST(x AS DATETIME), 'Europe/Paris'), 'UTC')"


def test_a_nested_zone_interpretation_is_rewritten_too() -> None:
    """The shape a mapping actually produces: the interpretation is a *column*
    of a SELECT, never the root node the unit above hands it."""
    node = exp.select(
        exp.alias_(
            exp.AtTimeZone(
                this=exp.cast(exp.column("placed_at"), exp.DataType.build("TIMESTAMP")),
                zone=exp.Literal.string("Europe/Berlin"),
            ),
            "ordered_at",
        )
    ).from_("bronze.woo")
    rendered = DIALECT.render(node)
    assert "DATETIME(TIMESTAMP(CAST(placed_at AS DATETIME), 'Europe/Berlin'), 'UTC')" in rendered
    assert "AT TIME ZONE" not in rendered


@pytest.mark.parametrize("nested", [False, True])
def test_rendering_a_zone_interpretation_does_not_mutate_the_input(nested: bool) -> None:
    """The port contract shares one neutral AST across every dialect, so a
    rewrite that edited in place would leave the next dialect rendering
    BigQuery's spelling. The in-place branch is the *nested* one, since a root
    node is replaced by rebinding a local."""
    interpretation = exp.AtTimeZone(this=exp.column("x"), zone=exp.Literal.string("Europe/Paris"))
    node: Expression = exp.select(exp.alias_(interpretation, "t")) if nested else interpretation
    before = node.sql()
    DIALECT.render(node)
    assert node.sql() == before
    assert "AT TIME ZONE" in before
    assert "AT TIME ZONE" in node.sql(dialect="duckdb")


def test_utc_now_states_the_zone_rather_than_reading_the_session() -> None:
    """A bare ``CURRENT_DATETIME()`` reads off the session's clock, so two rows
    written at one instant by two readers in two zones land in different days
    (S-0045). BigQuery has no ``timezone(zone, ts)`` for the base spelling to
    reach, and its zoned ``CURRENT_DATETIME`` returns exactly what ``timestamp``
    is: a zoneless wall clock already on UTC."""
    assert DIALECT.render(DIALECT.utc_now()) == "CURRENT_DATETIME('UTC')"
    # A current-instant node the emit layer builds directly (the replay's
    # `resolved_at` stamps) takes the same spelling: `CURRENT_TIMESTAMP()` is
    # an instant GoogleSQL will not assign to a `DATETIME` column.
    assert DIALECT.render(exp.CurrentTimestamp()) == "CURRENT_DATETIME('UTC')"


def test_the_zoneless_utc_invariant_survives_a_full_projection() -> None:
    """The case this port can be wrong about while everything else is green
    (S-0014/risks), so it gets its own fixture rather than riding on one that
    happens to exercise it.

    Two mappings read two shops' local wall clocks in two zones, and a third
    column derives a date from one of them. The invariant is that *neither*
    value keeps its own zone into the stored column and that the derived date
    is taken off the UTC clock — so nothing downstream can read a display rule
    where it meant to read an instant.
    """
    node = exp.select(
        exp.alias_(
            exp.AtTimeZone(
                this=exp.cast(exp.column("berlin_local"), exp.DataType.build("TIMESTAMP")),
                zone=exp.Literal.string("Europe/Berlin"),
            ),
            "placed_at",
        ),
        exp.alias_(
            exp.AtTimeZone(
                this=exp.cast(exp.column("kolkata_local"), exp.DataType.build("TIMESTAMP")),
                zone=exp.Literal.string("Asia/Kolkata"),
            ),
            "shipped_at",
        ),
    ).from_("bronze.orders")
    rendered = DIALECT.render(node)

    # Both interpretations end on the UTC clock, and neither keeps its own zone.
    assert rendered.count("'UTC')") == 2
    assert rendered.count("DATETIME(TIMESTAMP(") == 2
    # Never the zone-aware type, and never the neutral spelling BigQuery reads
    # in the other direction.
    assert "AT TIME ZONE" not in rendered
    assert "TIMESTAMP_TRUNC" not in rendered
    for zone in ("'Europe/Berlin'", "'Asia/Kolkata'"):
        # the zone names the *source* clock only — it never survives as the
        # column's own display rule
        assert rendered.count(zone) == 1


# ----------------------- #
# S-0014/D-2 — the safe cast


def _iso_cast(to: str = "TIMESTAMP") -> Expression:
    """What ``{parse_ts: ISO8601}`` lowers to: a cast over a marked operand."""
    return exp.cast(
        exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("x")]),
        exp.DataType.build(to),
    )


def test_a_try_cast_is_a_safe_cast() -> None:
    """The locked NULL-on-failure contract the coercion lowering depends on
    (S-0014/D-2). ``SAFE_CAST`` is GoogleSQL's cast that yields NULL rather
    than aborting the run, which is what lets ``coercible`` see the bad value
    and the row reach quarantine."""
    node = exp.TryCast(this=exp.column("x"), to=exp.DataType.build("BIGINT"))
    assert DIALECT.render(node) == "SAFE_CAST(x AS INT64)"


def test_the_safe_cast_survives_the_cast_to_try_cast_rewrite() -> None:
    """The shape a quality-carrying entity actually emits: the ISO marker
    wraps the *operand*, so the ``Cast → TryCast`` rewrite still reaches the
    cast and this port's separator rewrite still reaches the text.

    A port that lost the safe cast here would turn the entity back into
    produce-or-raise on this engine alone — the bad value aborting the run
    instead of becoming the NULL ``coercible`` is looking for (S-0014/D-2).
    """
    node = exp.TryCast(
        this=exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("created_at")]),
        to=exp.DataType.build("TIMESTAMP"),
    )
    assert DIALECT.render(node) == (
        "SAFE_CAST(CASE\n"
        "  WHEN SUBSTR(CAST(created_at AS STRING), 11) LIKE '%+%'\n"
        "  OR SUBSTR(CAST(created_at AS STRING), 11) LIKE '%-%'\n"
        "  THEN NULL\n"
        "  ELSE RTRIM(REPLACE(REPLACE(CAST(created_at AS STRING), 'T', ' '), 't', ' '), 'Zz')\n"
        "END AS DATETIME)"
    )


def test_the_declared_try_cast_capability_matches_the_rendering() -> None:
    assert DIALECT.supports(DialectFeature.TRY_CAST)


# ----------------------- #
# ISO parsing and the offset guard


@pytest.mark.parametrize(("to", "expected"), [("TIMESTAMP", "DATETIME"), ("DATE", "DATE")])
def test_the_iso_text_marker_becomes_a_separator_rewrite(to: str, expected: str) -> None:
    """GoogleSQL's ``DATETIME`` literal grammar takes the space form on every
    documented spelling, where the ``T`` and lowercase ``t`` forms are where
    engines have already been measured to disagree (S-0044, S-0052). This port
    takes the spelling that needs no engine to be asked; the rewrite is a no-op
    on text that never carried a separator."""
    assert DIALECT.render(_iso_cast(to)) == (
        "CAST(CASE\n"
        "  WHEN SUBSTR(CAST(x AS STRING), 11) LIKE '%+%'\n"
        "  OR SUBSTR(CAST(x AS STRING), 11) LIKE '%-%'\n"
        "  THEN NULL\n"
        "  ELSE RTRIM(REPLACE(REPLACE(CAST(x AS STRING), 'T', ' '), 't', ' '), 'Zz')\n"
        f"END AS {expected})"
    )


def test_a_trailing_zulu_marker_is_dropped_before_the_datetime_cast() -> None:
    """The offset guard lets `Z` through because every other port's cast reads
    it as the UTC it is; GoogleSQL's `DATETIME` cast parses no zone marker, so
    a valid UTC value ending in `Z` cast to NULL and was quarantined as a
    coercion failure. `Z` is UTC and the column stores the UTC wall clock
    (S-0014/D-1), so the marker is trimmed and no value changes."""
    rendered = DIALECT.render(_iso_cast())
    assert "RTRIM(" in rendered and "'Zz')" in rendered


def test_a_cast_past_numerics_bounds_targets_bignumeric() -> None:
    """SQLGlot drops a decimal cast's parameters here and renders `NUMERIC`,
    so `to_decimal(30, 0)` became `SAFE_CAST(x AS NUMERIC)` while the column
    it feeds is `BIGNUMERIC(30, 0)` (S-0014/D-7): a valid 30-digit value came
    back NULL and was quarantined. The cast's target now follows the column's
    placement; a declaration `NUMERIC` holds keeps the recorded spelling."""
    wide = exp.TryCast(this=exp.column("x"), to=exp.DataType.build("DECIMAL(30, 0)"))
    assert DIALECT.render(wide) == "SAFE_CAST(x AS BIGNUMERIC)"
    deep = exp.cast(exp.column("x"), exp.DataType.build("DECIMAL(20, 12)"))
    assert DIALECT.render(deep) == "CAST(x AS BIGNUMERIC)"
    narrow = exp.TryCast(this=exp.column("x"), to=exp.DataType.build("DECIMAL(12, 4)"))
    assert "BIGNUMERIC" not in DIALECT.render(narrow)


def test_a_tuple_in_subquery_becomes_a_correlated_exists() -> None:
    """GoogleSQL's `IN` takes a single-column subquery, so the replay's
    resolution `UPDATE` — a row-value `IN` every other port accepts — failed
    before any reject row was marked resolved. The correlated `EXISTS` says
    the same thing; the update's target gets an alias so the outer columns the
    subquery's table also carries do not resolve to the inner ones."""
    update = parse_one(
        "UPDATE silver.order_line__reject SET resolved_at = CURRENT_TIMESTAMP() "
        "WHERE resolved_at IS NULL AND (source_relation, _source_row_id) IN "
        "(SELECT _target._source, _target._source_row_id FROM silver.order_line AS _target)"
    )
    rendered = DIALECT.render(update)
    assert " IN (" not in rendered
    assert "UPDATE silver.order_line__reject AS _row SET" in rendered
    assert "EXISTS(" in rendered or "EXISTS (" in rendered
    assert "_target._source = _row.source_relation" in rendered
    assert "_target._source_row_id = _row._source_row_id" in rendered
    assert "CURRENT_DATETIME('UTC')" in rendered


def test_both_iso_separators_are_normalized() -> None:
    rendered = DIALECT.render(_iso_cast())
    assert "'T', ' '" in rendered
    assert "'t', ' '" in rendered


def test_the_offset_guard_uses_googlesqls_own_substring_spelling() -> None:
    """``SUBSTR`` is GoogleSQL's name for the function and SQLGlot's bigquery
    generator emits the ANSI ``SUBSTRING``, which would leave the offset
    guard's window (S-0052/D-5) resting on an alias. Both re-parse, so no rung
    below the engine reports the difference — which is the reason to spell it
    the engine's way here rather than find out from a live lane."""
    rendered = DIALECT.render(_iso_cast())
    assert "SUBSTR(" in rendered
    assert "SUBSTRING(" not in rendered


def test_offset_bearing_text_is_still_refused_as_null() -> None:
    """The guard is inherited by calling ``strip_iso_text`` at all, so it lands
    on this port the way it lands on the other three (S-0052/D-3)."""
    rendered = DIALECT.render(_iso_cast())
    assert "LIKE '%+%'" in rendered
    assert "LIKE '%-%'" in rendered
    assert "THEN NULL" in rendered


# ----------------------- #
# S-0014/D-7 — the decimal mapping


@pytest.mark.parametrize(
    ("declared", "physical"),
    [
        # Inside NUMERIC: the common declarations, and both of its exact edges
        # — 29 integer digits and a scale of 9, which meet at decimal(38, 9).
        (DecimalType(12, 4), "NUMERIC(12, 4)"),
        (DecimalType(1, 0), "NUMERIC(1, 0)"),
        (DecimalType(38, 9), "NUMERIC(38, 9)"),
        (DecimalType(29, 0), "NUMERIC(29, 0)"),
        # Past one bound or the other, so BIGNUMERIC. A scale of 10 is inside
        # NUMERIC's integer digits and outside its scale; decimal(30, 0) and
        # decimal(38, 0) are the reverse, and are the cases that reading the
        # unparameterized precision maximum of 38 as an independent bound gets
        # wrong — NUMERIC(38, 0) asks a 29-integer-digit type for 38 of them.
        (DecimalType(38, 10), "BIGNUMERIC(38, 10)"),
        (DecimalType(30, 0), "BIGNUMERIC(30, 0)"),
        (DecimalType(38, 0), "BIGNUMERIC(38, 0)"),
        (DecimalType(39, 9), "BIGNUMERIC(39, 9)"),
        (DecimalType(76, 38), "BIGNUMERIC(76, 38)"),
    ],
)
def test_a_declared_decimal_lands_on_the_type_its_bounds_allow(
    declared: DecimalType, physical: str
) -> None:
    """S-0014/D-7, recorded with the bounds it was decided at: GoogleSQL bounds
    a *parameterized* decimal's precision relative to its scale, so
    ``NUMERIC(P, S)`` takes ``S`` in ``[0, 9]`` with ``P`` in
    ``[max(1, S), S + 29]``, and ``BIGNUMERIC(P, S)`` takes ``S`` in
    ``[0, 38]`` with ``P`` in ``[max(1, S), S + 38]``. What places a
    declaration is therefore its integer digits, ``P - S``, and not its
    precision on its own.

    The two are not interchangeable — ``BIGNUMERIC`` reaches further and costs
    more storage — so the narrower one is taken wherever the declaration fits
    it, and the wider one only where it does not.
    """
    assert DIALECT.physical_type(declared) == physical


@pytest.mark.parametrize("declared", [DecimalType(77, 38), DecimalType(76, 39)])
def test_a_decimal_past_both_bounds_is_refused_rather_than_widened(declared: DecimalType) -> None:
    """Silently widening would store a different type than the one declared,
    and silently narrowing would drop digits the author asked for. bloomery
    forbids floats in emission paths, so there is no third type to fall to."""
    with pytest.raises(UnsupportedByTarget, match="cannot express decimal"):
        DIALECT.physical_type(declared)


def test_the_refusal_names_both_bounds() -> None:
    with pytest.raises(UnsupportedByTarget) as excinfo:
        DIALECT.physical_type(DecimalType(90, 50))
    message = str(excinfo.value)
    assert "NUMERIC(P, S) holds scale <= 9 with at most 29 integer digits (P - S)" in message
    assert "BIGNUMERIC(P, S) holds scale <= 38 with at most 38" in message


def test_a_narrowing_cast_loses_its_scale_because_googlesql_has_no_other_form() -> None:
    """A recorded consequence rather than a defect: GoogleSQL does not accept a
    parameterized type in a ``CAST``, so the narrowing cast that bounds an
    exact division lands on ``NUMERIC``'s own scale of 9 rather than on the
    declared 4. The value stays exact and the *column* still carries the
    author's scale; there is no spelling of the cast that keeps it."""
    node = exp.cast(exp.column("x"), exp.DataType.build("DECIMAL(12, 4)"))
    assert DIALECT.render(node) == "CAST(x AS NUMERIC)"
    assert DIALECT.physical_type(DecimalType(12, 4)) == "NUMERIC(12, 4)"


# ----------------------- #
# The rest of the rewrite surface


def test_the_sha256_digest_is_lowercase_hex_text() -> None:
    """``SHA256`` returns ``BYTES`` on this engine, so the plain spelling gives
    ``reject_id`` the wrong type rather than the digest every engine has to
    agree on (S-0033/D-21)."""
    assert DIALECT.render(DIALECT.text_sha256(exp.column("canon"))) == "TO_HEX(SHA256(canon))"
    # Not the case-unspecified `exp.Hex`, whose bigquery rendering uppercases.
    assert "UPPER" not in DIALECT.render(DIALECT.text_sha256(exp.column("canon")))


def test_a_capture_group_other_than_one_is_refused() -> None:
    """GoogleSQL's ``REGEXP_EXTRACT`` takes no group argument: it returns the
    pattern's single capturing group, so group 1 is the only index it can be
    asked for. SQLGlot drops any other *silently* and renders the same SQL —
    which would answer ``{regex_extract: [pattern, 2]}`` with group 1 and call
    it a success."""
    node = parse_one("SELECT REGEXP_EXTRACT(x, 'p', 2)", dialect="duckdb")
    with pytest.raises(UnsupportedByTarget, match="capture group 2"):
        DIALECT.render(node)


def test_the_expressible_capture_group_renders() -> None:
    node = parse_one("SELECT REGEXP_EXTRACT(x, 'p', 1)", dialect="duckdb")
    assert "REGEXP_EXTRACT(x, 'p')" in DIALECT.render(node)


def test_reserved_relation_names_are_backtick_quoted() -> None:
    node = exp.Select().select("x").from_(exp.table_("order", db="silver"))
    assert DIALECT.render(node) == "SELECT\n  x\nFROM silver.`order`"


def test_a_transaction_is_opened_with_the_googlesql_spelling() -> None:
    """``BEGIN`` alone opens a *block* in GoogleSQL scripting, not a
    transaction, so the bare spelling would run the envelope's statements
    outside any transaction rather than fail loudly."""
    assert DIALECT.begin_transaction == "BEGIN TRANSACTION"


@pytest.mark.parametrize("feature", sorted(DialectFeature))
def test_every_capability_is_declared(feature: DialectFeature) -> None:
    """BigQuery has ``JSON``, ``ARRAY``, ``SAFE_CAST``, ``REGEXP_CONTAINS`` and
    ``REGEXP_EXTRACT``, ``NORMALIZE(x, NFC)``, positional ``JSON_OBJECT``,
    ``IS NOT DISTINCT FROM``, zone conversion, and a SHA-256 this port hexes —
    so the port claims every one rather than inheriting the claim silently."""
    assert DIALECT.supports(feature)


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        (
            exp.Normalize(this=exp.column("name"), form=exp.var("NFC")),
            "NORMALIZE(name, NFC)",
        ),
        (
            exp.JSONExtractScalar(
                this=exp.column("customer"), expression=exp.Literal.string("$.id")
            ),
            "JSON_EXTRACT_SCALAR(customer, '$.id')",
        ),
        (
            exp.NullSafeEQ(this=exp.column("a"), expression=exp.column("b")),
            "a IS NOT DISTINCT FROM b",
        ),
        (
            exp.RegexpLike(this=exp.column("sku"), expression=exp.Literal.string("^[A-Z]{3}$")),
            "REGEXP_CONTAINS(sku, '^[A-Z]{3}$')",
        ),
    ],
)
def test_the_declared_capabilities_have_a_googlesql_spelling(
    node: Expression, expected: str
) -> None:
    assert DIALECT.render(node) == expected


def test_the_positional_json_object_is_what_the_reject_table_gets() -> None:
    pairs = [("order_id", exp.column("order_id")), ("line_no", exp.column("line_no"))]
    assert DIALECT.render(DIALECT.json_object(pairs)) == (
        "JSON_OBJECT('order_id', order_id, 'line_no', line_no)"
    )


# ----------------------- #
# Rung 3 — every rendered statement re-parses under SQLGlot's bigquery reader


RENDERED_SURFACE: list[tuple[str, Expression]] = [
    ("iso_parse", _iso_cast()),
    ("iso_parse_date", _iso_cast("DATE")),
    (
        "coercible_parse",
        exp.TryCast(
            this=exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("created_at")]),
            to=exp.DataType.build("TIMESTAMP"),
        ),
    ),
    (
        "zone_interpretation",
        exp.AtTimeZone(
            this=exp.cast(exp.column("x"), exp.DataType.build("TIMESTAMP")),
            zone=exp.Literal.string("Europe/Berlin"),
        ),
    ),
    ("utc_now", DIALECT.utc_now()),
    ("reject_id", DIALECT.text_sha256(exp.column("canon"))),
    ("json_object", DIALECT.json_object([("k", exp.column("v"))])),
    ("normalize", exp.Normalize(this=exp.column("name"), form=exp.var("NFC"))),
    ("regexp_like", exp.RegexpLike(this=exp.column("sku"), expression=exp.Literal.string("^A$"))),
    ("null_safe_eq", exp.NullSafeEQ(this=exp.column("a"), expression=exp.column("b"))),
    ("regexp_extract", parse_one("SELECT REGEXP_EXTRACT(x, 'p', 1)", dialect="duckdb")),
    ("exact_division", parse_one("SELECT BLM_DIVIDE(a, b)", dialect="duckdb")),
    ("reserved_name", exp.Select().select("x").from_(exp.table_("order", db="silver"))),
]


@pytest.mark.parametrize(
    ("name", "node"), RENDERED_SURFACE, ids=[name for name, _ in RENDERED_SURFACE]
)
def test_every_rendered_construction_reparses_under_the_bigquery_reader(
    name: str, node: Expression
) -> None:
    """Rung 3, and the whole of what it proves: SQLGlot's bigquery *reader*
    accepts what its bigquery generator wrote. It is not evidence about
    BigQuery — a construction can round-trip here and still be refused by the
    service — which is why the dry-run lane exists above it.

    What it does catch is the failure mode a port rewrite introduces most
    easily: a hand-built call that renders as text nothing can parse back.
    """
    rendered = DIALECT.render(node)
    reparsed = parse_one(rendered, dialect="bigquery")
    assert reparsed is not None
    assert reparsed.sql(dialect="bigquery", pretty=True) == rendered
