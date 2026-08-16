"""Every classification branch of the differ (RFC 0007 §5.2–§5.4, D3–D7):
one minimal IR pair per precedence rule, both ``ContractViolation`` arms,
rename validation including staleness, and the metric/mart/relationship/
date-dimension walks."""

from __future__ import annotations

from dataclasses import replace

import pytest
from support import plan_ir
from support.ir_factory import build_project_ir as factory_ir

from bloomery.errors import ContractViolation, PlanError, RenameTargetMissing
from bloomery.plan.diff import _reject_source  # pyright: ignore[reportPrivateUsage]
from bloomery.ir import (
    AuditIR,
    Cardinality,
    DateDimensionIR,
    DimensionRef,
    MartDimensionIR,
    MartJoinIR,
    Materialization,
    PartitionSpec,
    RelationshipIR,
    SCDKind,
    SourceFieldIR,
    TaxBasis,
    TransformStepIR,
    Unit,
    UnreachableMetric,
)
from bloomery.plan import Change, ChangeClass, plan
from bloomery.typing import DecimalType, IntType, StringType, TimestampType, VariantType

pytestmark = pytest.mark.unit


def entity_project(*columns: object, **entity_kwargs: object) -> object:
    return plan_ir.project(
        entities=(plan_ir.entity(columns=tuple(columns) or None, **entity_kwargs),)  # type: ignore[arg-type]
    )


def only_change(old: object, new: object) -> Change:
    result = plan(old, new)  # type: ignore[arg-type]
    assert len(result.changes) == 1, result.changes
    return result.changes[0]


# ....................... #
# Identity and initial deploy (D2)


def test_identical_projects_yield_the_empty_plan() -> None:
    ir = factory_ir()
    result = plan(ir, ir)
    assert not result.has_changes
    assert result.changes == ()
    assert result.backfill_scope.entities == ()
    assert not result.backfill_scope.restates_history
    assert result.downstream_impact == ()


def test_initial_deploy_classifies_everything_additive() -> None:
    ir = factory_ir()
    result = plan(None, ir)
    assert result.has_changes
    assert {change.change_class for change in result.changes} == {ChangeClass.ADDITIVE}
    assert result.breaking == ()
    assert result.backfill_scope.entities == ()
    assert not result.backfill_scope.restates_history
    assert result.downstream_impact == ()
    subjects = {change.subject for change in result.changes}
    assert "entity:order_item" in subjects
    assert "field:unit_price" in subjects
    assert "metric:gross_revenue" in subjects
    assert "mart:order_items" in subjects
    assert "relationship:item_of_order" in subjects
    assert "date_dimension:dim_date" in subjects


def test_plan_is_deterministic_for_the_same_pair() -> None:
    old, new = plan_ir.project(), factory_ir()
    assert plan(old, new) == plan(old, new)


def test_ir_version_mismatch_is_refused() -> None:
    old = replace(plan_ir.project(), bloomery_ir_version=1)
    with pytest.raises(PlanError, match="IR version"):
        plan(old, plan_ir.project())


# ....................... #
# Column presence (§5.2 rule 4)


def test_new_optional_column_is_additive() -> None:
    old = entity_project(plan_ir.column("id", required=True))
    new = entity_project(plan_ir.column("id", required=True), plan_ir.column("note"))
    change = only_change(old, new)
    assert change == Change(
        "order_item", "field:note", ChangeClass.ADDITIVE, "field added", new="string, optional"
    )


def test_new_required_column_on_an_existing_entity_is_breaking() -> None:
    old = entity_project(plan_ir.column("id", required=True))
    new = entity_project(
        plan_ir.column("id", required=True), plan_ir.column("code", required=True)
    )
    change = only_change(old, new)
    assert change.change_class is ChangeClass.BREAKING
    assert change.subject == "field:code"
    assert "add it optional, backfill, then tighten" in change.detail


def test_new_entity_with_required_columns_is_additive() -> None:
    old = plan_ir.project(entities=(plan_ir.entity("order"),))
    new = plan_ir.project(
        entities=(
            plan_ir.entity("order"),
            plan_ir.entity("customer", columns=(plan_ir.column("id", required=True),)),
        )
    )
    result = plan(old, new)
    assert {change.change_class for change in result.changes} == {ChangeClass.ADDITIVE}
    assert {change.subject for change in result.changes} == {"entity:customer", "field:id"}


def test_dropped_unreferenced_column_is_breaking_not_raised() -> None:
    old = entity_project(plan_ir.column("id", required=True), plan_ir.column("note"))
    new = entity_project(plan_ir.column("id", required=True))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.BREAKING
    assert change.subject == "field:note"
    assert change.detail == "field dropped"


def test_dropped_column_hints_renamed_from_when_a_same_typed_field_appears() -> None:
    old = entity_project(plan_ir.column("id", required=True), plan_ir.column("note"))
    new = entity_project(plan_ir.column("id", required=True), plan_ir.column("comment"))
    result = plan(old, new)
    dropped = next(c for c in result.changes if c.subject == "field:note")
    assert "renamed_from: 'note'" in dropped.detail
    assert "'comment'" in dropped.detail


def test_dropped_entity_is_one_breaking_entity_change() -> None:
    old = plan_ir.project(entities=(plan_ir.entity("order"), plan_ir.entity("customer")))
    new = plan_ir.project(entities=(plan_ir.entity("order"),))
    change = only_change(old, new)
    assert change == Change(
        "customer", "entity:customer", ChangeClass.BREAKING, "entity dropped (1 fields)"
    )


# ....................... #
# Types (§5.2 rule 2, D7 — the RFC 0004 lattice)


def test_widened_decimal_is_widening() -> None:
    old = entity_project(plan_ir.column("amount", type_=DecimalType(10, 2)))
    new = entity_project(plan_ir.column("amount", type_=DecimalType(12, 4)))
    change = only_change(old, new)
    assert change == Change(
        "order_item",
        "field:amount",
        ChangeClass.WIDENING,
        "type widened",
        old="decimal(10,2), optional",
        new="decimal(12,4), optional",
    )


def test_widening_to_variant_is_widening() -> None:
    old = entity_project(plan_ir.column("payload", type_=IntType()))
    new = entity_project(plan_ir.column("payload", type_=VariantType()))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.WIDENING
    assert (change.old, change.new) == ("int, optional", "variant, optional")


def test_narrowed_decimal_is_breaking() -> None:
    old = entity_project(plan_ir.column("amount", type_=DecimalType(12, 4)))
    new = entity_project(plan_ir.column("amount", type_=DecimalType(10, 2)))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.BREAKING
    assert change.detail == "type narrowed"


def test_incompatible_type_change_is_breaking() -> None:
    old = entity_project(plan_ir.column("seen_at", type_=TimestampType()))
    new = entity_project(plan_ir.column("seen_at", type_=StringType()))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.BREAKING
    assert (change.old, change.new) == ("timestamp, optional", "string, optional")


def test_optional_to_required_is_breaking() -> None:
    old = entity_project(plan_ir.column("id", required=True), plan_ir.column("code"))
    new = entity_project(plan_ir.column("id", required=True), plan_ir.column("code", required=True))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.BREAKING
    assert change.detail == "optional field became required"


def test_required_to_optional_is_widening() -> None:
    old = entity_project(plan_ir.column("id", required=True), plan_ir.column("code", required=True))
    new = entity_project(plan_ir.column("id", required=True), plan_ir.column("code"))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.WIDENING
    assert change.detail == "required field became optional"


def test_narrowing_and_tightening_report_both_facets_in_one_breaking_change() -> None:
    old = entity_project(plan_ir.column("id", required=True), plan_ir.column("amount", type_=DecimalType(12, 4)))
    new = entity_project(
        plan_ir.column("id", required=True),
        plan_ir.column("amount", type_=DecimalType(10, 2), required=True),
    )
    change = only_change(old, new)
    assert change.change_class is ChangeClass.BREAKING
    assert change.detail == "type narrowed and optional field became required"


def test_type_change_takes_precedence_over_semantic_change() -> None:
    old = entity_project(plan_ir.column("amount", type_=DecimalType(10, 2), recipe_id="direct"))
    new = entity_project(plan_ir.column("amount", type_=DecimalType(12, 4), recipe_id="from_total"))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.WIDENING  # §5.2: type before semantics


# ....................... #
# Semantics — RESTATING (§5.2 rule 3, D4)


@pytest.mark.parametrize(
    ("facet", "old_column", "new_column"),
    [
        ("canonical", {"canonical": "gross"}, {"canonical": "net"}),
        ("recipe", {"recipe_id": "direct"}, {"recipe_id": "from_total"}),
        ("expression", {"expr": "a"}, {"expr": "b"}),
        ("unit", {"unit": Unit.CURRENCY}, {"unit": Unit.COUNT}),
        ("tax_basis", {"tax_basis": None}, {"tax_basis": TaxBasis.NET}),
    ],
)
def test_semantic_changes_are_restating_with_backfill(
    facet: str, old_column: dict[str, object], new_column: dict[str, object]
) -> None:
    old = entity_project(plan_ir.column("amount", **old_column))  # type: ignore[arg-type]
    new = entity_project(plan_ir.column("amount", **new_column))  # type: ignore[arg-type]
    result = plan(old, new)
    (change,) = result.changes
    assert change.change_class is ChangeClass.RESTATING
    assert facet in change.detail
    assert result.backfill_scope.entities == ("order_item",)
    assert result.backfill_scope.restates_history


def test_changed_source_path_is_restating() -> None:
    old = entity_project(
        plan_ir.column("amount"),
        source_fields=(SourceFieldIR(target_field="amount", source_path="$.price"),),
    )
    new = entity_project(
        plan_ir.column("amount"),
        source_fields=(SourceFieldIR(target_field="amount", source_path="$.total"),),
    )
    change = only_change(old, new)
    assert change.change_class is ChangeClass.RESTATING
    assert "source" in change.detail


def test_changed_transform_chain_is_restating() -> None:
    old = entity_project(
        plan_ir.column("amount"),
        source_fields=(
            SourceFieldIR(
                target_field="amount",
                source_path="$.price",
                transform=(TransformStepIR(name="to_int"),),
            ),
        ),
    )
    new = entity_project(
        plan_ir.column("amount"),
        source_fields=(
            SourceFieldIR(
                target_field="amount",
                source_path="$.price",
                transform=(TransformStepIR(name="to_string"),),
            ),
        ),
    )
    change = only_change(old, new)
    assert change.change_class is ChangeClass.RESTATING


def test_description_only_change_is_additive_metadata() -> None:
    old = entity_project(plan_ir.column("amount"))
    new = entity_project(plan_ir.column("amount", description="net amount"))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.ADDITIVE
    assert "metadata only" in change.detail


# ....................... #
# Entity-level BREAKING (§5.2 rule 1, D7)


@pytest.mark.parametrize(
    ("label", "kwargs"),
    [
        ("grain", {"grain": "one row per something else"}),
        ("key", {"key": ("id", "line_no")}),
        ("scd", {"scd": SCDKind.TYPE2}),
        ("materialization", {"materialization": Materialization.INCREMENTAL_BY_KEY}),
    ],
)
def test_entity_redefinition_is_breaking_at_the_entity_subject(
    label: str, kwargs: dict[str, object]
) -> None:
    old = plan_ir.project(entities=(plan_ir.entity(),))
    new = plan_ir.project(entities=(plan_ir.entity(**kwargs),))  # type: ignore[arg-type]
    change = only_change(old, new)
    assert change.change_class is ChangeClass.BREAKING
    assert change.subject == "entity:order_item"
    assert change.detail == f"{label} changed"


def test_entity_breaking_still_reports_column_diffs_alongside() -> None:
    old = plan_ir.project(entities=(plan_ir.entity(),))
    new = plan_ir.project(
        entities=(
            plan_ir.entity(
                scd=SCDKind.TYPE2,
                columns=(plan_ir.column("id", required=True), plan_ir.column("note")),
            ),
        )
    )
    result = plan(old, new)
    by_subject = {change.subject: change.change_class for change in result.changes}
    assert by_subject == {
        "entity:order_item": ChangeClass.BREAKING,
        "field:note": ChangeClass.ADDITIVE,
    }


def test_changed_source_relation_is_restating_at_the_entity_subject() -> None:
    old = plan_ir.project(entities=(plan_ir.entity(relation="raw__a"),))
    new = plan_ir.project(entities=(plan_ir.entity(relation="raw__b"),))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.RESTATING
    assert change.subject == "entity:order_item"
    assert (change.old, change.new) == ("raw__a", "raw__b")
    assert plan(old, new).backfill_scope.entities == ("order_item",)


# ....................... #
# The union merge's source set (RFC 0024 §5.5, D9). No new change class: the
# table falls out of the existing classifier, which is one of the three reasons
# RFC 0021's reusable question answers "yes" for this feature.


def test_the_reject_schema_diff_says_so_when_the_invariant_stops_holding() -> None:
    """`quarantine:` is refused on a merged entity (RFC 0024 D14), so the reject
    schema is always one mapping's — but written as `sources[0]` that reads as a
    choice among branches. The guard is exercised so its message is known to be
    right on the day P2 lifts D14."""
    merged = plan_ir.entity(relation="raw__a", merged_with=("raw__b",))
    with pytest.raises(PlanError) as excinfo:
        _reject_source(merged)
    message = str(excinfo.value)
    assert "2 sources" in message
    assert "RFC 0024 D14" in message


def test_a_mapping_added_to_a_single_source_entity_is_additive() -> None:
    old = plan_ir.project(entities=(plan_ir.entity(relation="raw__a"),))
    new = plan_ir.project(entities=(plan_ir.entity(relation="raw__a", merged_with=("raw__b",)),))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.ADDITIVE
    assert change.subject == "entity:order_item"
    assert "raw__b" in change.detail
    # D9's second half: the transition is a schema move, and an operator should
    # see it in `plan()` before it lands rather than discover the column later.
    assert "_source" in change.detail
    # New rows, and a column that is a constant per branch — nothing stored
    # restates.
    assert plan(old, new).backfill_scope.entities == ()


def test_a_mapping_added_to_an_already_merged_entity_does_not_re_announce_source() -> None:
    old = plan_ir.project(entities=(plan_ir.entity(relation="raw__a", merged_with=("raw__b",)),))
    new = plan_ir.project(
        entities=(plan_ir.entity(relation="raw__a", merged_with=("raw__b", "raw__c")),)
    )
    change = only_change(old, new)
    assert change.change_class is ChangeClass.ADDITIVE
    assert "raw__c" in change.detail
    assert "_source" not in change.detail  # already present


def test_a_mapping_removed_leaving_two_is_restating() -> None:
    old = plan_ir.project(
        entities=(plan_ir.entity(relation="raw__a", merged_with=("raw__b", "raw__c")),)
    )
    new = plan_ir.project(entities=(plan_ir.entity(relation="raw__a", merged_with=("raw__b",)),))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.RESTATING
    assert "raw__c" in change.detail
    assert "_source" not in change.detail  # two sources remain, so it stays
    # Same columns, fewer rows — the relation must be rebuilt.
    assert plan(old, new).backfill_scope.entities == ("order_item",)


def test_a_mapping_removed_leaving_one_drops_the_source_column() -> None:
    """The sharp row of §5.5's table, and the one D9 asks to verify."""
    old = plan_ir.project(entities=(plan_ir.entity(relation="raw__a", merged_with=("raw__b",)),))
    new = plan_ir.project(entities=(plan_ir.entity(relation="raw__a"),))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.RESTATING
    assert "raw__b" in change.detail
    assert "_source" in change.detail
    assert plan(old, new).backfill_scope.entities == ("order_item",)


def test_a_swap_reports_the_addition_and_the_removal_separately() -> None:
    """Two facts, two changes: an operator adding one shop while retiring
    another needs to see both, and the classes differ."""
    old = plan_ir.project(entities=(plan_ir.entity(relation="raw__a", merged_with=("raw__b",)),))
    new = plan_ir.project(entities=(plan_ir.entity(relation="raw__a", merged_with=("raw__c",)),))
    classes = {change.detail: change.change_class for change in plan(old, new).changes}
    assert len(classes) == 2
    assert {change_class for change_class in classes.values()} == {
        ChangeClass.ADDITIVE,
        ChangeClass.RESTATING,
    }


def test_partition_and_audit_changes_are_additive_metadata() -> None:
    old = plan_ir.project(entities=(plan_ir.entity(),))
    new = plan_ir.project(
        entities=(
            plan_ir.entity(
                partition_by=(PartitionSpec(transform="days", column="id"),),
                audits=(AuditIR(kind="not_null", column="id"),),
            ),
        )
    )
    result = plan(old, new)
    assert {change.change_class for change in result.changes} == {ChangeClass.ADDITIVE}
    details = sorted(change.detail for change in result.changes)
    assert details == ["audits changed (metadata only)", "partition_by changed (metadata only)"]


# ....................... #
# Explicit rename (§5.3, D3)


def test_annotated_rename_is_one_rename_change_with_no_backfill() -> None:
    # The lowered expr is source-derived, so a pure rename keeps it intact.
    old = entity_project(plan_ir.column("id", required=True), plan_ir.column("quantity", expr="q"))
    new = entity_project(
        plan_ir.column("id", required=True),
        plan_ir.column("qty", expr="q", renamed_from="quantity"),
    )
    result = plan(old, new)
    assert result.changes == (
        Change(
            "order_item",
            "field:qty",
            ChangeClass.RENAME,
            "renamed from 'quantity'",
            old="quantity",
            new="qty",
        ),
    )
    assert result.backfill_scope.entities == ()
    assert result.downstream_impact == ()


def test_rename_with_widening_reports_both_records() -> None:
    old = entity_project(plan_ir.column("qty", type_=DecimalType(10, 2)))
    new = entity_project(
        plan_ir.column("quantity_units", type_=DecimalType(12, 2), renamed_from="qty")
    )
    result = plan(old, new)
    classes = [change.change_class for change in result.changes]
    assert sorted(classes) == sorted([ChangeClass.RENAME, ChangeClass.WIDENING])
    assert {change.subject for change in result.changes} == {"field:quantity_units"}


def test_stale_annotation_raises_when_old_is_none() -> None:
    new = entity_project(plan_ir.column("qty", renamed_from="quantity"))
    with pytest.raises(RenameTargetMissing, match="stale"):
        plan(None, new)


def test_stale_annotation_raises_when_the_old_name_never_existed() -> None:
    old = entity_project(plan_ir.column("qty"))
    new = entity_project(plan_ir.column("qty", renamed_from="ghost"))
    with pytest.raises(RenameTargetMissing, match="'ghost'"):
        plan(old, new)


def test_stale_annotation_raises_for_a_new_entity() -> None:
    old = plan_ir.project(entities=(plan_ir.entity("order"),))
    new = plan_ir.project(
        entities=(
            plan_ir.entity("order"),
            plan_ir.entity("customer", columns=(plan_ir.column("qty", renamed_from="quantity"),)),
        )
    )
    with pytest.raises(RenameTargetMissing):
        plan(old, new)


def test_already_applied_annotation_is_identity_not_stale() -> None:
    annotated = entity_project(plan_ir.column("qty", renamed_from="quantity"))
    assert not plan(annotated, annotated).has_changes


def test_rename_with_both_names_present_is_refused() -> None:
    old = entity_project(plan_ir.column("quantity"))
    new = entity_project(
        plan_ir.column("quantity"), plan_ir.column("qty", renamed_from="quantity")
    )
    with pytest.raises(PlanError, match="both names"):
        plan(old, new)


def test_rename_onto_a_preexisting_column_is_refused_as_ambiguous() -> None:
    old = entity_project(plan_ir.column("quantity"), plan_ir.column("qty"))
    new = entity_project(plan_ir.column("qty", renamed_from="quantity"))
    with pytest.raises(PlanError, match="ambiguous"):
        plan(old, new)


# ....................... #
# Metrics


def test_added_and_removed_metrics_classify_additive_and_breaking() -> None:
    old = plan_ir.project(metrics=(plan_ir.metric("gone"), plan_ir.metric("kept")))
    new = plan_ir.project(metrics=(plan_ir.metric("kept"), plan_ir.metric("fresh")))
    result = plan(old, new)
    by_subject = {change.subject: change for change in result.changes}
    assert by_subject["metric:fresh"].change_class is ChangeClass.ADDITIVE
    assert by_subject["metric:gone"].change_class is ChangeClass.BREAKING
    assert by_subject["metric:gone"].detail == "metric removed"


def test_metric_that_became_unreachable_names_its_missing_leaves() -> None:
    old = plan_ir.project(metrics=(plan_ir.metric("margin"),))
    new = plan_ir.project(
        metrics=(), unreachable=(UnreachableMetric(name="margin", missing=("cogs",)),)
    )
    change = only_change(old, new)
    assert change.change_class is ChangeClass.BREAKING
    assert change.detail == "metric became unreachable (missing: cogs)"


def test_metric_grain_change_is_breaking() -> None:
    old = plan_ir.project(metrics=(plan_ir.metric("m", grain="order_item"),))
    new = plan_ir.project(metrics=(plan_ir.metric("m", grain="order"),))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.BREAKING
    assert (change.old, change.new) == ("order_item", "order")


def test_metric_definition_change_is_restating_without_entity_backfill() -> None:
    old = plan_ir.project(metrics=(plan_ir.metric("m", agg="sum"),))
    new = plan_ir.project(metrics=(plan_ir.metric("m", agg="max"),))
    result = plan(old, new)
    (change,) = result.changes
    assert change.change_class is ChangeClass.RESTATING
    assert result.backfill_scope.entities == ()  # nothing stored — metrics render at query time
    assert result.backfill_scope.restates_history
    assert result.downstream_impact == ("m",)


def test_metric_description_change_is_additive_metadata() -> None:
    old = plan_ir.project(metrics=(plan_ir.metric("m"),))
    new = plan_ir.project(metrics=(plan_ir.metric("m", description="net of tax"),))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.ADDITIVE


# ....................... #
# Downstream impact (D6 — MetricIR.depends_on closure)


def test_downstream_impact_walks_the_depends_on_closure() -> None:
    entity = plan_ir.entity(
        columns=(plan_ir.column("id", required=True), plan_ir.column("amount", canonical="amount"))
    )
    base = plan_ir.metric("base", depends_on=("amount",))
    derived = plan_ir.metric("derived", depends_on=("base",))
    unrelated = plan_ir.metric("unrelated", depends_on=("other",))
    old = plan_ir.project(entities=(entity,), metrics=(base, derived, unrelated))
    widened = plan_ir.entity(
        columns=(
            plan_ir.column("id", required=True),
            plan_ir.column("amount", canonical="amount", type_=VariantType()),
        )
    )
    new = plan_ir.project(entities=(widened,), metrics=(base, derived, unrelated))
    assert plan(old, new).downstream_impact == ("base", "derived")


def test_a_source_addition_reports_the_metrics_whose_numbers_move() -> None:
    """Adding a branch to a union merge changes no column's meaning and every
    metric's *value* — the entity's row population grew.

    That makes it the first ADDITIVE change in this differ that a metric
    consumer has to know about, and the sibling test below is why the
    distinction needs stating: a column *addition* seeds nothing because no
    existing number moves, and until now "ADDITIVE" and "no downstream impact"
    happened to coincide. `downstream_impact` is documented as "the metric
    names affected by any change", and a metric over a merged entity reports a
    different number the day the second shop lands.
    """
    columns = (plan_ir.column("id", required=True), plan_ir.column("amount", canonical="amount"))
    metrics = (plan_ir.metric("revenue", depends_on=("amount",)),)
    old = plan_ir.project(
        entities=(plan_ir.entity(columns=columns, relation="raw__a"),), metrics=metrics
    )
    new = plan_ir.project(
        entities=(plan_ir.entity(columns=columns, relation="raw__a", merged_with=("raw__b",)),),
        metrics=metrics,
    )
    result = plan(old, new)
    assert result.downstream_impact == ("revenue",)
    # Still ADDITIVE, and still no backfill — the classification is right, it
    # was only the impact set that was silent.
    (change,) = result.changes
    assert change.change_class is ChangeClass.ADDITIVE
    assert result.backfill_scope.entities == ()


def test_a_source_removal_reports_them_too() -> None:
    """The symmetric case, which already worked — a removal seeds through the
    `redefined` path. Pinned so the two directions cannot drift apart again."""
    columns = (plan_ir.column("id", required=True), plan_ir.column("amount", canonical="amount"))
    metrics = (plan_ir.metric("revenue", depends_on=("amount",)),)
    old = plan_ir.project(
        entities=(plan_ir.entity(columns=columns, relation="raw__a", merged_with=("raw__b",)),),
        metrics=metrics,
    )
    new = plan_ir.project(
        entities=(plan_ir.entity(columns=columns, relation="raw__a"),), metrics=metrics
    )
    assert plan(old, new).downstream_impact == ("revenue",)


def test_additive_changes_do_not_seed_downstream_impact() -> None:
    entity = plan_ir.entity(columns=(plan_ir.column("id", required=True),))
    grown = plan_ir.entity(
        columns=(plan_ir.column("id", required=True), plan_ir.column("note", canonical="note"))
    )
    metrics = (plan_ir.metric("m", depends_on=("note",)),)
    old = plan_ir.project(entities=(entity,), metrics=metrics)
    new = plan_ir.project(entities=(grown,), metrics=metrics)
    assert plan(old, new).downstream_impact == ()


# ....................... #
# Expand/contract (§5.4, D5) — the stage's only refusal


def test_dropping_a_field_a_live_metric_references_is_refused() -> None:
    old = entity_project(plan_ir.column("id", required=True), plan_ir.column("amount", canonical="amount"))
    new = plan_ir.project(
        entities=(plan_ir.entity(columns=(plan_ir.column("id", required=True),)),),
        metrics=(plan_ir.metric("revenue", depends_on=("amount",)),),
    )
    with pytest.raises(ContractViolation) as caught:
        plan(old, new)
    assert "order_item.amount" in str(caught.value)
    assert "revenue" in str(caught.value)


def test_narrowing_a_field_a_live_metric_references_is_refused() -> None:
    metrics = (plan_ir.metric("revenue", depends_on=("amount",)),)
    old = plan_ir.project(
        entities=(plan_ir.entity(columns=(plan_ir.column("amount", canonical="amount", type_=DecimalType(12, 4)),)),),
        metrics=metrics,
    )
    new = plan_ir.project(
        entities=(plan_ir.entity(columns=(plan_ir.column("amount", canonical="amount", type_=DecimalType(10, 2)),)),),
        metrics=metrics,
    )
    with pytest.raises(ContractViolation, match="narrowed"):
        plan(old, new)


def test_dropping_field_and_its_metric_together_is_refused() -> None:
    old = plan_ir.project(
        entities=(plan_ir.entity(columns=(plan_ir.column("amount", canonical="amount"),)),),
        metrics=(plan_ir.metric("revenue", depends_on=("amount",)),),
    )
    new = plan_ir.project(entities=(plan_ir.entity(columns=()),), metrics=())
    with pytest.raises(ContractViolation, match="revenue"):
        plan(old, new)


def test_dropping_an_unreferenced_field_is_breaking_but_returned() -> None:
    old = plan_ir.project(
        entities=(plan_ir.entity(columns=(plan_ir.column("amount"), plan_ir.column("note")),),),
        metrics=(plan_ir.metric("revenue", depends_on=("amount",)),),
    )
    new = plan_ir.project(
        entities=(plan_ir.entity(columns=(plan_ir.column("amount"),)),),
        metrics=(plan_ir.metric("revenue", depends_on=("amount",)),),
    )
    result = plan(old, new)
    assert [change.subject for change in result.breaking] == ["field:note"]


def test_tightening_required_does_not_trigger_the_contract() -> None:
    metrics = (plan_ir.metric("revenue", depends_on=("amount",)),)
    old = plan_ir.project(
        entities=(plan_ir.entity(columns=(plan_ir.column("amount", canonical="amount"),)),),
        metrics=metrics,
    )
    new = plan_ir.project(
        entities=(plan_ir.entity(columns=(plan_ir.column("amount", canonical="amount", required=True),)),),
        metrics=metrics,
    )
    result = plan(old, new)  # BREAKING, but reads are unaffected — no refusal
    assert [change.change_class for change in result.changes] == [ChangeClass.BREAKING]


# ....................... #
# Marts (RFC 0007 §12 amended phasing)


def test_added_and_dropped_marts() -> None:
    old = plan_ir.project(marts=(plan_ir.mart("gone"),))
    new = plan_ir.project(marts=(plan_ir.mart("fresh"),))
    result = plan(old, new)
    by_subject = {change.subject: change.change_class for change in result.changes}
    assert by_subject == {
        "mart:fresh": ChangeClass.ADDITIVE,
        "mart:gone": ChangeClass.BREAKING,
    }


@pytest.mark.parametrize(
    ("label", "kwargs"),
    [
        ("grain", {"grain": "order"}),
        ("base", {"base": "order"}),
        ("materialization", {"materialization": Materialization.INCREMENTAL_BY_KEY}),
    ],
)
def test_mart_redefinition_is_breaking_at_the_mart_subject(
    label: str, kwargs: dict[str, object]
) -> None:
    old = plan_ir.project(marts=(plan_ir.mart(),))
    new = plan_ir.project(marts=(plan_ir.mart(**kwargs),))  # type: ignore[arg-type]
    change = only_change(old, new)
    assert change.change_class is ChangeClass.BREAKING
    assert change.subject == "mart:items"
    assert change.detail == f"{label} changed"


def test_mart_flattened_column_changes() -> None:
    old = plan_ir.project(
        marts=(plan_ir.mart(columns=(plan_ir.mart_column("kept"), plan_ir.mart_column("gone"))),)
    )
    new = plan_ir.project(
        marts=(
            plan_ir.mart(
                columns=(
                    plan_ir.mart_column("kept", type_=IntType()),
                    plan_ir.mart_column("fresh"),
                )
            ),
        )
    )
    result = plan(old, new)
    by_detail = {change.detail: change.change_class for change in result.changes}
    assert by_detail == {
        "flattened column 'fresh' added": ChangeClass.ADDITIVE,
        "flattened column 'gone' dropped": ChangeClass.BREAKING,
        "flattened column 'kept' changed": ChangeClass.BREAKING,
    }


def test_mart_measure_growth_is_additive() -> None:
    old = plan_ir.project(marts=(plan_ir.mart(measures=("m1",)),))
    new = plan_ir.project(marts=(plan_ir.mart(measures=("m1", "m2")),))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.ADDITIVE
    assert change.detail == "measure 'm2' added"


def test_mart_measure_removal_is_breaking_when_the_metric_is_gone_too() -> None:
    old = plan_ir.project(
        marts=(plan_ir.mart(measures=("m1", "m2")),), metrics=(plan_ir.metric("m1"),)
    )
    new = plan_ir.project(marts=(plan_ir.mart(measures=("m1",)),), metrics=(plan_ir.metric("m1"),))
    change = only_change(old, new)
    assert change.change_class is ChangeClass.BREAKING
    assert change.detail == "measure 'm2' removed"


def test_mart_measure_removal_for_a_live_unserved_metric_is_refused() -> None:
    metrics = (plan_ir.metric("m2"),)
    old = plan_ir.project(marts=(plan_ir.mart(measures=("m2",)),), metrics=metrics)
    new = plan_ir.project(marts=(plan_ir.mart(measures=()),), metrics=metrics)
    with pytest.raises(ContractViolation, match="'m2'"):
        plan(old, new)


def test_mart_measure_removal_is_fine_when_another_mart_serves_it() -> None:
    metrics = (plan_ir.metric("m2"),)
    old = plan_ir.project(marts=(plan_ir.mart(measures=("m2",)),), metrics=metrics)
    new = plan_ir.project(
        marts=(plan_ir.mart(measures=()), plan_ir.mart("other", measures=("m2",))),
        metrics=metrics,
    )
    result = plan(old, new)  # no refusal: the metric is still served
    assert any(change.detail == "measure 'm2' removed" for change in result.changes)


def test_mart_dimension_and_join_changes_are_breaking() -> None:
    ref = DimensionRef(dimension="date", role="ordered")
    old = plan_ir.project(marts=(plan_ir.mart(),))
    new = plan_ir.project(
        marts=(
            plan_ir.mart(
                dimensions=(MartDimensionIR(ref=ref, column="ordered_day"),),
                joins=(MartJoinIR(relationship="r", entity="order", prefix="order_", on=(("a", "b"),)),),
            ),
        )
    )
    result = plan(old, new)
    assert sorted(change.detail for change in result.changes) == [
        "dimensions changed",
        "joins changed",
    ]
    assert {change.change_class for change in result.changes} == {ChangeClass.BREAKING}


def test_mart_partition_and_cost_hint_changes_are_additive_metadata() -> None:
    old = plan_ir.project(marts=(plan_ir.mart(),))
    new = plan_ir.project(
        marts=(
            plan_ir.mart(
                partition_by=(PartitionSpec(transform="days", column="ordered_day"),),
                cost_hint=3,
            ),
        )
    )
    result = plan(old, new)
    assert {change.change_class for change in result.changes} == {ChangeClass.ADDITIVE}
    assert sorted(change.detail for change in result.changes) == [
        "cost_hint changed (metadata only)",
        "partition_by changed (metadata only)",
    ]


# ....................... #
# Relationships and the date dimension


def test_relationship_add_drop_and_redefine() -> None:
    def rel(name: str, cardinality: Cardinality = Cardinality.MANY_TO_ONE) -> RelationshipIR:
        return RelationshipIR(
            name=name,
            from_entity="order_item",
            to_entity="order",
            via=(("order_id", "order_id"),),
            cardinality=cardinality,
        )

    old = plan_ir.project(relationships=(rel("gone"), rel("kept")))
    new = plan_ir.project(relationships=(rel("kept", Cardinality.ONE_TO_ONE), rel("fresh")))
    result = plan(old, new)
    by_subject = {change.subject: change.change_class for change in result.changes}
    assert by_subject == {
        "relationship:fresh": ChangeClass.ADDITIVE,
        "relationship:gone": ChangeClass.BREAKING,
        "relationship:kept": ChangeClass.BREAKING,
    }


def test_date_dimension_added_and_removed() -> None:
    dim = DateDimensionIR(name="dim_date", grain="day", start_year=2020, end_year=2030)
    added = only_change(plan_ir.project(), plan_ir.project(date_dimension=dim))
    assert added.change_class is ChangeClass.ADDITIVE
    removed = only_change(plan_ir.project(date_dimension=dim), plan_ir.project())
    assert removed.change_class is ChangeClass.BREAKING


def test_date_dimension_bounds_extension_is_additive_but_shrinking_is_breaking() -> None:
    dim = DateDimensionIR(name="dim_date", grain="day", start_year=2020, end_year=2030)
    extended = DateDimensionIR(name="dim_date", grain="day", start_year=2019, end_year=2031)
    shrunk = DateDimensionIR(name="dim_date", grain="day", start_year=2022, end_year=2030)
    grow = only_change(plan_ir.project(date_dimension=dim), plan_ir.project(date_dimension=extended))
    assert grow.change_class is ChangeClass.ADDITIVE
    assert (grow.old, grow.new) == ("2020-2030", "2019-2031")
    cut = only_change(plan_ir.project(date_dimension=dim), plan_ir.project(date_dimension=shrunk))
    assert cut.change_class is ChangeClass.BREAKING
