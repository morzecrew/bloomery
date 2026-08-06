"""Package-surface smoke test: the public API is exactly what spec §8 and the
stage RFCs promise (M2–M3 adds compile/resolve/build and the extension
points), and ``__all__`` stays sorted."""

from __future__ import annotations

import pytest

import bloomery

pytestmark = pytest.mark.unit


def test_public_api_surface() -> None:
    assert bloomery.__all__ == [
        "BloomeryError",
        "Resolution",
        "Target",
        "build_project_ir",
        "compile_project",
        "load_catalog",
        "load_project",
        "project_fingerprint",
        "register_emitter",
        "register_transform",
        "resolve",
    ]


def test_all_is_sorted_and_resolvable() -> None:
    assert bloomery.__all__ == sorted(bloomery.__all__)
    for name in bloomery.__all__:
        assert getattr(bloomery, name) is not None
