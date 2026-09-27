"""A vector is the input of no transform and the output of no cast
(S-0011/D-4): its input domain is empty in every registered spec, and asking for
a neutral cast to one is a refusal rather than a `KeyError`."""

from __future__ import annotations

import pytest

from bloomery.errors import TypeCheckError
from bloomery.transforms import DEFAULT_REGISTRY, neutral_type
from bloomery.typing import StringType, VectorType

pytestmark = pytest.mark.unit


def test_no_transform_accepts_a_vector() -> None:
    """Admitting one would put float arithmetic inside a lowered expression,
    which is what the package-wide float ban stops (S-0011/D-4)."""

    accepting = [
        spec.name for spec in DEFAULT_REGISTRY.values() if VectorType in spec.input_domain
    ]
    assert accepting == []


def test_there_is_no_neutral_cast_to_a_vector() -> None:
    with pytest.raises(TypeCheckError) as excinfo:
        neutral_type(VectorType(scalar="float32", dimensions=1536))
    message = str(excinfo.value)
    assert "no neutral cast to vector(float32, 1536)" in message
    assert "Fix: populate a vector column from a step" in message


def test_the_other_types_still_have_one() -> None:
    assert neutral_type(StringType()).sql() == "TEXT"
