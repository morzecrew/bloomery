"""Range sanity (RFC 0006 §5.6, D8): well-typedness of assert: clauses
against the field's logical type, and their lowering into AuditIR entries."""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_project
from bloomery.errors import AssertLoweringError, GuardrailError
from bloomery.guardrails.asserts import lower_asserts
from bloomery.ir import AuditIR, ProjectIR
from bloomery.spec import Project

pytestmark = pytest.mark.unit


def _project(fields: str, mapped: str) -> Project:
    model = f"""\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    fields:
      event_id: {{type: string, required: true}}
{fields}
"""
    mapping = f"""\
mapping_version: 1
source: raw__events
target: event
key:
  event_id: {{from: "$.id", transform: [to_string]}}
fields:
{mapped}
"""
    return load_project({"entity_model": model, "mapping": mapping})


def _build(fields: str, mapped: str) -> ProjectIR:
    return build_project_ir(_project(fields, mapped))


def _refusal(fields: str, mapped: str) -> GuardrailError:
    with pytest.raises(GuardrailError) as excinfo:
        _build(fields, mapped)
    return excinfo.value


def _audits(ir: ProjectIR) -> tuple[AuditIR, ...]:
    return ir.entities[0].audits


# ....................... #
# Lowering (the valid clauses become entity audits, sorted by kind, column)


def test_valid_clauses_lower_into_sorted_audits() -> None:
    ir = _build(
        "      amount: {type: \"decimal(10,2)\", assert: {min: 0, max: 100, not_null: true}}\n"
        "      code: {type: string, assert: {regex: \"^[A-Z]+$\", enum: [A, B]}}\n",
        '      amount: {from: "$.amount", transform: [{to_decimal: [10, 2]}]}\n'
        '      code: {from: "$.code"}\n',
    )
    assert _audits(ir) == (
        AuditIR(kind="enum", column="code", params=(("value_0000", "A"), ("value_0001", "B"))),
        AuditIR(kind="max", column="amount", params=(("value", "100"),)),
        AuditIR(kind="min", column="amount", params=(("value", "0"),)),
        AuditIR(kind="not_null", column="amount"),
        AuditIR(kind="regex", column="code", params=(("pattern", "^[A-Z]+$"),)),
    )


def test_temporal_bounds_take_iso_string_literals() -> None:
    ir = _build(
        '      occurred_at: {type: timestamp, assert: {min: "2020-01-01"}}\n',
        '      occurred_at: {from: "$.ts", transform: [{parse_ts: ISO8601}]}\n',
    )
    assert _audits(ir) == (
        AuditIR(kind="min", column="occurred_at", params=(("value", "2020-01-01"),)),
    )


def test_int_enum_members_lower_for_int_fields() -> None:
    ir = _build(
        "      status: {type: int, assert: {enum: [1, 2, 3]}}\n",
        '      status: {from: "$.status", transform: [to_int]}\n',
    )
    assert _audits(ir) == (
        AuditIR(
            kind="enum",
            column="status",
            params=(("value_0000", "1"), ("value_0001", "2"), ("value_0002", "3")),
        ),
    )


def test_fields_without_asserts_lower_no_audits() -> None:
    ir = _build(
        "      kind: {type: string}\n",
        '      kind: {from: "$.kind"}\n',
    )
    assert _audits(ir) == ()


# ....................... #
# Refusals (AssertLoweringError, batched with the rest)


def test_string_bound_on_a_numeric_field_is_refused() -> None:
    error = _refusal(
        '      amount: {type: int, assert: {min: "low"}}\n',
        '      amount: {from: "$.amount", transform: [to_int]}\n',
    )
    (leaf,) = error.collected
    assert isinstance(leaf, AssertLoweringError)
    assert leaf.source_path == "entity_model: entities.event.fields.amount.assert"
    assert "numeric field takes a numeric bound" in str(leaf)


def test_numeric_bound_on_a_temporal_field_is_refused() -> None:
    error = _refusal(
        "      occurred_at: {type: timestamp, assert: {max: 5}}\n",
        '      occurred_at: {from: "$.ts", transform: [{parse_ts: ISO8601}]}\n',
    )
    (leaf,) = error.collected
    assert "temporal field takes an ISO literal" in str(leaf)


def test_bound_on_a_bool_field_is_refused() -> None:
    error = _refusal(
        "      active: {type: bool, assert: {min: 0}}\n",
        '      active: {from: "$.active", transform: [to_bool]}\n',
    )
    (leaf,) = error.collected
    assert "requires a numeric or temporal field" in str(leaf)


def test_enum_on_a_decimal_field_is_refused() -> None:
    error = _refusal(
        "      amount: {type: \"decimal(10,2)\", assert: {enum: [1, 2]}}\n",
        '      amount: {from: "$.amount", transform: [{to_decimal: [10, 2]}]}\n',
    )
    (leaf,) = error.collected
    assert "enum: requires a string or int field" in str(leaf)


def test_enum_member_of_the_wrong_type_is_refused() -> None:
    error = _refusal(
        "      code: {type: string, assert: {enum: [A, 7]}}\n",
        '      code: {from: "$.code"}\n',
    )
    (leaf,) = error.collected
    assert "enum member 7 is not castable" in str(leaf)
    assert "as a str" in str(leaf)


def test_regex_on_a_non_string_field_is_refused() -> None:
    error = _refusal(
        '      amount: {type: int, assert: {regex: "^1$"}}\n',
        '      amount: {from: "$.amount", transform: [to_int]}\n',
    )
    (leaf,) = error.collected
    assert "regex: requires a string field" in str(leaf)


def test_uncompilable_regex_is_refused() -> None:
    error = _refusal(
        '      code: {type: string, assert: {regex: "["}}\n',
        '      code: {from: "$.code"}\n',
    )
    (leaf,) = error.collected
    assert "does not compile" in str(leaf)


def test_assert_on_an_unmapped_field_is_refused() -> None:
    # A clause no mapping lowers can never run — a silent hole (§5.6).
    error = _refusal(
        "      amount: {type: int, assert: {not_null: true}}\n      kind: {type: string}\n",
        '      kind: {from: "$.kind"}\n',
    )
    (leaf,) = error.collected
    assert isinstance(leaf, AssertLoweringError)
    assert "no mapping lowers the field" in str(leaf)


def test_assert_on_an_entity_absent_from_the_draft_is_refused() -> None:
    """Direct call: an entity no mapping targets never reaches the draft, so
    its clauses can never run either."""
    project = _project(
        "      amount: {type: int, assert: {not_null: true}}\n",
        '      amount: {from: "$.amount", transform: [to_int]}\n',
    )
    errors, audits = lower_asserts(project, ProjectIR())
    (leaf,) = errors
    assert isinstance(leaf, AssertLoweringError)
    assert audits == {}


def test_ill_typed_clauses_batch_across_fields() -> None:
    error = _refusal(
        '      amount: {type: int, assert: {min: "low"}}\n'
        '      code: {type: int, assert: {regex: "^a$"}}\n',
        '      amount: {from: "$.amount", transform: [to_int]}\n'
        '      code: {from: "$.code", transform: [to_int]}\n',
    )
    assert [type(leaf) for leaf in error.collected] == [AssertLoweringError, AssertLoweringError]
