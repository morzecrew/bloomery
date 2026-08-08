"""`plan()` over steps (RFC 0017 §5.6, D6/D11).

The RFC's claim is that steps need *no special-casing* in the differ: they are
IR nodes, the encoder covers them, and a change reads as an ordinary
structural diff. These tests are what makes that claim checkable — above all
the one the design is named for, that a `runtime_lock` bump alone produces a
RESTATING plan with a backfill, although no spec moved at all.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from bloomery import plan
from bloomery.plan import ChangeClass
from bloomery.ir import (
    Determinism,
    Lineage,
    StepColumnIR,
    StepIR,
    StepKind,
    StepOutputIR,
    StepParameterIR,
)
from bloomery.typing import StringType
from support.plan_ir import project

pytestmark = pytest.mark.unit


def step(**overrides: object) -> StepIR:
    base = StepIR(
        ref="resolve_customers",
        version=3,
        kind=StepKind.PYTHON_MODEL,
        determinism=Determinism.PURE,
        runtime_lock="sha256:a91f",
        lineage=Lineage.COARSE,
        entrypoint="platform_steps.resolve_customers:resolve",
        outputs=(
            StepOutputIR(
                name="customer",
                relation="silver.customer",
                grain="customer",
                key=("canonical_id",),
                columns=(StepColumnIR(name="canonical_id", type=StringType(), required=True),),
            ),
        ),
        inputs=(("raw", "silver.customer_raw"),),
        parameters=(StepParameterIR(name="threshold", value="0.9", type="decimal(4,3)"),),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def changes(old: StepIR | None, new: StepIR | None):  # noqa: ANN201
    old_ir = project(steps=(old,) if old is not None else ())
    new_ir = project(steps=(new,) if new is not None else ())
    return plan(old_ir, new_ir)


# ....................... #
# The claim the design is named for (§5.6, D6)


def test_a_runtime_lock_bump_alone_restates_and_backfills() -> None:
    """A `rapidfuzz` bump silently changing a scorer is invisible in every
    spec. This is the only thing that makes it visible — and a restatement
    that backfilled nothing would leave the warehouse holding rows no current
    code can reproduce (§4)."""
    result = changes(step(), step(runtime_lock="sha256:beef"))
    (change,) = result.changes
    assert change.change_class is ChangeClass.RESTATING
    assert change.subject == "step:resolve_customers"
    assert "pinned dependencies moved" in change.detail
    assert "although no spec did" in change.detail
    assert result.backfill_scope.entities == ("customer",)
    assert result.backfill_scope.restates_history


@pytest.mark.parametrize(
    ("label", "mutation"),
    [
        ("version", {"version": 4}),
        ("seed", {"seed": 7}),
        ("determinism", {"determinism": Determinism.SEEDED}),
        ("entrypoint", {"entrypoint": "platform_steps.v2:resolve"}),
        ("lineage", {"lineage": Lineage.COLUMN}),
        ("input wiring", {"inputs": (("raw", "silver.other"),)}),
        (
            "parameter",
            {"parameters": (StepParameterIR(name="threshold", value="0.8", type="decimal(4,3)"),)},
        ),
    ],
)
def test_every_behaviour_bearing_field_restates(label: str, mutation: dict[str, object]) -> None:
    """D11: a step has no privileged fields. `runtime_lock` is the one the
    design is named for, but a parameter, a seed or a rewired input is the
    same kind of fact and is treated the same."""
    (change,) = changes(step(), step(**mutation)).changes
    assert change.change_class is ChangeClass.RESTATING, label


def test_an_unchanged_step_is_the_empty_plan() -> None:
    """RFC 0007 D2's identity property has to survive the new node kind."""
    assert changes(step(), step()).changes == ()


# ....................... #
# Presence


def test_adding_a_step_is_additive() -> None:
    """RFC 0007 D2: an initial deploy is all-ADDITIVE, and adding a step is
    that same statement in the small."""
    (change,) = changes(None, step()).changes
    assert change.change_class is ChangeClass.ADDITIVE


def test_removing_a_step_is_breaking_and_names_the_orphaned_relation() -> None:
    """Nothing produces the relation afterwards — a reader needs to know
    which one before applying."""
    (change,) = changes(step(), None).changes
    assert change.change_class is ChangeClass.BREAKING
    assert "customer is no longer produced" in change.detail


def test_a_version_upgrade_is_one_change_not_a_remove_and_an_add() -> None:
    """Steps are keyed by ref. Keyed by ``ref@version`` an upgrade would read
    as one step removed and a different one added, losing the backfill exactly
    where it matters most."""
    result = changes(step(), step(version=4))
    (change,) = result.changes
    assert change.change_class is ChangeClass.RESTATING
    assert (change.old, change.new) == ("@3", "@4")
    assert result.backfill_scope.entities == ("customer",)


def test_a_changed_output_contract_restates() -> None:
    widened = (
        StepOutputIR(
            name="customer",
            relation="silver.customer",
            grain="customer",
            key=("canonical_id",),
            columns=(
                StepColumnIR(name="canonical_id", type=StringType(), required=True),
                StepColumnIR(name="confidence", type=StringType(), required=False),
            ),
        ),
    )
    (change,) = changes(step(), step(outputs=widened)).changes
    assert change.change_class is ChangeClass.RESTATING
