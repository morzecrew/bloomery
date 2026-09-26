"""No shipped port spells a vector (S-0011/D-4): the type exists so a retrieval
guardrail can compare a dimension, and the engine-side spelling belongs to the
retrieval target rather than to a warehouse port's DDL."""

from __future__ import annotations

import pytest

from bloomery.dialects import get_dialect
from bloomery.errors import UnsupportedByTarget
from bloomery.typing import StringType, VectorType

pytestmark = pytest.mark.unit

PORTS = ["duckdb", "postgres", "trino"]


@pytest.mark.parametrize("name", PORTS)
def test_no_port_has_a_physical_type_for_a_vector(name: str) -> None:
    dialect = get_dialect(name)
    with pytest.raises(UnsupportedByTarget) as excinfo:
        dialect.physical_type(VectorType(scalar="float32", dimensions=1536))
    message = str(excinfo.value)
    assert f"dialect {name!r} has no physical type for vector(float32, 1536)" in message
    assert "Fix: a vector column belongs to a retrieval target" in message


@pytest.mark.parametrize("name", PORTS)
def test_the_same_port_still_spells_a_scalar(name: str) -> None:
    assert get_dialect(name).physical_type(StringType())
