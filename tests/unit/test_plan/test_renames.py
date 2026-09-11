"""A node rename is one change, not a delete and an add (RFC 0062 P2, §5.3).

The identity `plan()` needs is not in the IR: RFC 0062 P1 substitutes the
authored `id:` while building node ids and keeps only names, because a field
there would move every fingerprint in the corpus and break that document's D3.
So it arrives as a label map per side, and passing none reproduces today's
report exactly — which is the half of D3 these tests have to hold as hard as
the other.

Projects here are the corpus's own, edited in their source text. A rename is a
whole-project edit — the definition moves *and* every reference to it does —
and hand-building two IRs would let a test declare a rename that no spec could
actually express.
"""

from __future__ import annotations

import re

import pytest

from dataclasses import replace

from bloomery import (
    build_project_ir,
    load_catalog,
    load_project,
    node_labels,
    plan,
)
from bloomery.ir import (
    Determinism,
    Lineage,
    ProjectIR,
    StepColumnIR,
    StepIR,
    StepKind,
    StepOutputIR,
)
from bloomery.typing import StringType
from bloomery.errors import GuardrailError
from support.compiling import (
    FIXTURES,
    fixture_sources,
    load_fixture,
    spec_fixture_names,
)
from support.steps import registry_for

pytestmark = pytest.mark.unit


def sides(
    fixture: str, was: str, now: str, *, mint: str = "mtr_7f3a9c", adopt: bool = True
) -> tuple[object, object, dict[str, str], dict[str, str]]:
    """Two compiles of one fixture, the second with ``was`` renamed to ``now``.

    The id is minted on **both** sides, because that is what a write-once id
    means: it was there before the rename and it is there after. Minting it
    only on the new side is the delete-and-add this feature exists to
    distinguish from a rename, and `adopt=False` is how a test asks for that.
    """
    sources = fixture_sources(fixture)
    catalog_text = (FIXTURES / fixture / "catalog.yaml").read_text()
    anchor = f"  {was}:\n"
    assert anchor in sources["metrics"], was

    old_sources = (
        {**sources, "metrics": sources["metrics"].replace(anchor, f"{anchor}    id: {mint}\n", 1)}
        if adopt
        else dict(sources)
    )
    # On word boundaries, because a metric name is routinely a substring of
    # another one — `period_over_period` has `revenue` and `paid_revenue` — and
    # a blunt replace renames both, which is a defect in the *test* that reads
    # exactly like a defect in the relabelling.
    pattern = re.compile(rf"\b{re.escape(was)}\b")
    new_sources = {key: pattern.sub(now, text) for key, text in old_sources.items()}
    new_catalog_text = pattern.sub(now, catalog_text)

    old_project, old_catalog = load_project(old_sources), load_catalog(catalog_text)
    new_project, new_catalog = load_project(new_sources), load_catalog(new_catalog_text)
    steps = registry_for(fixture)

    return (
        build_project_ir(old_project, catalog=old_catalog, steps=steps),
        build_project_ir(new_project, catalog=new_catalog, steps=steps),
        node_labels(old_project, old_catalog),
        node_labels(new_project, new_catalog),
    )


def classes(result: object) -> list[tuple[str, str]]:
    return [(change.change_class.value, change.subject) for change in result.changes]


# ....................... #
# §6's pair: a rename is a rename, and a delete is still a delete


def test_a_rename_is_one_change_and_no_deletions() -> None:
    """§6's first test, and the claim §2 says the current report gets backwards.

    A rename reaches everything that *names* the metric and nothing that uses
    it, so the report is one change, no backfill, and no restatement: every
    number the metric reported still means what it meant.
    """
    old, new, old_labels, new_labels = sides("ecom_basic", "gross_revenue", "revenue_gross")
    result = plan(old, new, old_labels=old_labels, new_labels=new_labels)

    assert classes(result) == [("rename", "metric:revenue_gross")]
    assert result.changes[0].old == "gross_revenue"
    assert result.changes[0].new == "revenue_gross"
    assert result.backfill_scope.entities == ()
    assert result.backfill_scope.restates_history is False


def test_a_delete_is_still_a_delete() -> None:
    """§6's second test, and the pair is the whole point: the two edits produce
    the same *shape* of IR difference, and only the id separates them.

    The metric is removed along with everything that referenced it, which is
    what a project actually has to do to delete one.
    """
    sources = fixture_sources("ecom_basic")
    catalog_text = (FIXTURES / "ecom_basic" / "catalog.yaml").read_text()
    old_project = load_project(
        {
            **sources,
            "metrics": sources["metrics"].replace(
                "  gross_revenue:\n", "  gross_revenue:\n    id: mtr_7f3a9c\n", 1
            ),
        }
    )
    catalog = load_catalog(catalog_text)
    # Drop the metric and everything naming it: the mart measure, the derived
    # ratio, and the exposure's dependency.
    without = fixture_sources("ecom_basic")
    without["metrics"] = """
metrics_version: 1
metrics:
  order_count:
    grain: order
    additivity: additive
    agg: count
    expr: "order_id"
"""
    without["marts"] = without["marts"].replace("measures: [gross_revenue]", "measures: []")
    without["exposures"] = without["exposures"].replace(
        "metrics: [gross_revenue, order_count]", "metrics: [order_count]"
    )
    new_project = load_project(without)

    result = plan(
        build_project_ir(old_project, catalog=catalog),
        build_project_ir(new_project, catalog=catalog),
        old_labels=node_labels(old_project, catalog),
        new_labels=node_labels(new_project, catalog),
    )

    assert ("breaking", "metric:gross_revenue") in classes(result)
    assert not any(kind == "rename" for kind, _ in classes(result))


def test_a_rename_without_an_id_on_both_sides_is_a_delete_and_an_add() -> None:
    """Identity is declared, never inferred (D1). Two metrics of the same shape
    under two names are two metrics, and no similarity over names, SQL or
    column sets says otherwise — a wrong guess here rewrites history."""

    old, new, old_labels, new_labels = sides(
        "ecom_basic", "gross_revenue", "revenue_gross", adopt=False
    )
    result = plan(old, new, old_labels=old_labels, new_labels=new_labels)

    assert old_labels == {} and new_labels == {}
    assert ("breaking", "metric:gross_revenue") in classes(result)
    assert ("additive", "metric:revenue_gross") in classes(result)


# ....................... #
# The citation list (§5.3)


def test_the_rename_carries_what_cited_the_old_name() -> None:
    """§5.3's "with the citation list rather than with a severity".

    Three kinds of consumer in one fixture, which is why this one: a metric
    whose ratio reads it, a mart carrying it as a measure, and an exposure
    declaring it. Each has to be edited and none of them restates.
    """
    old, new, old_labels, new_labels = sides("ecom_basic", "gross_revenue", "revenue_gross")
    result = plan(old, new, old_labels=old_labels, new_labels=new_labels)

    assert result.changes[0].citations == (
        "exposure:weekly_revenue_review",
        "mart:order_items",
        "metric:average_order_value",
    )


def test_every_other_change_carries_no_citations() -> None:
    """The field is a rename's, and a defaulted field that quietly filled for
    other classes would make the section under it meaningless."""

    old, new, old_labels, new_labels = sides("ecom_basic", "gross_revenue", "revenue_gross")
    plain = plan(old, new)

    assert plain.changes, "the unlabelled report is the one with several changes"
    assert all(change.citations == () for change in plain.changes)


# ....................... #
# D3: passing no labels is today's report, exactly


def test_without_labels_the_report_is_unchanged() -> None:
    """The half of D3 that lives in this phase. A caller that adopted nothing
    passes nothing, and every classification, detail and scope is what it was —
    asserted against the same diff run with empty maps rather than against a
    transcription of it."""

    old, new, _old_labels, _new_labels = sides("ecom_basic", "gross_revenue", "revenue_gross")

    assert plan(old, new) == plan(old, new, old_labels={}, new_labels={})


# ....................... #
# Steps (§5.3's other reachable kind)


def test_a_renamed_step_is_a_rename() -> None:
    """`node_keys` mints ids for three kinds and `plan()` diffs two of them.

    **No spec edit can express this one**, which is why the IRs are built by
    hand here and nowhere else in this file. A step node is keyed by `ref`, and
    a wiring's ref *is* its `use:` — the manifest it runs. Changing it is not a
    relabelling, it is pointing at different code, and the registry refuses a
    ref no manifest declares. The producer is written for the kind rather than
    for the metric because `node_keys` files three kinds and a second producer
    that handled one of them would be a rule wearing a special case; this pins
    that it works if a spelling for a step label ever exists.
    """
    old_step = StepIR(
        ref="resolve_customers",
        version=4,
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
    )
    old = ProjectIR(steps=(old_step,))
    new = ProjectIR(steps=(replace(old_step, ref="resolve_people"),))

    result = plan(
        old,
        new,
        old_labels={"step.stp_44c1": "resolve_customers"},
        new_labels={"step.stp_44c1": "resolve_people"},
    )

    assert classes(result) == [("rename", "step:resolve_people")]
    # Nothing in the compiler cites a step by ref — a wiring binds another
    # step's *output relation*, not its ref — so the list is empty and says so.
    assert result.changes[0].citations == ()


# ....................... #
# The sweep that proves the relabelling is total


#: The two fixtures that exist to be refused, so they reach no IR and cannot be
#: swept. Named rather than caught: a `try/except` around the sweep passes just
#: as green on the day a fixture that used to compile stopped.
REFUSED_AT_GUARDRAILS = frozenset({"fanout_trap", "scd2_mart_refusal"})


@pytest.mark.parametrize("fixture", spec_fixture_names())
def test_a_rename_is_the_only_change_it_reports(fixture: str) -> None:
    """Every fixture that has a metric, renamed, must report exactly one change.

    This is the guard that makes `_relabel` trustworthy rather than merely
    written. A reference field it misses does not raise: the consumer holding
    that reference reports a *restatement*, which schedules a backfill for a
    rename — the exact failure §2 says the current report makes. Reading the
    substitution against the IR's fields would be checking my own list against
    my own list; this checks it against every project shape the corpus has.

    The metric name comes from the loaded project rather than from parsing the
    document, and the **last** one is taken: a name that is a prefix of another
    would rename both, and sorting puts the longest suffix-sharing name last —
    `period_over_period` has `revenue` and `paid_revenue`, and picking the
    first found the bug in this harness rather than in the code.
    """
    if fixture in REFUSED_AT_GUARDRAILS:
        project, catalog = load_fixture(fixture)
        with pytest.raises(GuardrailError):
            build_project_ir(project, catalog=catalog, steps=registry_for(fixture))
        return

    project, _catalog = load_fixture(fixture)
    if project.metric_set is None or not project.metric_set.metrics:
        pytest.skip("no metric to rename")

    was = sorted(project.metric_set.metrics)[-1]
    old, new, old_labels, new_labels = sides(fixture, was, f"{was}_renamed")
    result = plan(old, new, old_labels=old_labels, new_labels=new_labels)

    assert classes(result) == [("rename", f"metric:{was}_renamed")]
