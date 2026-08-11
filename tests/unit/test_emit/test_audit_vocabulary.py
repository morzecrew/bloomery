"""Which audit vocabulary each ``assert:`` clause lowers to (RFC 0008 §10 → D16).

§10 left this "to be settled against the pinned sqlmesh version", and the split
that shipped is real but was never written down: ``not_null`` and ``enum`` go to
each framework's **native** audit, while ``min``/``max``/``regex`` render a
predicate bloomery builds.

It is not "whatever SQLMesh happens to have". The pinned sqlmesh (0.236) ships
``accepted_range`` and ``match_regex_pattern_list``, and reading their queries
beside :func:`~bloomery.emit.lowering.audit_predicate` they mean *exactly* the
same thing — ``accepted_range(min_v := N)`` is ``column < N`` and
``match_regex_pattern_list(patterns := [p])`` is ``NOT REGEXP_LIKE(column, p)``.
Availability was never the constraint.

**The criterion is agreement between the two targets.** dbt-core has native
``not_null`` and ``accepted_values`` tests; it has no range or regex test at all
(``dbt_utils.expression_is_true`` is a *package*). So for the first two, both
frameworks say the same thing in their own words and bloomery uses each one's.
For the rest, only SQLMesh has a builtin — and taking it would leave
``audit_predicate`` with dbt as its only consumer, so the two targets' meaning
would be related by intent rather than by construction. One function builds
both forms, which is what makes them provably the same check.

This module pins the split so a future change to it is deliberate.
"""

from __future__ import annotations

import pytest
import yaml

from bloomery import Target, compile_project, load_project

pytestmark = pytest.mark.unit

ENTITY_MODEL = """
spec_version: 1
entities:
  t:
    grain: one row per thing
    key: [k]
    fields:
      k: {type: string, required: true}
      amount: {type: int, assert: {min: 0, max: 100}}
      code: {type: string, assert: {regex: "^[A-Z]{3}$", not_null: true, enum: [ABC, DEF]}}
"""

MAPPING = """
mapping_version: 1
target: t
source: raw__t
key:
  k: {from: "$.k", transform: [to_string]}
fields:
  amount: {from: "$.amount", transform: [to_int]}
  code: {from: "$.code", transform: [to_string]}
"""

#: The clauses that take a native audit on **both** targets, and the ones that
#: take bloomery's own predicate on both. The split is the decision; the lists
#: are how a change to it becomes a failing test rather than a diff nobody
#: reads.
NATIVE = ("not_null", "enum")
SHARED_PREDICATE = ("min", "max", "regex")


def _compile(target: Target) -> dict[str, str]:
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING})
    return {
        artifact.path: artifact.content
        for artifact in compile_project(project, target=target, dialect="duckdb")
    }


def test_sqlmesh_takes_the_builtin_where_dbt_also_has_one() -> None:
    """``not_null`` and ``accepted_values`` are declared inline in the MODEL
    block, in SQLMesh's own vocabulary — no artifact of bloomery's own."""
    model = _compile(Target.SQLMESH)["models/silver/t.sql"]
    assert "not_null(columns := (code))" in model
    assert "accepted_values(column := code, is_in := ('ABC', 'DEF'))" in model


def test_dbt_takes_its_native_test_for_the_same_two() -> None:
    schema = yaml.safe_load(_compile(Target.DBT)["models/schema.yml"])
    (entry,) = schema["models"]
    column = next(c for c in entry["columns"] if c["name"] == "code")
    assert "not_null" in column["data_tests"]
    assert any(
        isinstance(test, dict) and "accepted_values" in test for test in column["data_tests"]
    )


@pytest.mark.parametrize("kind", SHARED_PREDICATE)
def test_a_clause_dbt_cannot_express_natively_gets_one_shared_predicate(kind: str) -> None:
    """The other half of the criterion. dbt-core has no range or regex test, so
    both targets render the predicate :func:`audit_predicate` builds — the
    SQLMesh side as the violating rows, the dbt side as the assertion that must
    hold. Same function, two directions, so they cannot drift."""
    sqlmesh = _compile(Target.SQLMESH)
    assert f"audits/t_amount_{kind}.sql" in sqlmesh or f"audits/t_code_{kind}.sql" in sqlmesh


def test_the_two_directions_are_complements_not_two_opinions() -> None:
    """The property the shared predicate exists for, asserted rather than
    assumed: SQLMesh selects ``amount > 100`` and dbt asserts ``amount <= 100``
    — one bound, stated twice, from one place."""
    sqlmesh = _compile(Target.SQLMESH)["audits/t_amount_max.sql"]
    dbt = _compile(Target.DBT)["models/schema.yml"]
    assert "amount > 100" in sqlmesh
    assert "amount <= 100" in dbt


def test_no_range_or_regex_clause_reaches_a_sqlmesh_builtin() -> None:
    """The pinned sqlmesh *has* ``accepted_range`` and
    ``match_regex_pattern_list``, and they mean what bloomery means — so this
    is a check on the decision, not on availability. Taking them would strand
    ``audit_predicate`` with a single consumer."""
    model = _compile(Target.SQLMESH)["models/silver/t.sql"]
    assert "accepted_range" not in model
    assert "match_regex_pattern_list" not in model


def test_the_builtins_this_decision_declines_do_exist() -> None:
    """The control. If a later sqlmesh dropped them, the decision above would
    still hold but its *reasoning* would be stale — and a decision resting on a
    fact nobody checks is how an RFC row rots."""
    from sqlmesh.core.audit import builtin

    available = {audit.name for audit in builtin.BUILT_IN_AUDITS.values()}
    assert {"accepted_range", "match_regex_pattern_list"} <= available
