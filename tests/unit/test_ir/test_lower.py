"""The shared lowering primitives (RFC 0005 lowering rules; RFC 0006 D7
consumes them for path-conflict shadows)."""

from __future__ import annotations

import pytest

from bloomery.ir import SqlExpr, canon, extraction, generic_type
from bloomery.typing import DecimalType, StringType, TimestampType

pytestmark = pytest.mark.unit


def test_extraction_of_a_single_segment_is_the_physical_column() -> None:
    assert extraction("$.qty").sql() == "qty"


def test_extraction_of_nested_segments_is_json_extraction() -> None:
    assert extraction("$.customer.address.city").sql() == (
        "JSON_EXTRACT_SCALAR(customer, '$.address.city')"
    )


def test_generic_type_computes_decimal_and_maps_scalars() -> None:
    assert generic_type(DecimalType(12, 4)).sql() == "DECIMAL(12, 4)"
    assert generic_type(StringType()).sql() == "TEXT"
    assert generic_type(TimestampType()).sql() == "TIMESTAMP"


def test_canon_wraps_compact_dialect_neutral_text() -> None:
    assert canon(extraction("$.a.b")) == SqlExpr("JSON_EXTRACT_SCALAR(a, '$.b')")
