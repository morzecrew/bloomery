"""The dialect port and registry (RFC 0008 §5.1, D8): physical type mapping,
feature queries, registry collision/unknown-name behavior."""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest
from sqlglot import exp

from bloomery.dialects import (
    DialectFeature,
    DialectPort,
    DuckDBDialect,
    PostgresDialect,
    SQLGlotDialect,
    TrinoDialect,
    get_dialect,
    register_dialect,
    registered_dialects,
)
from bloomery.dialects.base import strip_iso_text
from bloomery.emit.base import Feature
from bloomery.errors import EmitError, UnsupportedByTarget
from bloomery.quality.pattern import unsupported_dialects
from bloomery.typing import DecimalType, StringType

pytestmark = pytest.mark.unit

dialects_module = importlib.import_module("bloomery.dialects")


@pytest.fixture(autouse=True)
def clean_overlay(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(dialects_module, "_overlay", {})
    yield


class _Custom(SQLGlotDialect):
    name = "custom"
    sqlglot_dialect = "postgres"


def test_get_dialect_returns_the_default() -> None:
    assert isinstance(get_dialect("duckdb"), DuckDBDialect)


def test_unknown_dialect_lists_known_names() -> None:
    expected = r"unknown dialect 'sqlite': known dialects are \['duckdb', 'postgres', 'trino'\]"
    with pytest.raises(EmitError, match=expected):
        get_dialect("sqlite")


def test_register_dialect_overlay() -> None:
    register_dialect(_Custom())
    assert get_dialect("custom").name == "custom"


def test_register_dialect_collision_is_an_error() -> None:
    with pytest.raises(EmitError, match="'duckdb' is already registered"):
        register_dialect(DuckDBDialect())


def test_registered_dialects_is_sorted_and_includes_the_overlay() -> None:
    """The public registry enumeration (RFC 0008 D8) — the D56 escape hatch
    builds an explicit dialect set for ``unsupported_dialects`` from it, so it
    must see extension registrations and stay sorted."""
    assert tuple(d.name for d in registered_dialects()) == ("duckdb", "postgres", "trino")
    register_dialect(_Custom())
    assert tuple(d.name for d in registered_dialects()) == (
        "custom",
        "duckdb",
        "postgres",
        "trino",
    )


def test_pattern_check_does_not_consult_the_mutable_registry() -> None:
    """RFC 0016 D56: registering a dialect must not change any verdict the
    compile stage reaches. A port that refuses every regex would flip
    ``unsupported_dialects`` if the check read the registry — it does not."""

    class _NoRegex(SQLGlotDialect):
        name = "noregex"
        sqlglot_dialect = "duckdb"

        def supports(self, feature: DialectFeature) -> bool:
            return feature is not DialectFeature.REGEXP_EXTRACT

    before = unsupported_dialects("^ok$")
    register_dialect(_NoRegex())
    assert unsupported_dialects("^ok$") == before == ()
    # ...and the explicit-argument hatch is what *does* see it.
    assert unsupported_dialects("^ok$", dialects=registered_dialects()) == ("noregex",)


def test_base_render_is_deterministic() -> None:
    node = exp.cast(exp.column("x"), exp.DataType.build("TEXT"))
    assert _Custom().render(node) == _Custom().render(node)


def test_base_supports_all_declared_features() -> None:
    dialect = _Custom()
    for feature in DialectFeature:
        assert dialect.supports(feature)


def test_base_physical_types() -> None:
    dialect = _Custom()
    assert dialect.physical_type(StringType()) == "TEXT"
    assert dialect.physical_type(DecimalType(12, 4)) == "DECIMAL(12, 4)"


@pytest.mark.parametrize(
    "dialect",
    [DuckDBDialect(), PostgresDialect(), TrinoDialect()],
    ids=lambda dialect: dialect.name,
)
def test_every_shipped_dialect_has_arrays(dialect: DialectPort) -> None:
    # RFC 0016 D9: array support is an *engine* property, so it is a
    # DialectFeature rather than a target Feature — SQLMesh-on-DuckDB and
    # dbt-on-DuckDB share it (the RFC 0008 D1 split). All three shipped
    # engines have a first-class array type (DuckDB STRING[], Postgres
    # TEXT[], Trino ARRAY(VARCHAR)), so none takes the delimited fallback.
    assert dialect.supports(DialectFeature.ARRAY)


def test_array_is_a_dialect_feature_not_a_target_feature() -> None:
    # the deliberate divergence from Document 5 §5.3, recorded as a test
    assert "array" in {feature.value for feature in DialectFeature}
    assert "array" not in {feature.value for feature in Feature}


def test_a_port_that_never_strips_the_iso_marker_is_refused() -> None:
    """The default is neither identity nor silence (RFC 0027).

    A port registered through `register_dialect` that inherits the base render
    and never decides what its engine needs would otherwise emit
    `BLM_ISO_TEXT(x)` — an undefined function that fails at *plan* time with the
    engine's own message. Defaulting to identity instead would be worse still:
    an engine whose cast rejects the `T` separator would return NULL for good
    data, which is the defect RFC 0027 exists to close.

    So the base renderer refuses, at emit, naming the one call to make.
    """

    class _Forgetful(SQLGlotDialect):
        name = "forgetful"
        sqlglot_dialect = "duckdb"

    node = exp.cast(
        exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("x")]),
        exp.DataType.build("TIMESTAMP"),
    )
    with pytest.raises(UnsupportedByTarget) as excinfo:
        _Forgetful().render(node)
    message = str(excinfo.value)
    assert "'forgetful'" in message
    assert "strip_iso_text" in message
    # The reason, not only the rule: a port author has to know why identity is
    # not a safe default.
    assert "silently NULL" in message


def test_a_port_that_strips_the_marker_renders_normally() -> None:
    """The companion: without it, deleting the guard's trigger would look like
    a pass."""

    class _Careful(SQLGlotDialect):
        name = "careful"
        sqlglot_dialect = "duckdb"

        def render(self, node: exp.Expression) -> str:
            return super().render(strip_iso_text(node.copy(), lambda text: text))

    node = exp.cast(
        exp.Anonymous(this="BLM_ISO_TEXT", expressions=[exp.column("x")]),
        exp.DataType.build("TIMESTAMP"),
    )
    assert _Careful().render(node) == "CAST(x AS TIMESTAMP)"
