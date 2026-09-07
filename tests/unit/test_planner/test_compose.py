"""The composed branch join (RFC 0041 D9, D13), apart from the planner that
builds its inputs.

The statement this module writes is the only SQL bloomery generates for a
query — everything inside a branch is MetricFlow's — so what is asserted here
is the join shape, the null semantics and the projection, against branches
whose text is a placeholder. The end-to-end proof that the numbers are right
is corpus case `006-two-grains-one-request`, executed on DuckDB.
"""

from __future__ import annotations

import pytest

from bloomery.dialects import DialectFeature, get_dialect
from bloomery.errors import PlannerError
from bloomery.planner.compose import Branch, compose

pytestmark = pytest.mark.unit

# ----------------------- #

DIALECTS = ("duckdb", "postgres", "trino")


def _two() -> list[Branch]:
    return [
        Branch(sql="SELECT a AS order__region, SUM(x) AS ship FROM t", keys=("order__region",)),
        Branch(
            sql="SELECT b AS item__order_region, SUM(y) AS disc FROM u",
            keys=("item__order_region",),
        ),
    ]


# ....................... #


def test_the_answer_is_a_key_domain_every_branch_is_matched_back_onto() -> None:
    """Both halves of D13 in one statement: a group present on one branch only
    survives, and a NULL group meets the other branch's NULL group instead of
    failing `NULL = NULL`.

    A `UNION`ed key domain and left joins rather than a full outer join —
    PostgreSQL refuses `FULL JOIN … ON a IS NOT DISTINCT FROM b` outright, so
    the obvious composition is one a shipped dialect cannot run
    (logs/T-0026.md, D-171).
    """
    sql = compose(
        _two(), keys=("region",), measures=((0, "ship"), (1, "disc")), dialect=get_dialect("duckdb")
    )

    assert "FULL" not in sql
    assert "INNER JOIN" not in sql
    assert sql.count("LEFT JOIN") == 2
    assert "UNION\n" in sql and "UNION ALL" not in sql
    assert sql.count("IS NOT DISTINCT FROM") == 2


def test_the_key_is_projected_once_under_the_name_the_caller_asked_for() -> None:
    """Two marts spell one dimension two ways and the result has one column
    (logs/T-0026.md, D-165). Coalesced rather than taken from either side,
    since a full outer join leaves the other side's copy NULL for every group
    that side does not have."""
    sql = compose(
        _two(), keys=("region",), measures=((0, "ship"), (1, "disc")), dialect=get_dialect("duckdb")
    )

    assert "branch_keys.region AS region" in sql
    # Once in the projection, and once per branch in the key domain — never
    # read from a branch, whose copy is NULL for every group it does not have.
    assert sql.count(" AS region") == 1 + len(_two())


def test_every_branch_contributes_to_the_key_domain_and_is_matched_back() -> None:
    """The generalization a chain of pairwise joins gets wrong: with a key
    domain there is no "earlier branch" to compare against, so a group only
    the third branch has is in the answer for the same reason as any other."""
    branches = [
        Branch(sql="S0", keys=("k0",)),
        Branch(sql="S1", keys=("k1",)),
        Branch(sql="S2", keys=("k2",)),
    ]
    sql = compose(
        branches,
        keys=("region",),
        measures=((0, "a"), (1, "b"), (2, "c")),
        dialect=get_dialect("duckdb"),
    )

    for index in range(3):
        assert f"SELECT branch_{index}.k{index} AS region FROM branch_{index}" in sql
        assert f"ON branch_{index}.k{index} IS NOT DISTINCT FROM branch_keys.region" in sql


def test_an_ungrouped_request_is_a_cross_join_of_totals() -> None:
    """Each branch is one row of totals, so the answer is their cross product.
    There is no key domain to build, and inventing one would be a group nobody
    asked for."""
    branches = [Branch(sql="S0", keys=()), Branch(sql="S1", keys=())]
    sql = compose(
        branches, keys=(), measures=((0, "a"), (1, "b")), dialect=get_dialect("duckdb")
    )

    assert "CROSS JOIN" in sql
    assert "branch_keys" not in sql
    assert "LEFT JOIN" not in sql


def test_measures_are_projected_in_the_order_they_were_asked_for() -> None:
    """Branches are sorted by mart name so two runs compose the same query;
    a result's column order is the caller's, and the two are not the same
    order."""
    sql = compose(
        _two(), keys=("region",), measures=((1, "disc"), (0, "ship")), dialect=get_dialect("duckdb")
    )

    assert sql.index("branch_1.disc") < sql.index("branch_0.ship")


@pytest.mark.parametrize("dialect", DIALECTS)
def test_every_shipped_dialect_renders_one_statement(dialect: str) -> None:
    """D17 the way it is meant to be read: the null-safe spelling is a
    capability each dialect declares, and all three shipped ones have it and
    render it identically. Asserted rather than cited from documentation,
    which is what the decision says the citation is not worth."""
    port = get_dialect(dialect)
    sql = compose(
        _two(), keys=("region",), measures=((0, "ship"), (1, "disc")), dialect=port
    )

    assert port.supports(DialectFeature.NULL_SAFE_EQUALITY)
    assert "IS NOT DISTINCT FROM" in sql
    # Rendering is not running: `tests/engines/test_branch_join_engines.py`
    # executes this statement on PostgreSQL and Trino, which is where the
    # first shape of it was found to be unrunnable (D17).


def test_an_ungrouped_request_needs_no_null_safe_equality() -> None:
    """The capability is asked of the keyed join only. An ungrouped request
    composes to a `CROSS JOIN` of one-row totals and has no key to match, so
    refusing it on a dialect without the feature would refuse a statement that
    never needed it."""

    class _Narrow:
        name = "narrow"

        def supports(self, _feature: DialectFeature) -> bool:
            return False

        def render(self, node: object) -> str:
            return get_dialect("duckdb").render(node)  # type: ignore[arg-type]

    sql = compose(
        [Branch(sql="S0", keys=()), Branch(sql="S1", keys=())],
        keys=(),
        measures=((0, "a"), (1, "b")),
        dialect=_Narrow(),  # type: ignore[arg-type]
    )

    assert "CROSS JOIN" in sql


def test_a_dialect_without_null_safe_equality_is_refused() -> None:
    """The reason the capability is a flag rather than an assumption: a fourth
    dialect without it would otherwise be handed `=`, which drops every
    NULL-keyed group from the answer and says nothing."""

    class _Narrow:
        name = "narrow"

        def supports(self, _feature: DialectFeature) -> bool:
            return False

    with pytest.raises(PlannerError, match="null-safe equality"):
        compose(
            _two(),
            keys=("region",),
            measures=((0, "ship"), (1, "disc")),
            dialect=_Narrow(),  # type: ignore[arg-type]
        )


def test_one_branch_is_not_a_composition() -> None:
    """A single branch is planned without a join at all, so reaching here with
    one is a caller that partitioned wrongly — and the statement it would
    build reads as a composed plan while composing nothing."""
    with pytest.raises(PlannerError, match="at least two branches"):
        compose(
            [Branch(sql="S0", keys=("k",))],
            keys=("region",),
            measures=((0, "a"),),
            dialect=get_dialect("duckdb"),
        )


def test_every_key_is_matched_when_a_request_groups_by_more_than_one() -> None:
    """A composed request may group by several dimensions, and each of them
    has to appear in the domain and in every branch's match.

    Found by a sabotage sweep: dropping all but the first key from the match
    broke nothing, because every test until this one asked for a single
    dimension. With two, matching on the first alone joins a branch's row for
    `(gold, monday)` onto every `gold` group there is.
    """
    branches = [
        Branch(sql="S0", keys=("a_tier", "a_day")),
        Branch(sql="S1", keys=("b_tier", "b_day")),
    ]
    sql = compose(
        branches,
        keys=("tier", "day"),
        measures=((0, "ship"), (1, "disc")),
        dialect=get_dialect("duckdb"),
    )

    assert "SELECT branch_0.a_tier AS tier, branch_0.a_day AS day FROM branch_0" in sql
    assert "SELECT branch_1.b_tier AS tier, branch_1.b_day AS day FROM branch_1" in sql
    for index, prefix in enumerate("ab"):
        condition = sql.split(f"LEFT JOIN branch_{index}\n  ON ")[1].split("\nLEFT JOIN")[0]

        assert f"branch_{index}.{prefix}_tier IS NOT DISTINCT FROM branch_keys.tier" in condition
        assert f"branch_{index}.{prefix}_day IS NOT DISTINCT FROM branch_keys.day" in condition


def test_a_two_dimension_cross_mart_request_carries_both_keys() -> None:
    """The same property through the planner rather than through the builder,
    since what a request resolves to is where the pair of keys comes from:
    `tier` and `signed_up` are both `customer` columns, so both are the same
    dimension on every branch by D12 and both belong to the match.
    """
    from bloomery import MetricRequest
    from support.planning import fixture_ir, make_planner

    plan = make_planner().plan(
        fixture_ir("cross_mart_branches"),
        MetricRequest(
            metrics=("shipping_count", "line_discount"), dimensions=("tier", "signed_up")
        ),
        dialect="duckdb",
    )

    assert [column.name for column in plan.columns][:2] == ["tier", "signed_up"]
    assert plan.sql.count("IS NOT DISTINCT FROM") == 2 * len(plan.marts)

