"""_canon_bytes / project_fingerprint (RFC 0003 §5.4): distinct values →
distinct bytes; permuted input but equal IR → identical bytes; every scalar
kind covered; floats rejected."""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from enum import StrEnum

import pytest

from bloomery.ir import (
    DedupeIR,
    DimensionRef,
    EntityIR,
    OnFail,
    ProjectIR,
    QualityRuleIR,
    QuarantineIR,
    ReconcileIR,
    SqlExpr,
    Unit,
    project_fingerprint,
    quality_sort_key,
)
from bloomery.ir.fingerprint import _canon_bytes
from support.ir_factory import build_project_ir

pytestmark = pytest.mark.unit


def _with_entity(ir: ProjectIR, entity: EntityIR) -> ProjectIR:
    """The project IR with its single entity replaced."""
    return dataclasses.replace(ir, entities=(entity,))


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
        ProjectIR(bloomery_ir_version=1),  # version change is loud (RFC 0003 D3)
        dataclasses.replace(base, marts=()),
        dataclasses.replace(base, metrics=base.metrics[:1]),
    ]
    seen = {_canon_bytes(base)}
    for variant in variants:
        encoded = _canon_bytes(variant)
        assert encoded not in seen, variant
        seen.add(encoded)


def test_quality_configuration_reaches_the_fingerprint() -> None:
    # RFC 0016 §5.7: every quality change classifies RESTATING, which only
    # works if the fingerprint sees it. The walker is type-driven, so the new
    # nodes need no encoder — this test is what proves that claim.
    base = build_project_ir()
    entity = base.entities[0]
    rule = QualityRuleIR("unit_price_range_min", "range", "unit_price", OnFail.QUARANTINE)
    variants = [
        _with_entity(base, dataclasses.replace(entity, quality=(rule,))),
        # the same rule, a different disposition — both directions RESTATE
        _with_entity(
            base,
            dataclasses.replace(
                entity, quality=(dataclasses.replace(rule, on_fail=OnFail.FLAG),)
            ),
        ),
        # the same rule, a different bound
        _with_entity(
            base,
            dataclasses.replace(entity, quality=(dataclasses.replace(rule, params=(("min", "1"),)),)),
        ),
        # a referential rule, whose disposition lives in params
        _with_entity(
            base,
            dataclasses.replace(
                entity,
                quality=(
                    QualityRuleIR(
                        "item_of_order",
                        "referential",
                        None,
                        None,
                        (("on_missing", "unknown_member"),),
                    ),
                ),
            ),
        ),
        _with_entity(
            base, dataclasses.replace(entity, dedupe=DedupeIR("latest_by", "_ingested_at"))
        ),
        _with_entity(
            base,
            dataclasses.replace(
                entity, dedupe=DedupeIR("latest_by", "_ingested_at", ("_load_id",))
            ),
        ),
        _with_entity(base, dataclasses.replace(entity, quarantine=QuarantineIR("90d"))),
        _with_entity(base, dataclasses.replace(entity, quarantine=QuarantineIR("12h"))),
        _with_entity(
            base, dataclasses.replace(entity, quarantine=QuarantineIR("90d", ("$.a.email",)))
        ),
        dataclasses.replace(
            base,
            reconcile=(
                ReconcileIR("totals", "sum(a)", "b", Decimal("0.01"), OnFail.FLAG),
            ),
        ),
        dataclasses.replace(
            base,
            reconcile=(
                ReconcileIR("totals", "sum(a)", "b", Decimal("0.010"), OnFail.FLAG),
            ),
        ),
    ]
    seen = {_canon_bytes(base)}
    for variant in variants:
        encoded = _canon_bytes(variant)
        assert encoded not in seen, variant
        seen.add(encoded)


def test_permuted_quality_rules_sorted_are_identical() -> None:
    # RFC 0003 §5.3: authored rule order carries nothing, so the canonical
    # sort makes permuted input yield an equal IR — and equal bytes.
    base = build_project_ir()
    entity = base.entities[0]
    unsorted = (
        QualityRuleIR("r", "range", "unit_price", OnFail.FLAG, (("max", "1000000"),)),
        QualityRuleIR("c", "coercible", "unit_price", OnFail.QUARANTINE),
        QualityRuleIR("r", "range", "unit_price", OnFail.QUARANTINE, (("min", "0"),)),
    )
    first = _with_entity(
        base, dataclasses.replace(entity, quality=tuple(sorted(unsorted, key=quality_sort_key)))
    )
    second = _with_entity(
        base,
        dataclasses.replace(
            entity, quality=tuple(sorted(reversed(unsorted), key=quality_sort_key))
        ),
    )
    assert first == second
    assert _canon_bytes(first) == _canon_bytes(second)
    assert project_fingerprint(first) == project_fingerprint(second)


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
