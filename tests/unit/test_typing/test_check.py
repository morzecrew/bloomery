"""The typecheck stage (S-0021/typecheck-stage-bloomery-typing-check-py): chain happy/sad paths, deterministic
closest-match suggestions, decimal tracking through arithmetic, batching."""

from __future__ import annotations

import pytest

from bloomery.errors import TypeCheckError, UnknownTransformError
from bloomery.spec.mapping import TransformStep
from bloomery.transforms import registry
from bloomery.typing import (
    ChainCheck,
    DecimalType,
    IntType,
    StringType,
    TimestampType,
    VariantType,
    VectorType,
    typecheck_chain,
    typecheck_chains,
)

pytestmark = pytest.mark.unit

REGISTRY = registry()


def steps(*raw: object) -> tuple[TransformStep, ...]:
    return tuple(TransformStep.model_validate(item) for item in raw)


def test_happy_chain_string_to_int() -> None:
    result = typecheck_chain(
        StringType(), steps("to_int"), IntType(), registry=REGISTRY, source_path="doc: f"
    )
    assert result == IntType()


def test_happy_chain_parse_ts_to_utc() -> None:
    chain = steps({"parse_ts": "ISO8601"}, {"to_utc": "Europe/Paris"})
    result = typecheck_chain(
        StringType(), chain, TimestampType(), registry=REGISTRY, source_path="doc: f"
    )
    assert result == TimestampType()


def test_empty_chain_requires_assignability() -> None:
    assert (
        typecheck_chain(StringType(), (), StringType(), registry=REGISTRY, source_path="p")
        == StringType()
    )
    with pytest.raises(TypeCheckError, match="not assignable"):
        typecheck_chain(StringType(), (), IntType(), registry=REGISTRY, source_path="p")


def test_anything_is_assignable_to_variant() -> None:
    result = typecheck_chain(
        StringType(), steps("to_int"), VariantType(), registry=REGISTRY, source_path="p"
    )
    assert result == IntType()


def test_unknown_transform_names_the_closest_match() -> None:
    with pytest.raises(UnknownTransformError) as excinfo:
        typecheck_chain(
            StringType(), steps("pars_ts"), TimestampType(), registry=REGISTRY, source_path="doc: f"
        )
    assert "closest match: 'parse_ts'" in str(excinfo.value)
    assert excinfo.value.source_path == "doc: f.transform[0]"


def test_unknown_transform_without_a_close_match() -> None:
    with pytest.raises(UnknownTransformError) as excinfo:
        typecheck_chain(
            StringType(), steps("zzzzzz"), StringType(), registry=REGISTRY, source_path="doc: f"
        )
    assert "closest match" not in str(excinfo.value)


def test_arity_mismatch() -> None:
    with pytest.raises(TypeCheckError, match=r"'trim' takes 0 argument\(s\), got 1") as excinfo:
        typecheck_chain(
            StringType(), steps({"trim": "x"}), StringType(), registry=REGISTRY, source_path="doc: f"
        )
    assert excinfo.value.source_path == "doc: f.transform[0]"


@pytest.mark.parametrize(
    ("step", "match"),
    [
        ({"to_decimal": ["12", 4]}, "argument 0 must be int"),
        ({"parse_ts": 5}, "argument 0 must be str"),
        ({"multiply": "not-a-number"}, "argument 0 must be number"),
        ({"multiply": "NaN"}, "argument 0 must be number"),
    ],
)
def test_arg_kind_mismatch(step: object, match: str) -> None:
    with pytest.raises(TypeCheckError, match=match):
        typecheck_chain(
            DecimalType(12, 4),
            steps(step),
            DecimalType(38, 10),
            registry=REGISTRY,
            source_path="doc: f",
        )


def test_input_domain_violation_names_the_accepted_types() -> None:
    with pytest.raises(TypeCheckError, match="'to_utc' does not accept string") as excinfo:
        typecheck_chain(
            StringType(),
            steps({"to_utc": "UTC"}),
            TimestampType(),
            registry=REGISTRY,
            source_path="doc: f",
        )
    assert "timestamp" in str(excinfo.value)
    assert excinfo.value.source_path == "doc: f.transform[0]"


def test_terminal_type_not_assignable() -> None:
    with pytest.raises(TypeCheckError, match="produces int, which is not assignable") as excinfo:
        typecheck_chain(
            StringType(), steps("to_int"), StringType(), registry=REGISTRY, source_path="doc: f"
        )
    assert excinfo.value.source_path == "doc: f"


def test_decimal_widening_is_implicit() -> None:
    result = typecheck_chain(
        StringType(),
        steps({"to_decimal": [10, 2]}),
        DecimalType(12, 4),
        registry=REGISTRY,
        source_path="p",
    )
    assert result == DecimalType(10, 2)


def test_decimal_narrowing_needs_an_explicit_step() -> None:
    with pytest.raises(TypeCheckError) as excinfo:
        typecheck_chain(
            StringType(),
            steps({"to_decimal": [12, 4]}),
            DecimalType(10, 2),
            registry=REGISTRY,
            source_path="doc: f",
        )
    message = str(excinfo.value)
    assert "decimal widening is implicit" in message
    assert "explicit to_decimal(p, s) step" in message


def test_decimal_tracking_through_arithmetic() -> None:
    chain = steps({"to_decimal": [20, 4]}, {"multiply": "2.5"})
    result = typecheck_chain(
        StringType(), chain, DecimalType(38, 10), registry=REGISTRY, source_path="p"
    )
    assert result == DecimalType(22, 5)


def test_decimal_cap_at_38_overflows_loudly() -> None:
    chain = steps({"to_decimal": [38, 0]}, {"multiply": 10})
    with pytest.raises(TypeCheckError, match="38-digit precision cap") as excinfo:
        typecheck_chain(StringType(), chain, DecimalType(38, 0), registry=REGISTRY, source_path="p")
    assert excinfo.value.source_path == "p.transform[1]"


def test_divide_follows_the_same_capped_scheme() -> None:
    chain = steps({"to_decimal": [12, 4]}, {"divide": 3})
    result = typecheck_chain(
        StringType(), chain, DecimalType(38, 10), registry=REGISTRY, source_path="p"
    )
    assert result == DecimalType(13, 4)


@pytest.mark.parametrize("args", [[], ["a"], ["a", "b", "c"]])
def test_enum_map_requires_pairs(args: list[str]) -> None:
    with pytest.raises(TypeCheckError, match="positive multiple of 2"):
        typecheck_chain(
            StringType(),
            steps({"enum_map": args}),
            StringType(),
            registry=REGISTRY,
            source_path="p",
        )


def test_enum_map_pairs_typecheck() -> None:
    result = typecheck_chain(
        StringType(),
        steps({"enum_map": ["a", "b", "c", "d"]}),
        StringType(),
        registry=REGISTRY,
        source_path="p",
    )
    assert result == StringType()


def test_batched_failures_combine_into_one_error() -> None:
    checks = [
        ChainCheck(StringType(), steps("pars_ts"), TimestampType(), "doc: fields.a"),
        ChainCheck(StringType(), steps("to_int"), StringType(), "doc: fields.b"),
        ChainCheck(StringType(), steps("trim"), StringType(), "doc: fields.c"),
    ]
    with pytest.raises(TypeCheckError) as excinfo:
        typecheck_chains(checks, registry=REGISTRY)
    error = excinfo.value
    assert len(error.collected) == 2
    assert "doc: fields.a.transform[0]" in str(error)
    assert "doc: fields.b" in str(error)


def test_batched_single_failure_raises_itself() -> None:
    checks = [
        ChainCheck(StringType(), steps("pars_ts"), TimestampType(), "doc: fields.a"),
        ChainCheck(StringType(), steps("trim"), StringType(), "doc: fields.c"),
    ]
    with pytest.raises(UnknownTransformError) as excinfo:
        typecheck_chains(checks, registry=REGISTRY)
    assert excinfo.value.collected == ()
    assert excinfo.value.source_path == "doc: fields.a.transform[0]"


def test_batched_success_returns_terminal_types() -> None:
    checks = [
        ChainCheck(StringType(), steps("to_int"), IntType(), "a"),
        ChainCheck(StringType(), steps({"to_decimal": [12, 4]}), DecimalType(12, 4), "b"),
    ]
    assert typecheck_chains(checks, registry=REGISTRY) == (IntType(), DecimalType(12, 4))


def test_a_chain_into_a_vector_is_refused_at_the_field() -> None:
    """S-0011/D-4: a vector arrives from a step, never from a mapping. Refused
    at type-check with the field's path, rather than at emit, where the neutral
    cast raised with no address and the schema-agreement census caught it."""
    with pytest.raises(TypeCheckError, match="a mapping chain cannot populate") as raised:
        typecheck_chain(
            StringType(), (), VectorType("float32", 3), registry=REGISTRY, source_path="mapping: fields.embedding"
        )
    assert raised.value.source_path == "mapping: fields.embedding"


@pytest.mark.parametrize("slot", ["key", "fields"])
def test_a_mapped_vector_is_refused_even_without_a_transform(slot: str) -> None:
    """An empty chain is a declared-type cast at extraction, and no cast reaches
    a vector (S-0011/D-4). The schema-agreement census drew exactly this — a
    vector key mapped straight from the source — and it reached emit with no
    address; it is now refused at the mapping's own key or field."""
    from bloomery import build_project_ir, load_project  # noqa: PLC0415

    fields = "a: {type: string}\n      v: {type: \"vector(float32, 3)\"}"
    key = "v" if slot == "key" else "a"
    documents = {
        "entity_model": f"spec_version: 1\nentities:\n  e:\n    grain: one e\n    key: [{key}]\n    fields:\n      {fields}\n",
        "mapping": (
            "mapping_version: 1\nsource: raw\ntarget: e\n"
            + (f"key:\n  v: {{from: \"$.v\"}}\nfields:\n  a: {{from: \"$.a\"}}\n" if slot == "key"
               else "key:\n  a: {from: \"$.a\"}\nfields:\n  v: {from: \"$.v\"}\n")
        ),
    }
    with pytest.raises(TypeCheckError, match="a mapping chain cannot populate vector") as raised:
        build_project_ir(load_project(documents))
    assert raised.value.source_path is not None and raised.value.source_path.endswith(f"{slot}.v")
