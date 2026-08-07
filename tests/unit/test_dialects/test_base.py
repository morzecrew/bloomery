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
)
from bloomery.emit.base import Feature
from bloomery.errors import EmitError
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
