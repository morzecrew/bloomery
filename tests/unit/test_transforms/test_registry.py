"""The transform registry (RFC 0004 §5.3): closed default, sorted iteration,
overlay extension, collision-is-an-error."""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest
from sqlglot import exp

from sqlglot.expressions.core import Expression

from bloomery.errors import TransformRegistrationError
from bloomery.resolve.build import _lower_chain
from bloomery.spec.mapping import TransformStep
from bloomery.transforms import (
    DEFAULT_REGISTRY,
    Builder,
    TransformSpec,
    register_transform,
    registry,
    transform,
)
from bloomery.typing import ArgKind, IntType, LogicalType, StringType

# The package re-exports the `registry` *function*, shadowing the submodule
# attribute — fetch the module itself for overlay isolation.
registry_module = importlib.import_module("bloomery.transforms.registry")

pytestmark = pytest.mark.unit

#: The starter set, exactly RFC 0004 D3.
STARTER_SET = [
    "abs",
    "coalesce",
    "concat",
    "convert",
    "divide",
    "enum_map",
    "json_path",
    "lower",
    "multiply",
    "nullif",
    "parse_date",
    "parse_ts",
    "regex_extract",
    "round",
    "split_part",
    "strip_prefix",
    "strip_suffix",
    "to_bool",
    "to_decimal",
    "to_int",
    "to_string",
    "to_utc",
    "trim",
    "upper",
]


@pytest.fixture(autouse=True)
def clean_overlay(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate the process-global overlay per test."""
    monkeypatch.setattr(registry_module, "_overlay", {})
    yield


def _spec(name: str) -> TransformSpec:
    return TransformSpec(
        name=name,
        arity=0,
        arg_kinds=(),
        input_domain=(StringType,),
        output_type=lambda t, _args: t,
        builder=lambda col: exp.Upper(this=col),
    )


def test_default_registry_is_exactly_the_starter_set() -> None:
    assert list(DEFAULT_REGISTRY) == STARTER_SET  # sorted by construction


def test_default_registry_is_immutable() -> None:
    with pytest.raises(TypeError):
        DEFAULT_REGISTRY["rogue"] = _spec("rogue")  # type: ignore[index]


def test_registry_iteration_is_sorted_regardless_of_registration_order() -> None:
    register_transform(_spec("zz_last"))
    register_transform(_spec("aa_first"))
    names = list(registry())
    assert names == sorted(names)
    assert names[0] == "aa_first"
    assert names[-1] == "zz_last"


def test_register_transform_overlay_is_consulted() -> None:
    register_transform(_spec("sponge"))
    assert registry()["sponge"].name == "sponge"
    assert "sponge" not in DEFAULT_REGISTRY


def test_register_transform_collision_with_default() -> None:
    with pytest.raises(TransformRegistrationError, match="'trim' is already registered"):
        register_transform(_spec("trim"))


def test_register_transform_collision_with_overlay() -> None:
    register_transform(_spec("sponge"))
    with pytest.raises(TransformRegistrationError, match="'sponge' is already registered"):
        register_transform(_spec("sponge"))


def test_decorator_collision_with_default() -> None:
    with pytest.raises(TransformRegistrationError, match="already registered"):

        @transform("trim", arity=0, input=(StringType,), output=StringType())
        def shadow(col: exp.Expression) -> exp.Expression:
            return col


@pytest.mark.parametrize(
    ("arity", "arg_kinds", "variadic", "match"),
    [
        (-1, (), False, "arity must be >= 0"),
        (1, (), False, "must match the number of declared arg kinds"),
        (0, (), True, "variadic transform needs at least one arg kind"),
    ],
)
def test_register_transform_validates_spec_shape(
    arity: int, arg_kinds: tuple[ArgKind, ...], variadic: bool, match: str
) -> None:
    spec = TransformSpec(
        name="broken",
        arity=arity,
        arg_kinds=arg_kinds,
        input_domain=(StringType,),
        output_type=lambda t, _args: t,
        builder=lambda col: col,
        variadic=variadic,
    )
    with pytest.raises(TransformRegistrationError, match=match):
        register_transform(spec)


def test_register_transform_rejects_empty_input_domain() -> None:
    spec = TransformSpec(
        name="broken",
        arity=0,
        arg_kinds=(),
        input_domain=(),
        output_type=lambda t, _args: t,
        builder=lambda col: col,
    )
    with pytest.raises(TransformRegistrationError, match="input domain must not be empty"):
        register_transform(spec)


def test_a_builder_is_told_its_input_type_only_when_it_declares_types() -> None:
    """RFC 0029 D1: the declaration of what a transform produces is a function
    of the input type, and the construction was not — so the two could disagree,
    and across the whole starter set they did.

    The flag is what keeps the public ``Builder`` signature intact: passing
    ``input_type=`` to every builder would break each registered extension
    (logs/T-0002.md D-001), so only a spec that asks for it is given it.
    """
    seen: list[object] = []

    def typed_builder(col: Expression, *, input_type: LogicalType) -> Expression:
        seen.append(input_type)
        return col

    def plain_builder(col: Expression) -> Expression:
        seen.append("not offered")
        return col

    def spec(name: str, builder: Builder, *, types: bool) -> TransformSpec:
        return TransformSpec(
            name=name,
            arity=0,
            arg_kinds=(),
            input_domain=(StringType, IntType),
            output_type=lambda _t, _a: IntType(),
            builder=builder,
            types=types,
        )

    registry: dict[str, TransformSpec] = {
        "typed": spec("typed", typed_builder, types=True),
        "plain": spec("plain", plain_builder, types=False),
    }
    _lower_chain(
        "$.x",
        (TransformStep(name="plain", args=()), TransformStep(name="typed", args=())),
        IntType(),
        registry,
        {},
        source_path="test",
    )
    # Bronze lands as text, so the first step sees `string`; the second sees what
    # the first *declared* it produces, not what its AST happened to build.
    assert seen == ["not offered", IntType()]
