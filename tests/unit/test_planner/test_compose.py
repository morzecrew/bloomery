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


def test_the_branches_are_joined_full_outer_on_a_null_safe_key() -> None:
    """Both halves of D13 in one statement: a group present on one side only
    survives the join, and a NULL group meets the other side's NULL group
    instead of failing `NULL = NULL` and splitting into two rows."""
    sql = compose(
        _two(), keys=("region",), measures=((0, "ship"), (1, "disc")), dialect=get_dialect("duckdb")
    )

    assert "FULL OUTER JOIN" in sql
    assert "IS NOT DISTINCT FROM" in sql
    assert "INNER JOIN" not in sql


def test_the_key_is_projected_once_under_the_name_the_caller_asked_for() -> None:
    """Two marts spell one dimension two ways and the result has one column
    (logs/T-0026.md, D-165). Coalesced rather than taken from either side,
    since a full outer join leaves the other side's copy NULL for every group
    that side does not have."""
    sql = compose(
        _two(), keys=("region",), measures=((0, "ship"), (1, "disc")), dialect=get_dialect("duckdb")
    )

    assert "COALESCE(branch_0.order__region, branch_1.item__order_region) AS region" in sql
    assert sql.count(" AS region") == 1


def test_a_third_branch_joins_against_every_earlier_one() -> None:
    """The generalization that a two-branch case cannot see. After a full
    outer join a key present only on the second branch is NULL in the first,
    so joining the third against the first alone would drop every group the
    first did not have."""
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

    assert "ON branch_1.k1 IS NOT DISTINCT FROM branch_0.k0" in sql
    assert "ON branch_2.k2 IS NOT DISTINCT FROM COALESCE(branch_0.k0, branch_1.k1)" in sql


def test_an_ungrouped_request_joins_on_true() -> None:
    """Each branch is one row of totals, so the join is their cross product.
    Omitting the condition is a syntax error and inventing a key is a lie;
    `ON TRUE` is what the shape actually is."""
    branches = [Branch(sql="S0", keys=()), Branch(sql="S1", keys=())]
    sql = compose(
        branches, keys=(), measures=((0, "a"), (1, "b")), dialect=get_dialect("duckdb")
    )

    assert "ON TRUE" in sql
    assert "COALESCE" not in sql


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
