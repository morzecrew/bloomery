"""Guardrail-stage properties (S-0023/tests): deterministic violation output
(byte-identical aggregate messages) and identity on clean projects."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bloomery import build_project_ir
from bloomery.errors import GuardrailError
from bloomery.guardrails import check_guardrails
from support.compiling import load_fixture

pytestmark = pytest.mark.property


@settings(max_examples=10, deadline=None)
@given(st.integers(min_value=0, max_value=9))
def test_guardrail_output_is_deterministic(_seed: int) -> None:
    """Same specs twice ⇒ byte-identical aggregate messages — the violation
    ordering is load-bearing (S-0023/tests)."""
    project, catalog = load_fixture("fanout_trap")
    with pytest.raises(GuardrailError) as first:
        build_project_ir(project, catalog)
    with pytest.raises(GuardrailError) as second:
        build_project_ir(project, catalog)
    assert str(first.value).encode() == str(second.value).encode()
    assert [str(leaf) for leaf in first.value.collected] == [
        str(leaf) for leaf in second.value.collected
    ]
    assert [leaf.source_path for leaf in first.value.collected] == [
        leaf.source_path for leaf in second.value.collected
    ]


@settings(max_examples=10, deadline=None)
@given(name=st.sampled_from(["minimal", "ecom_basic", "path_conflict"]))
def test_stage_is_identity_modulo_amendments(name: str) -> None:
    """On a violation-free project the stage amends only via path-conflict
    shadows and assert: lowering — re-running on the amended IR is the
    identity (S-0023/D-9)."""
    project, catalog = load_fixture(name)
    amended = build_project_ir(project, catalog)
    assert check_guardrails(amended, project=project, catalog=catalog) is amended
