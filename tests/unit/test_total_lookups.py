"""No lookup in the compiler may fail as a bare ``StopIteration``
(RFC 0003 D11).

``next(x for x in xs if …)`` over a set an earlier stage validated is correct
and fails terribly: a bare ``StopIteration`` carries no message, no source
path, and no hint about which stage was supposed to prevent it. One escaped
from a `coverage` check naming an unmapped entity and read as a crash rather
than as a missing refusal — the guardrail that should have caught it simply
did not exist yet.

The invariant "every such lookup is total because a guardrail refused the case
that would break it" was real and held everywhere but that one place. What it
never had was somewhere to be *stated*, so drift was invisible. This module is
that place: :func:`~bloomery.errors.guaranteed` makes each call site name its
guarantor, and the scan below keeps the bare form from coming back.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "bloomery"


def python_sources() -> list[Path]:
    return sorted(SOURCE_ROOT.rglob("*.py"))


def bare_next_calls(tree: ast.AST) -> list[int]:
    """Line numbers of ``next(...)`` calls with no default argument."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "next"
        and len(node.args) == 1
    ]


def test_no_lookup_relies_on_a_bare_stop_iteration() -> None:
    """Either supply a default and handle the absence, or call ``guaranteed``
    and name the stage that makes the lookup total. Both say what happens when
    the value is missing; ``next(...)`` alone says nothing and raises an
    exception with no message."""
    offenders: list[str] = []
    for path in python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders.extend(
            f"{path.relative_to(SOURCE_ROOT)}:{line}" for line in bare_next_calls(tree)
        )
    assert offenders == [], (
        "bare next(...) without a default — use guaranteed(..., expected=…, by=…) "
        f"or pass a default: {offenders}"
    )


def test_the_scan_would_notice_one() -> None:
    """The control. A scan that found nothing because it looks for the wrong
    shape would pass the test above for the wrong reason."""
    tree = ast.parse("first = next(x for x in xs if x)\nsecond = next(iter(xs), None)\n")
    assert bare_next_calls(tree) == [1]


@pytest.mark.parametrize(
    "source",
    [
        "next(x for x in xs if x)",
        "next(iter(xs))",
        "next(candidates)",
    ],
)
def test_every_bare_spelling_is_caught(source: str) -> None:
    """The idiom has several spellings and the scan is shape-based, so each is
    asserted rather than assumed to fall out of the first."""
    assert bare_next_calls(ast.parse(source)) == [1]
