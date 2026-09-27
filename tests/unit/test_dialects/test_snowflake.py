"""The Snowflake dialect (S-0013): the concrete type map, the six rewrite
points each answered from Snowflake rather than from a shipped port, and
syntax sanity — ``sqlglot.parse_one(rendered, read="snowflake")`` — on every
rendering this file makes.

Every assertion about rendered SQL goes through :func:`_rendered`, which parses
the result with Snowflake's own parser before returning it. That is the offline
rung's whole claim and the limit of it: a statement Snowflake's parser accepts
is not a statement Snowflake's binder accepts, which is what the `EXPLAIN USING
JSON` lane is for (S-0013/authoritative-layers).
"""

from __future__ import annotations

import sqlglot
import pytest
from sqlglot import exp
from sqlglot.expressions.core import Expression

from bloomery.dialects import DialectFeature, SnowflakeDialect, get_dialect
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

pytestmark = pytest.mark.unit

DIALECT = SnowflakeDialect()


def _rendered(node: Expression) -> str:
    """The port's rendering, after Snowflake's own parser has accepted it."""
    sql = DIALECT.render(node)
    sqlglot.parse_one(sql, read="snowflake")
    return sql


def test_the_port_is_registered_under_its_name() -> None:
    assert isinstance(get_dialect("snowflake"), SnowflakeDialect)
    assert DIALECT.name == "snowflake"
    assert DIALECT.sqlglot_dialect == "snowflake"


# ....................... #
# The concrete type map (S-0013/D-6), under D-1's constraint


@pytest.mark.parametrize(
    ("logical", "physical"),
    [
        (StringType(), "VARCHAR"),
        # Snowflake's BIGINT is a documented synonym for NUMBER(38, 0) rather
        # than a 64-bit integer, and `physical_type` is a one-way door once
        # artifacts exist (D6) — so it states the range it actually has.
        (IntType(), "NUMBER(38, 0)"),
        (DecimalType(12, 4), "DECIMAL(12, 4)"),
        (DecimalType(38, 0), "DECIMAL(38, 0)"),
        (BoolType(), "BOOLEAN"),
        (DateType(), "DATE"),
        # D1: zoneless, and never the session-dependent TIMESTAMP_LTZ. Nor
        # bare TIMESTAMP, which on this engine is an alias resolved through
        # TIMESTAMP_TYPE_MAPPING and may *be* TIMESTAMP_LTZ.
        (TimestampType(), "TIMESTAMP_NTZ"),
        # D6's open question, closed: Snowflake has no JSON type, and VARIANT
        # is what its own semi-structured functions take and return.
        (VariantType(), "VARIANT"),
    ],
)
def test_physical_type_for_every_logical_type(logical: LogicalType, physical: str) -> None:
    assert DIALECT.physical_type(logical) == physical


def test_a_decimal_past_snowflakes_precision_is_refused() -> None:
    """``NUMBER`` carries 38 digits and Snowflake has no wider fixed-point
    type, while the spec layer accepts any precision — so the bound has
    nowhere to live but the port. Refused at emit naming the bound, rather
    than rendered into DDL the engine rejects in its own words (S-0025/D-3).
    """
    with pytest.raises(UnsupportedByTarget, match="exceeds Snowflake's fixed-point precision"):
        DIALECT.physical_type(DecimalType(40, 2))


def test_no_rendering_reaches_for_the_session_zone_timestamp() -> None:
    """D1 is a ban on two spellings, not one.

    ``TIMESTAMP_LTZ`` renders against the reader's session zone. Bare
    ``TIMESTAMP`` is worse, because it *looks* decided: it is an alias
    resolved through the ``TIMESTAMP_TYPE_MAPPING`` parameter, which an
    account may point at ``TIMESTAMP_LTZ`` — so the emitted SQL would not
    change while the type underneath did.
    """
    sql = _rendered(exp.cast(exp.column("ts"), exp.DataType.build("TIMESTAMP")))
    assert sql == "CAST(ts AS TIMESTAMPNTZ)"  # SQLGlot's spelling of TIMESTAMP_NTZ
    assert "LTZ" not in sql
    assert DIALECT.physical_type(TimestampType()) != "TIMESTAMP_LTZ"


# ....................... #
# Rewrite point 1: the zone interpretation door into `timestamp`


def test_zone_interpretation_uses_the_three_argument_convert_timezone() -> None:
    """``to_utc`` means *interpret this zoneless timestamp as being in zone*
    (S-0021/logical-types-bloomery-typing-types-py) and must land zoneless UTC.

    Snowflake's three-argument ``CONVERT_TIMEZONE(<from>, <to>, <ts>)`` is
    exactly that: it reads a zoneless timestamp in the named zone and returns
    ``TIMESTAMP_NTZ`` in the target one — one call, no cast to drop a zone.

    SQLGlot renders :class:`sqlglot.exp.AtTimeZone` as the *two*-argument
    form, which is a different function: it expects an instant, promotes a
    zoneless operand with the **session** zone before converting, and returns
    a zone-aware ``TIMESTAMP_TZ``. Both halves are what S-0045/what-was-measured is about.
    """
    node = exp.AtTimeZone(
        this=exp.cast(exp.column("x"), exp.DataType.build("TIMESTAMP")),
        zone=exp.Literal.string("Europe/Berlin"),
    )
    assert _rendered(node) == "CONVERT_TIMEZONE('Europe/Berlin', 'UTC', CAST(x AS TIMESTAMPNTZ))"


def test_rendering_a_zone_interpretation_does_not_mutate_the_input() -> None:
    """The port contract shares one neutral AST across every dialect, so a
    rewrite that edited in place would leave the next port rendering this
    one's tree."""
    node = exp.select(
        exp.alias_(
            exp.AtTimeZone(
                this=exp.cast(exp.column("x"), exp.DataType.build("TIMESTAMP")),
                zone=exp.Literal.string("Europe/Berlin"),
            ),
            "n",
        )
    )
    before = node.sql()
    DIALECT.render(node)
    assert node.sql() == before


def test_utc_now_is_the_engines_own_utc_instant() -> None:
    """``SYSDATE()`` is documented as the system's current instant in UTC,
    typed ``TIMESTAMP_NTZ`` — zoneless UTC, which is what this method owes.

    The base spelling cannot be reached for: Snowflake has no
    ``timezone(zone, ts)``, and ``CURRENT_TIMESTAMP`` is ``TIMESTAMP_LTZ``, so
    casting it would keep the session's wall clock — the S-0045/what-was-measured defect
    in the shape of its fix.
    """
    sql = _rendered(DIALECT.utc_now())
    assert sql == "SYSDATE()"
    assert "CURRENT_TIMESTAMP" not in sql
    assert "AT TIME ZONE" not in sql


def test_a_current_instant_node_gets_the_utc_spelling_wherever_it_was_built() -> None:
    """D1 binds the rendering, not just the ``utc_now`` door.

    The replay statements stamp ``resolved_at`` and ``last_evaluated_at`` from
    a :class:`sqlglot.exp.CurrentTimestamp` the emit layer builds directly,
    never calling ``utc_now``. Rendered verbatim that is
    ``CURRENT_TIMESTAMP()`` — ``TIMESTAMP_LTZ`` — and assigning it into the
    ``TIMESTAMP_NTZ`` column this port declares converts it through the
    *session* zone, storing the writer's local wall clock under a zoneless
    type. So the port rewrites the node rather than trusting its callers.
    """
    assert _rendered(exp.CurrentTimestamp()) == "SYSDATE()"

    stamp = exp.Update(
        this=exp.table_("order_line__reject", db="silver"),
        expressions=[exp.EQ(this=exp.column("resolved_at"), expression=exp.CurrentTimestamp())],
    )
    sql = _rendered(stamp)
    assert sql == "UPDATE silver.order_line__reject SET resolved_at = SYSDATE()"
    assert "CURRENT_TIMESTAMP" not in sql


# ....................... #
# Rewrite point 2: the ISO-text marker and S-0052's offset guard


def _iso_cast(text: Expression) -> Expression:
    return exp.cast(
        exp.Anonymous(this="BLM_ISO_TEXT", expressions=[text]),
        exp.DataType.build("TIMESTAMP"),
    )


def test_the_iso_text_marker_becomes_the_strictly_safe_separator_rewrite() -> None:
    """Snowflake's ``AUTO`` input format documents the ``T``-separated ISO
    8601 form, so identity is the likely answer — but the two candidate
    spellings fail asymmetrically, and that decides it.

    If ``T`` is accepted, the rewrite costs a ``REPLACE`` over a value that
    parses identically afterwards. If some ISO form is not — DuckDB takes
    ``T`` and *raises* on the lowercase ``t`` — identity returns NULL for good
    data, which is the defect S-0044 and S-0052 exist to close. A NULL cannot
    be seen by a parser or by ``EXPLAIN``, so the live execution corpus is
    what settles it; until then the port takes the spelling that is safe under
    either measurement.
    """
    sql = _rendered(_iso_cast(exp.column("placed_at")))
    assert "REPLACE(REPLACE(CAST(placed_at AS VARCHAR), 'T', ' '), 't', ' ')" in sql


def test_the_offset_guard_renders_verbatim_on_this_port() -> None:
    """S-0052's guard needs nothing from Snowflake: the window over an
    explicit text cast and the two ``LIKE``s are all spelled the same way
    here, so the refusal of offset-bearing text arrives by inheritance rather
    than by a fourth remembered rule."""
    sql = _rendered(
        exp.TryCast(
            this=exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("_ingested_at")]),
            to=exp.DataType.build("TIMESTAMP"),
        )
    )
    assert "SUBSTRING(CAST(_ingested_at AS VARCHAR), 11)" in sql
    assert "LIKE '%+%'" in sql


def test_parse_ts_with_a_format_is_pinned_to_the_zoneless_type() -> None:
    """``TO_TIMESTAMP`` returns the ``TIMESTAMP_TYPE_MAPPING`` type, so under
    an account pointing that at ``TIMESTAMP_LTZ`` the parsed wall clock comes
    back with the session zone attached — D1's defect, reached through a
    parameter rather than through a type name.

    Snowflake converts ``TIMESTAMP_LTZ`` to ``TIMESTAMP_NTZ`` through the
    session zone, which is the attachment ``TO_TIMESTAMP`` just made, so the
    two cancel; under the default mapping the cast is a no-op.
    """
    built = DEFAULT_REGISTRY["parse_ts"].builder(exp.column("raw"), "%Y-%m-%d %H:%M:%S")
    sql = _rendered(canon(built).ast())
    assert sql.startswith("CAST(TO_TIMESTAMP(")
    assert sql.endswith("AS TIMESTAMPNTZ)")


# ....................... #
# Rewrite point 3: the TRY_* family


def test_try_cast_is_actually_emitted_and_given_a_string_source() -> None:
    """Two Snowflake facts meet here, and the second is a generator detail
    rather than a missing keyword.

    Snowflake's ``TRY_CAST`` takes a **string** source only, and SQLGlot's
    snowflake generator knows it: ``trycast_sql`` emits a plain ``CAST``
    unless the operand's annotated type is text. A neutral tree's operands are
    unannotated, so ``TRY_CAST(_ingested_at AS TIMESTAMP)`` rendered verbatim
    is ``CAST(...)`` — silently turning "quarantine the uncastable row" into
    "abort the run", which is the degradation S-0033/D-30 refused on
    PostgreSQL.

    So the operand is cast to ``VARCHAR``, which satisfies the restriction
    over whatever it is handed — a chain's inner cast may be numeric, and
    S-0033/D-21's metadata audit marks a bronze column a project may have
    landed typed.
    """
    node = exp.TryCast(this=exp.column("line_no"), to=exp.DataType.build("BIGINT"))
    assert _rendered(node) == "TRY_CAST(CAST(line_no AS VARCHAR) AS BIGINT)"
    assert DIALECT.supports(DialectFeature.TRY_CAST)


def test_an_operand_that_is_already_text_is_not_cast_twice() -> None:
    """A chain's ``to_string`` step already satisfies the restriction; a
    second identical cast around it would be noise in every artifact."""
    node = exp.TryCast(
        this=exp.cast(exp.column("raw"), exp.DataType.build("VARCHAR")),
        to=exp.DataType.build("DATE"),
    )
    assert _rendered(node) == "TRY_CAST(CAST(raw AS VARCHAR) AS DATE)"


# ....................... #
# Rewrite point 4: regexp capture-group numbering — nothing port-specific


def test_the_capture_group_survives_without_a_port_rewrite() -> None:
    """SQLGlot renders :class:`sqlglot.exp.RegexpExtract` here as
    ``REGEXP_SUBSTR(x, p, 1, 1, 'c', <group>)``, whose sixth argument is
    Snowflake's ``group_num`` — the same slot PostgreSQL's ``regexp_substr``
    uses, reached without PostgreSQL's rewrite because this generator already
    spells it.

    What the group needs is the shared restoration the base render applies to
    every tree: the IR keeps canonical text, and ``REGEXP_EXTRACT(x, p, 1)``
    re-parses with the third argument bound to ``position`` (S-0045/D-5).
    """
    built = DEFAULT_REGISTRY["regex_extract"].builder(exp.column("sku"), "sku-([0-9]+)", 1)
    assert _rendered(canon(built).ast()) == "REGEXP_SUBSTR(sku, 'sku-([0-9]+)', 1, 1, 'c', 1)"


# ....................... #
# Rewrite point 5: JSON and VARIANT extraction


def test_json_extraction_lowers_to_snowflakes_own_functions() -> None:
    """A bronze path is declared ``string`` and lowers to
    :class:`sqlglot.exp.JSONExtractScalar`, which SQLGlot renders as
    ``JSON_EXTRACT_PATH_TEXT`` — Snowflake's accessor over a JSON *string*,
    returning text, which is what the declared type says. The ``variant``
    transform lowers to :class:`sqlglot.exp.JSONExtract` and renders as
    ``GET_PATH(PARSE_JSON(...))``, whose result is ``VARIANT`` — the type this
    port maps ``variant`` to, so the extraction and the column agree.

    Neither needed a port rewrite, which is the answer S-0013/D-2 asks for
    when a rewrite point has nothing to add: PostgreSQL's ``jsonb`` detour
    exists because its ``variant`` is ``JSONB`` and its own functions return
    ``json``.
    """
    path = exp.JSONPath(expressions=[exp.JSONPathRoot(), exp.JSONPathKey(this="id")])
    scalar = exp.JSONExtractScalar(this=exp.column("customer"), expression=path)
    assert _rendered(scalar) == "JSON_EXTRACT_PATH_TEXT(customer, 'id')"
    variant = exp.JSONExtract(this=exp.column("payload"), expression=path.copy())
    assert _rendered(variant) == "GET_PATH(PARSE_JSON(payload), 'id')"


def test_arrays_use_the_semi_structured_spelling() -> None:
    """Snowflake's semi-structured array is untyped and built by
    ``ARRAY_CONSTRUCT``; the bracket form is documented for constants and a
    per-element type belongs to the newer *structured* surface, whose
    availability depends on the account. ``_quality_flags`` needs membership
    and size, which ``ARRAY_CONTAINS`` and ``ARRAY_SIZE`` give over the
    untyped array (S-0033/D-23).

    Trino's ``ARRAY(VARCHAR)`` is the rendering that must not be inherited
    here: it is native there and only looks native here (S-0013/D-2).
    """
    node = exp.cast(
        exp.Array(expressions=[exp.Literal.string("sku_coercible")]),
        exp.DataType.build("ARRAY<VARCHAR>"),
    )
    assert _rendered(node) == "CAST(ARRAY_CONSTRUCT('sku_coercible') AS ARRAY)"
    assert DIALECT.supports(DialectFeature.ARRAY)


# ....................... #
# Rewrite point 6: `text_sha256` — the base spelling, checked not copied


def test_text_sha256_is_the_base_spelling() -> None:
    """Snowflake's ``SHA2(msg, 256)`` takes a string and returns the lowercase
    hex digest directly, which is ``reject_id``'s contract (S-0033/D-21).

    Trino needed ``LOWER(TO_HEX(SHA256(TO_UTF8(…))))`` because *its* ``sha256``
    is binary in and binary out, and PostgreSQL needed ``ENCODE``/
    ``CONVERT_TO`` for the same reason. Copying either here would be a rewrite
    answering nobody's question (S-0013/D-2) — and would double the digest's
    length by hex-encoding an already-hex string.
    """
    sql = _rendered(DIALECT.text_sha256(exp.column("canon")))
    assert sql == "SHA2(canon, 256)"
    assert "TO_UTF8" not in sql
    assert "TO_HEX" not in sql


# ....................... #
# The two capabilities the source document predates, and the one gap


def test_json_object_is_object_construct_keeping_nulls() -> None:
    """Snowflake has no ``JSON_OBJECT`` at all, and its object builder *drops*
    any pair whose value is NULL.

    The reject table's ``raw`` and ``key_values`` are built from exactly the
    row that failed, so a NULL cell dropping its key would make the
    quarantined payload disagree with every other port's
    (S-0033/quarantine-one-reject-table-per-entity) — which is why the ``_KEEP_NULL`` variant is
    load-bearing rather than defensive.
    """
    node = DIALECT.json_object([("sku", exp.column("sku")), ("line_no", exp.column("line_no"))])
    assert _rendered(node) == "OBJECT_CONSTRUCT_KEEP_NULL('sku', sku, 'line_no', line_no)"
    assert DIALECT.supports(DialectFeature.JSON_OBJECT_POSITIONAL)


def test_null_safe_equality_is_the_standard_spelling() -> None:
    """Snowflake defines ``IS [NOT] DISTINCT FROM``, so a branch join keeps
    its NULL-keyed groups instead of dropping them (S-0055/D-13)."""
    node = exp.NullSafeEQ(this=exp.column("a"), expression=exp.column("b"))
    assert _rendered(node) == "a IS NOT DISTINCT FROM b"
    assert DIALECT.supports(DialectFeature.NULL_SAFE_EQUALITY)


def test_unicode_normalization_is_the_one_declared_gap() -> None:
    """Snowflake has no NFC normalization function — no ``NORMALIZE`` and
    nothing under another name; its Unicode surface is collation, which
    compares rather than rewrites.

    SQLGlot renders :class:`sqlglot.exp.Normalize` verbatim for every
    generator, so a ``normalize`` rule would compile clean and die on a
    function the engine never defined. Declaring the gap turns that into an
    emit-time refusal (S-0033/D-86, S-0025/D-3) — the answer S-0013/D-2 calls
    for where a rewrite point has no spelling to offer.
    """
    assert not DIALECT.supports(DialectFeature.UNICODE_NORMALIZE)
    assert {
        feature for feature in DialectFeature if not DIALECT.supports(feature)
    } == {DialectFeature.UNICODE_NORMALIZE}


# ....................... #


def test_reserved_names_are_quoted_in_their_folded_spelling() -> None:
    """SQLGlot's snowflake generator quotes nothing — verified: ``SELECT x FROM
    silver.order`` — and ``order`` is reserved here as it is on PostgreSQL. But
    quoting is case-significant on this engine: an unquoted name folds to
    UPPERCASE and a quoted one is taken verbatim, so the PostgreSQL spelling
    ``silver."order"`` would name a different object from the ``silver.order``
    the model declares (SQLMesh resolves that as ``"SILVER"."ORDER"``, and the
    project would not form a DAG). The port quotes the folded spelling, for
    relations and columns alike. The two reserved lists are not interchangeable
    in either direction: ``qualify``, ``minus`` and ``sample`` are reserved
    here and free there, ``offset`` and ``analyse`` the other way round.
    """
    node = exp.Select().select(exp.column("order")).from_(exp.table_("order", db="silver"))
    assert _rendered(node) == 'SELECT\n  "ORDER"\nFROM silver."ORDER"'


def test_the_calendar_series_becomes_a_generator_row_source() -> None:
    """The neutral calendar body's ``GENERATE_SERIES(...)`` row source renders
    here as ``ARRAY_GENERATE_RANGE(...)`` — a scalar function over integers,
    not a table, which the parser accepts and the engine refuses. The port
    rewrites it to Snowflake's row generator, with the count read from the
    series' own literal bounds, inclusive at both ends as ``dim_date`` is on
    every shipped port."""
    node = sqlglot.parse_one(
        "SELECT CAST(date_day AS DATE) AS date_day FROM GENERATE_SERIES("
        "CAST('2020-01-01' AS DATE), CAST('2020-01-10' AS DATE), INTERVAL '1' DAY"
        ") AS date_day(date_day)"
    )
    sql = _rendered(node)
    assert "ARRAY_GENERATE_RANGE" not in sql
    assert "FROM TABLE(GENERATOR(ROWCOUNT => 10))" in sql
    assert (
        "DATEADD(DAY, ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1, CAST('2020-01-01' AS DATE))"
        " AS date_day" in sql
    )
    assert sql.rstrip().endswith(") AS date_day")


def test_a_series_the_port_cannot_count_is_refused_by_name() -> None:
    """A step other than one day, or a bound that is not a literal date, has
    no row count to hand ``GENERATOR`` — refused at emit rather than rendered
    into SQL the engine rejects (S-0025/D-3)."""
    weekly = sqlglot.parse_one(
        "SELECT d FROM GENERATE_SERIES(CAST('2020-01-01' AS DATE), CAST('2020-03-01' AS DATE),"
        " INTERVAL '7' DAY) AS t(d)"
    )
    with pytest.raises(UnsupportedByTarget, match="one-day calendar"):
        DIALECT.render(weekly)

    computed = sqlglot.parse_one(
        "SELECT d FROM GENERATE_SERIES(CURRENT_DATE, CAST('2020-03-01' AS DATE),"
        " INTERVAL '1' DAY) AS t(d)"
    )
    with pytest.raises(UnsupportedByTarget, match="literal date bound"):
        DIALECT.render(computed)


def test_begin_transaction_is_the_common_spelling() -> None:
    """Snowflake accepts ``BEGIN`` as a synonym of ``BEGIN TRANSACTION``, so
    the base attribute needs nothing — unlike Trino, which takes the standard
    ``START TRANSACTION`` only."""
    assert DIALECT.begin_transaction == "BEGIN"
