"""Scaffold smoke test: the package imports and exposes an (empty) public API.

Exists so the test/coverage lane is exercised from the first commit; real
tier-1 suites replace its significance as RFCs 0002–0009 land.
"""

import pytest

import bloomery

pytestmark = pytest.mark.unit


def test_package_has_empty_public_api() -> None:
    assert bloomery.__all__ == []
