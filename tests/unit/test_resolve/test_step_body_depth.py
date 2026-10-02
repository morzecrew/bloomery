"""A step body is held to the depth cap authored expressions are (S-0088/D-3).

A registry body is assembled in Python and never passes ``SqlText``, so
``resolve/steps.py`` is its only door — and the body it parses is parsed again
at emit, deeper in the stack.
"""

from __future__ import annotations

import pytest
from sqlglot import parse_one

from bloomery import build_project_ir, load_project
from bloomery.errors import StepError
from bloomery.spec.common import MAX_SQL_DEPTH, sql_depth
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.unit


def _body(levels: int) -> str:
    """A body whose parsed tree is exactly ``levels`` deep."""
    for parens in range(levels):
        body = f"SELECT {'(' * parens}k{')' * parens} AS k FROM t"
        if sql_depth(parse_one(body)) == levels:
            return body
    raise AssertionError(levels)


def _build(body: str) -> object:
    project = load_project(
        {
            "entity_model": "spec_version: 1\nentities: {}\n",
            "steps": "steps_version: 1\nsteps:\n  - use: s@1\n    outputs: {out: silver.a}\n",
        }
    )
    manifest = StepManifest.model_validate(
        {
            "ref": "s",
            "version": 1,
            "kind": "sql_model",
            "determinism": "pure",
            "runtime_lock": "sha256:a91f",
            "entrypoint": None,
            "inputs": {},
            "parameters": {},
            "outputs": {"out": {"grain": "g", "key": ["k"], "produces": {"k": {"type": "string"}}}},
        }
    )
    registry = StepRegistry({("s", 1): manifest}, sql_bodies={("s", 1): body})
    return build_project_ir(project, steps=registry)


def test_a_body_at_the_depth_cap_builds() -> None:
    assert _build(_body(MAX_SQL_DEPTH))


def test_a_body_past_the_depth_cap_is_a_step_error() -> None:
    with pytest.raises(StepError, match=f"past the {MAX_SQL_DEPTH} authored SQL may nest"):
        _build(_body(MAX_SQL_DEPTH + 1))
