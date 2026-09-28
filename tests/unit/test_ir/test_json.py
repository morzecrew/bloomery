"""ir_json / ir_from_json (S-0002/D-2, S-0002/D-8): the IR's file form.

The pair is a round trip or it is nothing — an upstream read back has to be
the value the upstream compile produced, because that value is what the
resolver, the guardrails and the fingerprint go on to read. So every test here
asks one of two questions: does the value come back, and are the bytes a
function of the value alone.
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal

import pytest

from bloomery.errors import SpecParseError
from bloomery.ir import (
    EntityIR,
    MetricFilterIR,
    MetricIR,
    OnFail,
    ProjectIR,
    ReconcileIR,
    ir_from_json,
    ir_json,
    project_fingerprint,
)
from bloomery.ir.nodes import UpstreamIR
from support.ir_factory import build_project_ir

pytestmark = pytest.mark.unit


def _ir(**changes: object) -> ProjectIR:
    """The factory's tree at *this* compiler's IR version.

    The factory pins version 3 — it predates every bump and is hashed by the
    determinism guard as it stands — and the loader refuses any version but its
    own, which is the point of the loader rather than a problem with it.
    """
    return dataclasses.replace(
        build_project_ir(**changes),  # type: ignore[arg-type]
        bloomery_ir_version=ProjectIR().bloomery_ir_version,
    )


def _round_trip(ir: ProjectIR) -> ProjectIR:
    return ir_from_json(ir_json(ir))


def test_the_ir_comes_back_the_value_it_went_in_as() -> None:
    ir = _ir()
    assert _round_trip(ir) == ir


def test_the_fingerprint_survives_the_file() -> None:
    # The one property composition rests on: a downstream compiled against a
    # loaded upstream fingerprints as it would against the object (S-0002/D-3).
    ir = _ir()
    assert project_fingerprint(_round_trip(ir)) == project_fingerprint(ir)


def test_an_upstream_crosses_whole() -> None:
    entity = _ir().entities[0]
    ir = dataclasses.replace(
        _ir(),
        upstream=(
            UpstreamIR(
                alias="platform",
                fingerprint="blm1:" + "0" * 64,
                entities=(entity,),
                name="ecom_platform",
                # The chain above the upstream (S-0002/D-4). It survives the
                # file or it is not there at all: the artifact is the only
                # thing a further downstream is handed (D8), and a cycle two
                # projects up is visible in nothing else.
                ancestry=(("ledger", "blm1:" + "1" * 64),),
            ),
        ),
    )
    assert _round_trip(ir) == ir
    assert _round_trip(ir).upstream[0].ancestry == (("ledger", "blm1:" + "1" * 64),)


def test_every_scalar_kind_survives() -> None:
    # Decimal, the three JSON scalars and an enum, all in the places the IR
    # actually puts them. A Decimal that came back a float or a string would
    # round-trip past `==` nowhere near here, so it is pinned at the source.
    base = _ir()
    ir = dataclasses.replace(
        base,
        reconcile=(
            ReconcileIR(
                name="orders_match",
                left="order",
                right="order_item",
                tolerance=Decimal("0.0100"),
                on_fail=OnFail.FAIL,
            ),
        ),
        metrics=(
            dataclasses.replace(
                base.metrics[0],
                filter=(
                    MetricFilterIR(
                        dimension="status", op="in", values=("paid", 7, True, Decimal("1.50"))
                    ),
                ),
            ),
        ),
    )
    back = _round_trip(ir)

    assert back == ir
    assert back.reconcile[0].tolerance == Decimal("0.0100")
    assert back.metrics[0].filter[0].values == ("paid", 7, True, Decimal("1.50"))
    assert back.reconcile[0].on_fail is OnFail.FAIL


def test_the_bytes_are_a_function_of_the_ir_and_nothing_else() -> None:
    # Two equal IRs built separately, and the same IR after a trip through the
    # file: one text, or the artifact is not reproducible from the value.
    first = ir_json(_ir(column_names=("unit_price", "order_id")))
    second = ir_json(_ir(column_names=("order_id", "unit_price")))

    assert first == second
    assert ir_json(ir_from_json(first)) == first


def test_a_float_is_refused_rather_than_written() -> None:
    ir = _ir()
    # The one value the IR bans (S-0020/D-5), reached the only way a test can:
    # past the type checker, exactly as the fingerprint's guard is tested.
    bad = dataclasses.replace(ir, entities=(dataclasses.replace(ir.entities[0], grain=1.5),))  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="floats are banned"):
        ir_json(bad)


def test_another_bloomerys_ir_is_refused_by_version() -> None:
    payload = json.loads(ir_json(_ir()))
    payload["bloomery_ir_version"] = payload["bloomery_ir_version"] - 1

    with pytest.raises(SpecParseError, match="recompile both sides with one compiler"):
        ir_from_json(json.dumps(payload))


def test_the_version_is_read_before_anything_is_reconstructed() -> None:
    # An older IR is refused for its version, never for whichever field moved:
    # the second message names a symptom and the fix for it is the wrong fix.
    payload = json.loads(ir_json(_ir()))
    payload["bloomery_ir_version"] = payload["bloomery_ir_version"] - 1
    del payload["entities"]

    with pytest.raises(SpecParseError, match="cannot diff IR version"):
        ir_from_json(json.dumps(payload))


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        "[]",
        '{"$node": "EntityIR", "name": "order"}',
        '{"$node": "Nonsense", "bloomery_ir_version": 22}',
    ],
)
def test_a_document_that_is_not_an_ir_is_a_refusal_not_a_traceback(text: str) -> None:
    with pytest.raises(SpecParseError, match="not a bloomery IR document"):
        ir_from_json(text)


def test_a_field_of_the_wrong_shape_is_a_refusal_not_an_attribute_error() -> None:
    """A document that names the right node and puts a string where a node
    belongs is refused at the loader, not left for the resolver to trip on."""

    payload = json.loads(ir_json(_ir()))
    payload["exports"] = "invalid"

    with pytest.raises(SpecParseError, match="ProjectIR.exports is not a"):
        ir_from_json(json.dumps(payload))


def test_a_malformed_decimal_is_a_refusal() -> None:
    """`Decimal("invalid")` raises `InvalidOperation`, an `ArithmeticError` and
    not a `ValueError`; the loader's boundary catches it too, so a malformed
    IR file is a refusal rather than an internal error."""

    base = _ir()
    ir = dataclasses.replace(
        base,
        reconcile=(
            ReconcileIR(
                name="orders_match",
                left="order",
                right="order_item",
                tolerance=Decimal("0.0100"),
                on_fail=OnFail.FAIL,
            ),
        ),
    )
    text = ir_json(ir).replace('"$decimal": "0.0100"', '"$decimal": "invalid"')
    assert '"invalid"' in text

    with pytest.raises(SpecParseError, match="not a bloomery IR document"):
        ir_from_json(text)
