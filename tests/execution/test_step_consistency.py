"""The cross-output consistency audit, executed (RFC 0017 §5.8, D16).

D16 accepts a real residual risk in exchange for one wrapper per output: the
step runs N times, and a step *misdeclared* as `pure` can produce disagreeing
siblings **within one run** — a `customer_xref` referencing `canonical_id`s
the `customer` execution never minted. No behavioural gate can see it (they
all compare run to run) and neither can the contract assertion (each output is
individually valid).

So this audit is the only thing standing between that and silently wrong
numbers, which makes executing it — rather than reading it — the point.
"""

from __future__ import annotations

import duckdb
import pytest
from support.compiling import compile_fixture, extract_select

pytestmark = pytest.mark.execution

CONSISTENT = (
    "('sys', 's1', 'c1', 'exact'), ('sys', 's2', 'c2', 'fuzzy'), ('sys', 's3', NULL, 'none')"
)
DISAGREEING = CONSISTENT + ", ('sys', 's4', 'never_minted', 'fuzzy')"


def _audit_sql() -> str:
    audit = next(
        a for a in compile_fixture("step_resolution") if a.path.startswith("audits/")
    )
    return extract_select(audit.content)


def _run(xref_rows: str) -> list[tuple[object, ...]]:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE SCHEMA silver")
        connection.execute(
            "CREATE TABLE silver.customer AS SELECT * FROM (VALUES "
            "('c1', 0.9), ('c2', 0.8)) AS t(canonical_id, confidence)"
        )
        connection.execute(
            f"CREATE TABLE silver.customer_xref AS SELECT * FROM (VALUES {xref_rows}) "
            "AS t(source_system, source_id, canonical_id, method)"
        )
        return connection.execute(_audit_sql()).fetchall()
    finally:
        connection.close()


def test_the_audit_catches_a_sibling_that_disagrees() -> None:
    """The failure D16 names, seeded exactly: one wrapper's execution minted a
    `canonical_id` the other's never did."""
    assert _run(DISAGREEING) == [("never_minted",)]


def test_the_audit_passes_on_a_consistent_run() -> None:
    """The control. Without it the test above would pass just as green against
    an audit that returned every row."""
    assert _run(CONSISTENT) == []


def test_a_null_reference_is_not_an_orphan() -> None:
    """RFC 0016's three-valued discipline: a row with no key value says
    nothing, and failing a blocking audit on it would punish the ordinary
    case. Both runs above carry a NULL `canonical_id`; neither reports it."""
    assert not any(row[0] is None for row in _run(DISAGREEING))


def test_a_single_output_step_emits_no_consistency_audit() -> None:
    """Nothing to disagree with — an audit there would be noise that trains
    people to ignore the ones that matter."""
    from bloomery.emit.base import EmitContext
    from bloomery.emit.steps import consistency_audits
    from bloomery.dialects import get_dialect
    from bloomery.naming import DefaultNaming
    from support.steps import RESOLVE_CUSTOMERS
    from bloomery.resolve.steps import lower_steps
    from bloomery import load_project
    from bloomery.steps import StepRegistry

    project = load_project(
        {
            "entity_model": "spec_version: 1\nentities: {}\n",
            "steps": (
                "steps_version: 1\nsteps:\n  - use: resolve_customers@3\n"
                "    inputs: {raw: silver.customer_raw}\n"
                "    outputs: {customer: silver.customer}\n"
            ),
        }
    )
    single = RESOLVE_CUSTOMERS.model_copy(
        update={"outputs": {"customer": RESOLVE_CUSTOMERS.outputs["customer"]}}
    )
    (step,) = lower_steps(project, StepRegistry({("resolve_customers", 3): single}))
    ctx = EmitContext(
        fingerprint="blm1:t", naming=DefaultNaming(), dialect=get_dialect("duckdb")
    )
    assert consistency_audits(step, ctx) == ()
