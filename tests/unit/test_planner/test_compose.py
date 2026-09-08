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
from sqlglot import parse_one

from bloomery.dialects import DialectFeature, get_dialect
from bloomery.errors import PlannerError
from bloomery.planner.compose import Branch, Measure, compose

pytestmark = pytest.mark.unit

# ----------------------- #

DIALECTS = ("duckdb", "postgres", "trino")


def _m(index: int, name: str) -> Measure:
    """A stored measure: branch ``index`` projects it under its own name."""

    return Measure(name=name, inputs=((name, index, name),))


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
        _two(), keys=("region",), measures=(_m(0, "ship"), _m(1, "disc")), dialect=get_dialect("duckdb")
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
        _two(), keys=("region",), measures=(_m(0, "ship"), _m(1, "disc")), dialect=get_dialect("duckdb")
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
        measures=(_m(0, "a"), _m(1, "b"), _m(2, "c")),
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
        branches, keys=(), measures=(_m(0, "a"), _m(1, "b")), dialect=get_dialect("duckdb")
    )

    assert "CROSS JOIN" in sql
    assert "branch_keys" not in sql
    assert "LEFT JOIN" not in sql


def test_measures_are_projected_in_the_order_they_were_asked_for() -> None:
    """Branches are sorted by mart name so two runs compose the same query;
    a result's column order is the caller's, and the two are not the same
    order."""
    sql = compose(
        _two(), keys=("region",), measures=(_m(1, "disc"), _m(0, "ship")), dialect=get_dialect("duckdb")
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
        _two(), keys=("region",), measures=(_m(0, "ship"), _m(1, "disc")), dialect=port
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
        measures=(_m(0, "a"), _m(1, "b")),
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
            measures=(_m(0, "ship"), _m(1, "disc")),
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
            measures=(_m(0, "a"),),
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
        measures=(_m(0, "ship"), _m(1, "disc")),
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



# ....................... #
# RFC 0041 P2: computation above the join, and the statement's own tail.


def _computed() -> Measure:
    """A ratio over two branches — the shape D3 exists for."""

    return Measure(
        name="disc_per_ship",
        inputs=(("disc", 1, "disc"), ("ship", 0, "ship")),
        expr=parse_one("disc / NULLIF(ship, 0)"),
    )


@pytest.mark.parametrize("dialect", DIALECTS)
def test_a_computed_measure_is_evaluated_above_the_join(dialect: str) -> None:
    """RFC 0041 D3: the operands are aggregated in their own branches and the
    expression is evaluated once, over the joined result.

    What the assertion pins is that each name in the expression became **its
    own branch's** column: `disc` reads `branch_1` and `ship` reads `branch_0`,
    which is the whole content of the claim that the ratio was not computed
    row-level in either branch.

    The division's *spelling* is the dialect port's and differs — PostgreSQL
    and Trino take sqlglot's `CAST(… AS DOUBLE)` around an untyped `Div`, which
    is what keeps `COUNT(a) / COUNT(b)` off integer division and is the same
    treatment MetricFlow's own ratio gets on the single-mart path. So the
    binding is asserted and the arithmetic is left to the port that owns it.
    """
    sql = compose(
        _two(),
        keys=("region",),
        measures=(_computed(),),
        dialect=get_dialect(dialect),
    )
    projected = next(line for line in sql.splitlines() if "AS disc_per_ship" in line)

    assert "branch_1.disc" in projected
    assert "NULLIF(branch_0.ship, 0)" in projected
    assert " / " in projected


@pytest.mark.parametrize(
    ("expr", "named"),
    [
        ("disc / rogue", "rogue"),
        ("disc / t.disc", "t.disc"),
        ("disc / branch_0.ship", "branch_0.ship"),
    ],
)
def test_an_expression_naming_something_no_branch_produces_is_refused(
    expr: str, named: str
) -> None:
    """A composed expression reads its declared inputs by their bare names and
    nothing else.

    The **qualified** cases are the ones that got through. A qualified name is
    not a rebinding candidate, so checking what was still unqualified *after*
    the rebinding saw nothing wrong with it: `disc / t.disc` reached the SQL
    naming a relation the statement does not declare, and
    `disc / branch_0.ship` named a branch CTE directly, which would read
    another branch's column under this measure's name. The metrics guardrail
    does not stop either first — it compares `Column.name`, and the name half
    of `t.disc` is a declared alias (logs/T-0027.md, finding 5).
    """
    with pytest.raises(PlannerError, match="which no branch produces") as excinfo:
        compose(
            _two(),
            keys=("region",),
            measures=(
                Measure(
                    name="bad",
                    inputs=(("disc", 1, "disc"), ("ship", 0, "ship")),
                    expr=parse_one(expr),
                ),
            ),
            dialect=get_dialect("duckdb"),
        )

    assert named in str(excinfo.value)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_the_order_states_where_nulls_go_on_every_dialect(dialect: str) -> None:
    """RFC 0041 D13 mints a NULL group on purpose, so the composed `ORDER BY`
    sorts over a key that is NULL by construction and SQL does not fix where a
    NULL lands (logs/T-0027.md, D-177).

    Written out in both directions and identically on all three dialects. The
    obvious `exp.Ordered(nulls_first=False)` renders a bare `x DESC` on two of
    them, because sqlglot elides what it believes the dialect defaults to — and
    that default is a *setting*, which is exactly what this must not depend on.
    """
    sql = compose(
        _two(),
        keys=("region",),
        measures=(_m(0, "ship"), _m(1, "disc")),
        order_by=(("region", "asc"), ("ship", "desc")),
        dialect=get_dialect(dialect),
    )

    assert sql.rstrip().endswith("ORDER BY region ASC NULLS LAST, ship DESC NULLS LAST")


def test_the_limit_is_the_last_line_and_appears_once() -> None:
    """A limit anywhere but the composed statement truncates a branch before
    the join and answers from a prefix (logs/T-0027.md, D-182). One `LIMIT`,
    after everything."""
    sql = compose(
        _two(),
        keys=("region",),
        measures=(_m(0, "ship"),),
        order_by=(("ship", "desc"),),
        limit=25,
        dialect=get_dialect("duckdb"),
    )

    assert sql.upper().count("LIMIT") == 1
    assert sql.rstrip().endswith("LIMIT 25")


def test_an_ungrouped_composition_still_takes_its_tail() -> None:
    """The keyless shape is a `CROSS JOIN` of one-row totals with no key domain
    (D18), and the tail belongs to it just the same — a limit is the caller's
    guard whether or not the answer is grouped."""
    branches = [
        Branch(sql="SELECT SUM(x) AS a FROM t", keys=()),
        Branch(sql="SELECT SUM(y) AS b FROM u", keys=()),
    ]
    sql = compose(
        branches,
        keys=(),
        measures=(_m(0, "a"), _m(1, "b")),
        order_by=(("a", "desc"),),
        limit=1,
        dialect=get_dialect("duckdb"),
    )

    assert "CROSS JOIN" in sql
    assert sql.rstrip().endswith("ORDER BY a DESC NULLS LAST\nLIMIT 1")
