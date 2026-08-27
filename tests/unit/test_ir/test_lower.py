"""The shared lowering primitives (RFC 0005 lowering rules; RFC 0006 D7
consumes them for path-conflict shadows)."""

from __future__ import annotations

import pytest

from bloomery.ir import PartitionSpec, SqlExpr, canon, extraction, partition_specs
from bloomery.transforms import neutral_type
from bloomery.typing import DecimalType, StringType, TimestampType

pytestmark = pytest.mark.unit


def test_extraction_of_a_single_segment_is_the_physical_column() -> None:
    assert extraction("$.qty").sql() == "qty"


def test_extraction_of_nested_segments_is_json_extraction() -> None:
    assert extraction("$.customer.address.city").sql() == (
        "JSON_EXTRACT_SCALAR(customer, '$.address.city')"
    )


def test_neutral_type_computes_decimal_and_maps_scalars() -> None:
    assert neutral_type(DecimalType(12, 4)).sql() == "DECIMAL(12, 4)"
    assert neutral_type(StringType()).sql() == "TEXT"
    assert neutral_type(TimestampType()).sql() == "TIMESTAMP"


def test_canon_wraps_compact_dialect_neutral_text() -> None:
    assert canon(extraction("$.a.b")) == SqlExpr("JSON_EXTRACT_SCALAR(a, '$.b')")


def test_partition_specs_parse_bare_columns_and_transforms_in_authored_order() -> None:
    assert partition_specs(("days(ordered_day)", "region")) == (
        PartitionSpec(transform="days", column="ordered_day"),
        PartitionSpec(transform=None, column="region"),
    )
