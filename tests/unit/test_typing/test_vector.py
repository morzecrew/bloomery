"""The eighth logical type (S-0011/D-3, S-0011/D-4): a vector carries a scalar
*name* and an int dimension, round-trips through the spec spelling, and is
assignable to nothing but an identical vector — `variant` included, which would
otherwise launder a declared dimension into the unmapped tail."""

from __future__ import annotations

import pytest

from bloomery.errors import TypeCheckError
from bloomery.typing import (
    DecimalType,
    IntType,
    StringType,
    VariantType,
    VectorType,
    assignable,
    parse_type,
    render_type,
)

pytestmark = pytest.mark.unit


def test_a_declared_vector_parses_into_a_name_and_an_int() -> None:
    parsed = parse_type("vector(float32, 1536)", source_path="p")
    assert parsed == VectorType(scalar="float32", dimensions=1536)
    # The dimension is an int and the scalar a str: no float value is parsed,
    # so the package-wide ban holds unchanged (S-0011/D-3).
    assert isinstance(parsed.dimensions, int)
    assert isinstance(parsed.scalar, str)


def test_both_scalars_parse_with_or_without_the_space() -> None:
    assert parse_type("vector(float16,8)", source_path="p") == VectorType(
        scalar="float16", dimensions=8
    )


def test_the_rendered_spelling_parses_back_to_the_same_type() -> None:
    vector = VectorType(scalar="float32", dimensions=1536)
    assert render_type(vector) == "vector(float32,1536)"
    assert parse_type(render_type(vector), source_path="p") == vector


@pytest.mark.parametrize(
    "text",
    [
        "vector(float32, 0)",  # a zero-dimension vector has nothing to score
        "vector(float64, 8)",  # outside the closed scalar vocabulary
        "vector(float32)",  # no dimension at all
        "vector(8, float32)",  # the two the wrong way round
    ],
)
def test_a_vector_outside_the_grammar_is_refused(text: str) -> None:
    with pytest.raises(TypeCheckError):
        parse_type(text, source_path="p")


def test_the_zero_dimension_refusal_says_what_it_wants() -> None:
    with pytest.raises(TypeCheckError, match="dimensions must be >= 1"):
        parse_type("vector(float32, 0)", source_path="p")


def test_the_unknown_type_message_names_the_vector_grammar() -> None:
    with pytest.raises(TypeCheckError, match=r"vector\(scalar, dimensions\)"):
        parse_type("vector(float64, 8)", source_path="p")


# ....................... #
# Assignability (S-0011/D-4)


def test_an_identical_vector_is_assignable() -> None:
    vector = VectorType(scalar="float32", dimensions=4)
    assert assignable(vector, VectorType(scalar="float32", dimensions=4))
    assert assignable(vector, vector)


@pytest.mark.parametrize(
    "other",
    [
        VectorType(scalar="float32", dimensions=5),
        VectorType(scalar="float16", dimensions=4),
    ],
)
def test_a_vector_of_another_shape_is_not_assignable(other: VectorType) -> None:
    vector = VectorType(scalar="float32", dimensions=4)
    assert not assignable(vector, other)
    assert not assignable(other, vector)


@pytest.mark.parametrize("other", [StringType(), IntType(), VariantType(), DecimalType(9, 2)])
def test_a_vector_neither_assigns_to_nor_accepts_any_other_type(other: object) -> None:
    """`variant` included: accepting one there would launder a declared
    dimension into the unmapped tail, which is the check S-0011/D-4 exists for."""

    vector = VectorType(scalar="float32", dimensions=4)
    assert not assignable(vector, other)  # type: ignore[arg-type]
    assert not assignable(other, vector)  # type: ignore[arg-type]
