"""Package-surface smoke test: the M1 public API is exactly what RFCs 0002 and
0003 promise, and ``__all__`` stays sorted."""

from __future__ import annotations

import pytest

import bloomery

pytestmark = pytest.mark.unit


def test_public_api_surface() -> None:
    assert bloomery.__all__ == [
        "BloomeryError",
        "load_catalog",
        "load_project",
        "project_fingerprint",
    ]


def test_all_is_sorted_and_resolvable() -> None:
    assert bloomery.__all__ == sorted(bloomery.__all__)
    for name in bloomery.__all__:
        assert getattr(bloomery, name) is not None
