"""_canon_bytes / project_fingerprint (RFC 0003 §5.4): distinct values →
distinct bytes; permuted input but equal IR → identical bytes; every scalar
kind covered; floats rejected."""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from enum import StrEnum

import pytest

from bloomery.ir import DimensionRef, ProjectIR, SqlExpr, Unit, project_fingerprint
from bloomery.ir.fingerprint import _canon_bytes
from support.ir_factory import build_project_ir

pytestmark = pytest.mark.unit


def test_fingerprint_shape() -> None:
    fp = project_fingerprint(build_project_ir())
    assert fp.startswith("blm1:")
    assert len(fp) == len("blm1:") + 64
    assert set(fp[5:]) <= set("0123456789abcdef")


def test_equal_ir_identical_bytes() -> None:
    assert _canon_bytes(build_project_ir()) == _canon_bytes(build_project_ir())


def test_permuted_input_equal_ir_identical_bytes() -> None:
    # The factory sorts columns as the real builder must (RFC 0003 §5.3):
    # permuted authored order → equal IR → identical bytes and fingerprint.
    a = build_project_ir(column_names=("unit_price", "order_id"))
    b = build_project_ir(column_names=("order_id", "unit_price"))
    assert a == b
    assert _canon_bytes(a) == _canon_bytes(b)
    assert project_fingerprint(a) == project_fingerprint(b)


def test_distinct_ir_distinct_bytes() -> None:
    base = build_project_ir()
    variants = [
        ProjectIR(),
        ProjectIR(bloomery_ir_version=2),  # version change is loud (RFC 0003 D3)
        dataclasses.replace(base, marts=()),
        dataclasses.replace(base, metrics=base.metrics[:1]),
    ]
    seen = {_canon_bytes(base)}
    for variant in variants:
        encoded = _canon_bytes(variant)
        assert encoded not in seen, variant
        seen.add(encoded)


@dataclasses.dataclass(frozen=True, slots=True)
class _Node:
    value: object


def test_scalar_kinds_are_type_tagged() -> None:
    # distinct scalar kinds with lookalike reprs must never collide
    lookalikes = [
        _Node(value=1),
        _Node(value="1"),
        _Node(value=Decimal(1)),
        _Node(value=True),
        _Node(value=None),
        _Node(value=(1,)),
        _Node(value=Unit.CURRENCY),
        _Node(value="currency"),
    ]
    encodings = [_canon_bytes(node) for node in lookalikes]
    assert len(set(encodings)) == len(encodings)


def test_decimal_encoding_is_exact() -> None:
    assert _canon_bytes(_Node(Decimal("1.10"))) != _canon_bytes(_Node(Decimal("1.1")))


def test_nested_tuples_length_prefixed() -> None:
    # ((a, b), ()) vs ((a,), (b,)) must not collide under concatenation
    assert _canon_bytes(_Node((("a", "b"), ()))) != _canon_bytes(_Node((("a",), ("b",))))


def test_none_vs_empty_distinct() -> None:
    assert _canon_bytes(_Node(None)) != _canon_bytes(_Node(()))
    assert _canon_bytes(_Node(None)) != _canon_bytes(_Node(""))


def test_enum_encodes_by_value() -> None:
    class Other(StrEnum):
        CURRENCY = "currency"

    # same value, different enum class → same bytes (RFC 0003 §5.4: by value)
    assert _canon_bytes(_Node(Unit.CURRENCY)) == _canon_bytes(_Node(Other.CURRENCY))


def test_dataclass_type_is_part_of_encoding() -> None:
    @dataclasses.dataclass(frozen=True, slots=True)
    class OtherNode:
        value: object

    assert _canon_bytes(_Node("x")) != _canon_bytes(OtherNode("x"))


def test_float_rejected() -> None:
    with pytest.raises(TypeError, match="floats are banned"):
        _canon_bytes(_Node(value=1.5))


def test_float_nested_in_tuple_rejected() -> None:
    with pytest.raises(TypeError, match="floats are banned"):
        _canon_bytes(_Node(value=("a", (2.5,))))


def test_unsupported_type_rejected() -> None:
    with pytest.raises(TypeError, match="unsupported"):
        _canon_bytes(_Node(value=[1, 2]))


def test_sql_expr_and_dimension_ref_reachable() -> None:
    a = _canon_bytes(_Node((SqlExpr("a + b"), DimensionRef("date", "ordered"))))
    b = _canon_bytes(_Node((SqlExpr("a + b"), DimensionRef("date", "shipped"))))
    assert a != b
