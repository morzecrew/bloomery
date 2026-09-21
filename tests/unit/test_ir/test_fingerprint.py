"""_canon_bytes / project_fingerprint (S-0020/fingerprint): distinct values →
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
from bloomery.ir.nodes import UpstreamIR
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
    # The factory sorts columns as the real builder must (S-0020/ordering-rules):
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
        ProjectIR(bloomery_ir_version=1),  # version change is loud (S-0020/D-3)
        dataclasses.replace(base, marts=()),
        dataclasses.replace(base, metrics=base.metrics[:1]),
    ]
    seen = {_canon_bytes(base)}
    for variant in variants:
        encoded = _canon_bytes(variant)
        assert encoded not in seen, variant
        seen.add(encoded)


def test_quality_configuration_reaches_the_fingerprint() -> None:
    # S-0033/plan-integration-rfc-0007-amendment: every quality change classifies RESTATING, which only
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
    # S-0020/ordering-rules: authored rule order carries nothing, so the canonical
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

    # same value, different enum class → same bytes (S-0020/fingerprint: by value)
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


def _importing(fingerprint: str, *, alias: str = "platform") -> ProjectIR:
    """A downstream project importing one entity from one upstream."""
    base = build_project_ir()
    return dataclasses.replace(
        base,
        upstream=(UpstreamIR(alias=alias, fingerprint=fingerprint, entities=base.entities),),
    )


def test_upstream_fingerprint_reaches_the_downstream() -> None:
    # S-0002/D-3: the upstream identity crosses whole, so an upstream change that
    # touches nothing the downstream reads still moves the downstream fingerprint.
    a = _importing("blm1:" + "a" * 64)
    b = _importing("blm1:" + "b" * 64)
    assert a.upstream[0].entities == b.upstream[0].entities
    assert project_fingerprint(a) != project_fingerprint(b)


def test_importing_differs_from_not_importing() -> None:
    assert project_fingerprint(_importing("blm1:" + "a" * 64)) != project_fingerprint(
        build_project_ir()
    )


def test_unmoved_upstream_identical_bytes() -> None:
    # The upstream's documents may be reformatted at will: nothing reaches here but
    # its IR, so an upstream whose IR did not move leaves the downstream byte-identical.
    a = _importing("blm1:" + "a" * 64)
    b = _importing("blm1:" + "a" * 64)
    assert _canon_bytes(a) == _canon_bytes(b)
    assert project_fingerprint(a) == project_fingerprint(b)


def test_local_alias_reaches_the_downstream() -> None:
    # The alias is the downstream's own spelling, and a rename is a change to it.
    a = _importing("blm1:" + "a" * 64, alias="platform")
    b = _importing("blm1:" + "a" * 64, alias="core")
    assert project_fingerprint(a) != project_fingerprint(b)
