"""The Postgres dialect (RFC 0008 D5, M10): physical types for all seven
logical types, dialect-specific rendering, and the reserved-identifier
quoting the sqlglot postgres generator does not perform itself."""

from __future__ import annotations

import pytest
from sqlglot import exp, parse_one

from bloomery.dialects import PostgresDialect
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

DIALECT = PostgresDialect()


@pytest.mark.parametrize(
    ("logical", "physical"),
    [
        (StringType(), "TEXT"),
        (IntType(), "BIGINT"),
        (DecimalType(12, 4), "DECIMAL(12, 4)"),
        (DecimalType(38, 0), "DECIMAL(38, 0)"),
        (BoolType(), "BOOLEAN"),
        (DateType(), "DATE"),
        (TimestampType(), "TIMESTAMP"),
        (VariantType(), "JSONB"),  # binary JSON is the idiomatic pg variant
    ],
)
def test_physical_type_for_every_logical_type(logical: LogicalType, physical: str) -> None:
    assert DIALECT.physical_type(logical) == physical


def test_render_lowers_neutral_json_extraction_to_postgres() -> None:
    # Parsed like an IR ``SqlExpr`` (canonical neutral text re-parsed at
    # emit), so the JSONPath is a structured node the generator can lower.
    # The ``->>`` operator is polymorphic over json AND jsonb — the function
    # form JSON_EXTRACT_PATH_TEXT exists only for json (verified live).
    node = parse_one("customer ->> '$.id'")
    assert DIALECT.render(node) == "customer ->> 'id'"


def test_render_casts_deep_json_paths_to_json() -> None:
    # Multi-key paths keep the function form, which requires the json type.
    node = parse_one("payload ->> '$.a.b'")
    assert DIALECT.render(node) == "JSON_EXTRACT_PATH_TEXT(CAST(payload AS JSON), 'a', 'b')"


def test_render_quotes_reserved_relation_names() -> None:
    # sqlglot's postgres generator leaves ``order`` bare (illegal live);
    # the dialect port quotes reserved identifiers itself.
    node = exp.Select().select("x").from_(exp.table_("order", db="silver"))
    assert DIALECT.render(node) == 'SELECT\n  x\nFROM silver."order"'


def test_render_never_mutates_the_shared_ast() -> None:
    # The same neutral AST renders on every dialect (RFC 0008 D1): quoting
    # for postgres must not leak into a later duckdb rendering.
    node = exp.Select().select("x").from_(exp.table_("order", db="silver"))
    before = node.sql()
    DIALECT.render(node)
    assert node.sql() == before


def test_render_is_the_postgres_generator() -> None:
    assert DIALECT.name == "postgres"
    assert DIALECT.sqlglot_dialect == "postgres"
    node = exp.RegexpLike(this=exp.column("sku"), expression=exp.Literal.string("^A-"))
    assert DIALECT.render(node) == "sku ~ '^A-'"


def _iso_cast() -> exp.Expression:
    """What `{parse_ts: ISO8601}` lowers to: a cast over a marked operand."""
    return exp.cast(
        exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("x")]),
        exp.DataType.build("TIMESTAMP"),
    )


def test_the_iso_text_marker_is_stripped() -> None:
    """Postgres' own cast takes both ISO spellings, so the marker adds no
    separator rewrite on this port — what is left is the offset guard every
    port carries, in Postgres' own `SUBSTRING(… FROM …)` spelling (RFC 0036).

    A port that left the marker in place would emit `BLM_ISO_TEXT(x)`, which no
    engine defines — deliberately louder than silently NULL data (RFC 0027).
    """
    assert DIALECT.render(_iso_cast()) == (
        "CAST(CASE\n"
        "  WHEN SUBSTRING(CAST(x AS VARCHAR) FROM 11) LIKE '%+%'\n"
        "  OR SUBSTRING(CAST(x AS VARCHAR) FROM 11) LIKE '%-%'\n"
        "  THEN NULL\n"
        "  ELSE x\n"
        "END AS TIMESTAMP)"
    )


# ....................... #
# The rewrites RFC 0029 added. Each is asserted here at the rendering level so
# the default suite covers it: a sabotage sweep found that neutering
# `_zoneless_parse`, `_variant_is_jsonb` or `_jsonb_extraction` left every
# non-Docker tier green, which makes the engine tier the only thing standing
# between a regression and a release.


def _rendered(transform: str, *args: object, input_type: LogicalType | None = None) -> str:
    """A transform as this port emits it, through the canonical round trip the
    IR performs at emit (RFC 0003 D2)."""
    spec = DEFAULT_REGISTRY[transform]
    extra = {"input_type": input_type} if spec.types else {}
    return DIALECT.render(canon(spec.builder(exp.column("x"), *args, **extra)).ast())


def test_parse_ts_with_a_format_is_cast_back_to_a_zoneless_timestamp() -> None:
    """`to_timestamp(text, text)` returns `timestamptz`, having attached the
    *session* zone to the clock it just parsed, so one row stored a different
    instant depending on who ran it. The cast undoes the attachment exactly,
    because PostgreSQL converts `timestamptz` to `timestamp` through the same
    session zone (RFC 0029 §2.4).

    The value half — that the written clock survives under any session — is
    asserted against the engine in `tests/engines/test_zoneless_utc.py`; a
    wrong-but-zoneless spelling passes this test and fails that one.
    """
    assert _rendered("parse_ts", "%Y-%m-%d %H:%M:%S") == (
        "CAST(TO_TIMESTAMP(x, 'YYYY-MM-DD HH24:MI:SS') AS TIMESTAMP)"
    )
    # `parse_date` needs none of it: `TO_DATE` returns `date`, which has no
    # zone to attach.
    assert _rendered("parse_date", "%d/%m/%Y") == "TO_DATE(x, 'DD/MM/YYYY')"


def test_strip_suffix_uses_right_and_length_because_postgres_has_no_ends_with() -> None:
    """PostgreSQL has `starts_with` and no mirror of it, so `strip_suffix`
    failed at plan time with `42883` while `strip_prefix` ran.

    Deliberately not `LIKE '%' || s`, which would read `%` and `_` in the
    suffix as wildcards — the engine tier carries a `%` suffix to prove it.
    """
    assert "RIGHT(x, LENGTH('-eu')) = '-eu'" in _rendered("strip_suffix", "-eu")
    assert "STARTS_WITH" in _rendered("strip_prefix", "sku-")


def test_regex_extract_becomes_regexp_substr_keeping_the_capture_group() -> None:
    """PostgreSQL 16 defines no `regexp_extract` at all; `regexp_substr`'s
    sixth argument is the capture group."""
    assert _rendered("regex_extract", "sku-([0-9]+)", 1) == (
        "REGEXP_SUBSTR(x, 'sku-([0-9]+)', 1, 1, '', 1)"
    )


def test_a_neutral_variant_cast_becomes_jsonb() -> None:
    """`variant` is `JSONB` here while its *neutral* type is `JSON`, so every
    neutral variant cast disagreed with the column it was casting — invisible
    until `COALESCE(jsonb, json)` refused to coerce (`42846`).

    The bronze `->>` path below is the deliberate exception: it casts to `json`
    to reach a `json` function, for a column declared `string`.
    """
    assert _rendered("coalesce", "{}", input_type=VariantType()) == (
        "COALESCE(x, CAST('{}' AS JSONB))"
    )
    assert DIALECT.render(parse_one("payload ->> '$.a.b'")) == (
        "JSON_EXTRACT_PATH_TEXT(CAST(payload AS JSON), 'a', 'b')"
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        # A single key stays on the operator form, over a jsonb operand.
        ("$.a", "CAST(x AS JSONB) -> 'a'"),
        # Deeper paths take the jsonb twin of the function SQLGlot reaches for.
        ("$.a.b", "CAST(x AS JSONB) -> 'a' -> 'b'"),
        # Subscripts survive. An earlier version of this fix used
        # `jsonb_extract_path`, which takes *text* path elements and so had to
        # pull the keys out — dropping every subscript with them, so `$[0]`
        # returned the whole document.
        ("$[0]", "CAST(x AS JSONB) -> 0"),
        ("$.a[0]", "CAST(x AS JSONB) -> 'a' -> 0"),
        ("$.a.b[0]", "CAST(x AS JSONB) -> 'a' -> 'b' -> 0"),
        # A root-only path is the identity, and falls out of the operator form
        # for free. It rendered `JSON_EXTRACT_PATH(x)` before this branch — a
        # call PostgreSQL does not define, since its extraction functions are
        # variadic but not nullary. DuckDB and Trino always accepted theirs.
        ("$", "CAST(x AS JSONB)"),
    ],
)
def test_json_path_stays_in_jsonb_for_every_path_shape(path: str, expected: str) -> None:
    """Two shapes were broken and only one was registered: the deep path
    returned `json`, and the single-key path over a `string` column rendered
    `s -> 'a'`, which PostgreSQL has no operator for (`42883`). The conformance
    guard asks for one case per (transform, input type), and this transform
    takes several *path* shapes per input — so the rest are written by hand.

    Chaining `->` covers all of them with one branch, which is the point: the
    function form has to name path elements as text, and anything it cannot
    name it drops.
    """
    assert _rendered("json_path", path) == expected
