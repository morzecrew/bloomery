"""`Change.action`, `Change.member` and `Change.advice` (S-0024/D-11, #383).

A reader showing a plan in another language, grouped by column, had to take
the verb, the column and the dbt advice out of `detail`'s English. These
pin the three fields where the sentence used to be the only carrier; the
directory's conftest holds every other plan to them.
"""

from __future__ import annotations

import pytest
from support import plan_ir
from support.compiling import fixture_sources, load_fixture

from bloomery import build_project_ir, load_project
from bloomery.cli.render import render_plan
from bloomery.ir import Materialization, OnFail, QuarantineIR
from bloomery.plan import Change, ChangeAction, ChangeClass, plan
from bloomery.typing import parse_type

pytestmark = pytest.mark.unit


def _incremental(*columns: object, **kwargs: object) -> object:
    return plan_ir.project(
        entities=(
            plan_ir.entity(
                columns=tuple(columns),  # type: ignore[arg-type]
                materialization=Materialization.INCREMENTAL_BY_KEY,
                **kwargs,  # type: ignore[arg-type]
            ),
        )
    )


# ....................... #


def test_a_field_added_says_so_and_carries_the_dbt_refresh_beside_its_sentence() -> None:
    old = _incremental(plan_ir.column("id", required=True))
    new = _incremental(plan_ir.column("id", required=True), plan_ir.column("note"))

    (change,) = plan(old, new).changes  # type: ignore[arg-type]

    assert change == Change(
        "order_item",
        "field:note",
        ChangeClass.ADDITIVE,
        "field added",
        new="string, optional",
        action=ChangeAction.ADDED,
        member="note",
        advice=(("dbt", "run `dbt build --full-refresh -s order_item`"),),
    )


def test_the_reject_table_and_what_its_refresh_loses_stay_in_the_advice() -> None:
    quarantined = {"quarantine": QuarantineIR(retention="90d")}
    old = _incremental(plan_ir.column("id", required=True), **quarantined)
    new = _incremental(plan_ir.column("id", required=True), plan_ir.column("note"), **quarantined)

    (change,) = plan(old, new).changes  # type: ignore[arg-type]

    assert change.detail == "field added"
    assert change.advice == (
        (
            "dbt",
            "run `dbt build --full-refresh -s order_item order_item__reject`"
            " — resolved reject rows are lost",
        ),
    )


def test_a_new_quarantine_block_is_added_and_a_retention_edit_changed() -> None:
    bare = _incremental(plan_ir.column("id", required=True))
    kept = _incremental(plan_ir.column("id", required=True), quarantine=QuarantineIR(retention="90d"))
    longer = _incremental(plan_ir.column("id", required=True), quarantine=QuarantineIR(retention="180d"))

    (added,) = plan(bare, kept).changes  # type: ignore[arg-type]
    (edited,) = plan(kept, longer).changes  # type: ignore[arg-type]

    assert (added.action, added.detail) == (ChangeAction.ADDED, "quarantine block added (policy only)")
    assert (edited.action, edited.detail) == (
        ChangeAction.CHANGED,
        "quarantine retention changed (policy only)",
    )


def test_a_rename_names_the_new_column_and_a_retype_the_column_retyped() -> None:
    old = _incremental(plan_ir.column("quantity", expr="q"))
    new = _incremental(plan_ir.column("qty", expr="q", renamed_from="quantity", required=True))

    changes = {change.action: change for change in plan(old, new).changes}  # type: ignore[arg-type]

    assert changes[ChangeAction.RENAMED].member == "qty"
    assert changes[ChangeAction.RENAMED].detail == "renamed from 'quantity'"
    assert changes[ChangeAction.RETYPED].member == "qty"
    assert changes[ChangeAction.RETYPED].detail == "optional field became required"


def test_a_quality_rule_change_names_the_field_it_judges() -> None:
    rule = plan_ir.quality_rule(column_name="amount")
    old = plan_ir.project(entities=(plan_ir.entity(),))
    new = plan_ir.project(entities=(plan_ir.entity(quality=(rule,)),))

    (added,) = (c for c in plan(old, new).changes if c.subject.startswith("quality:"))  # type: ignore[arg-type]
    (removed,) = (c for c in plan(new, old).changes if c.subject.startswith("quality:"))  # type: ignore[arg-type]
    relaxed = plan_ir.quality_rule(column_name="amount", on_fail=OnFail.FLAG)
    (changed,) = plan(new, plan_ir.project(entities=(plan_ir.entity(quality=(relaxed,)),))).changes  # type: ignore[arg-type]

    assert (added.action, added.member) == (ChangeAction.ADDED, "amount")
    assert (removed.action, removed.member) == (ChangeAction.REMOVED, "amount")
    assert (changed.action, changed.member) == (ChangeAction.CHANGED, "amount")


def test_an_entity_level_rule_judges_no_one_field() -> None:
    rule = plan_ir.quality_rule("order_item_rows", kind="expression", column_name=None)
    old = plan_ir.project(entities=(plan_ir.entity(),))
    new = plan_ir.project(entities=(plan_ir.entity(quality=(rule,)),))

    (added,) = (c for c in plan(old, new).changes if c.subject.startswith("quality:"))  # type: ignore[arg-type]

    assert added.member is None


def test_a_new_mart_column_reported_twice_names_one_member_in_both() -> None:
    """The flattened column and the dimension it serves are two entries,
    one column: the pair `(subject, member)` says so."""
    base = build_project_ir(*load_fixture("ecom_basic"))
    _project, catalog = load_fixture("ecom_basic")
    sources = dict(fixture_sources("ecom_basic"))
    for key, old_text, new_text in (
        (
            "entity_model",
            "      customer_id: {type: string, classification: pii}\n",
            "      customer_id: {type: string, classification: pii}\n      channel: {type: string}\n",
        ),
        (
            "mapping_orders",
            '  customer_id: {from: "$.customer.id", transform: [to_string]}\n',
            '  customer_id: {from: "$.customer.id", transform: [to_string]}\n'
            '  channel: {from: "$.channel"}\n',
        ),
    ):
        assert sources[key].count(old_text) == 1, old_text
        sources[key] = sources[key].replace(old_text, new_text)

    result = plan(base, build_project_ir(load_project(sources), catalog))
    on_marts = {
        change.detail: change for change in result.changes if change.subject.startswith("mart:")
    }

    flattened = on_marts["flattened column 'order_channel' added"]
    dimension = on_marts["dimension 'order_channel' added"]
    assert (flattened.subject, flattened.member) == (dimension.subject, dimension.member)
    assert flattened.member == "order_channel"
    assert flattened.action is dimension.action is ChangeAction.ADDED


def test_a_flattened_column_whose_type_alone_moved_is_retyped() -> None:
    def over(column: object) -> object:
        return plan_ir.project(marts=(plan_ir.mart(columns=(column,)),))  # type: ignore[arg-type]

    def on_the_column(old: object, new: object) -> Change:
        (change,) = (
            c
            for c in plan(over(old), over(new)).changes  # type: ignore[arg-type]
            if c.detail.startswith("flattened column")
        )
        return change

    retyped = on_the_column(
        plan_ir.mart_column("amount", type_=parse_type("int", source_path="t")),
        plan_ir.mart_column("amount", type_=parse_type("decimal(12,2)", source_path="t")),
    )
    moved = on_the_column(
        plan_ir.mart_column("amount"), plan_ir.mart_column("amount", source_column="total")
    )

    assert (retyped.action, retyped.member, retyped.old, retyped.new) == (
        ChangeAction.RETYPED,
        "amount",
        "int",
        "decimal(12,2)",
    )
    assert retyped.detail == "flattened column 'amount' retyped"
    assert (moved.action, moved.detail) == (
        ChangeAction.CHANGED,
        "flattened column 'amount' changed",
    )


def test_the_cli_still_prints_the_advice_after_the_sentence() -> None:
    old = _incremental(plan_ir.column("id", required=True))
    new = _incremental(plan_ir.column("id", required=True), plan_ir.column("note"))

    rendered = render_plan(plan(old, new))  # type: ignore[arg-type]

    assert "field added; on dbt, run `dbt build --full-refresh -s order_item`" in rendered


def test_a_change_built_by_position_reads_as_a_change_with_no_member() -> None:
    change = Change(None, "metric:revenue", ChangeClass.RESTATING, "definition changed")

    assert (change.action, change.member, change.advice) == (ChangeAction.CHANGED, None, ())
