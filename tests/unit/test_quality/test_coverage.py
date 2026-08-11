"""Cross-entity coverage checks (RFC 0016 §10 → D90).

§10 asked whether "every customer has ≥1 order" was reconcile-shaped. It is
not: a ``reconcile`` compares two *values* and alerts when they differ beyond a
tolerance, and there is no right-hand value on the referenced entity to compare
against. This asserts *existence*, which is a different question with a
different answer.

What decides its shape is the same argument that settled mart assertions
(D89) and it lands somewhere different here. A childless customer **is** a real
silver row — it has a source identity, a reject table and a replay path — so a
disposition would be meaningful. It is still an audit, and for a structural
reason rather than a semantic one: routing the row would need the referenced
entity's model to read the dependent one, while the dependent one already reads
the referenced one through this very relationship. The pair that most wants the
check is exactly the pair whose models would form a cycle.

So the audit hangs off the **dependent** side, which already depends on the
referenced side, and adds no edge the relationship did not imply.
"""

from __future__ import annotations

import duckdb
import pytest
from sqlglot import exp, parse_one
from support.compiling import compile_fixture, extract_select, load_fixture

from bloomery import Target, compile_project, load_project
from bloomery.emit import ArtifactKind
from bloomery.errors import GuardrailError, SpecParseError, UnsupportedByTarget
from bloomery.resolve import build_project_ir

pytestmark = pytest.mark.unit

FIXTURE = "coverage_check"
AUDIT = "every_customer_has_an_order_coverage"

ENTITY_MODEL = """
spec_version: 1
entities:
  customer:
    grain: one row per customer
    key: [customer_id]
    fields:
      customer_id: {{type: string, required: true}}
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {{type: string, required: true}}
      customer_id: {{type: string}}
coverage:
{clauses}
relationships:
  - name: order_of_customer
    from: order
    to: customer
    via: {{customer_id: customer_id}}
    cardinality: many_to_one
"""

MAPPINGS = {
    "mapping_customers": (
        "mapping_version: 1\ntarget: customer\nsource: crm__customers\n"
        'key:\n  customer_id: {from: "$.id", transform: [to_string]}\n'
    ),
    "mapping_orders": (
        "mapping_version: 1\ntarget: order\nsource: shop__orders\n"
        'key:\n  order_id: {from: "$.id", transform: [to_string]}\n'
        'fields:\n  customer_id: {from: "$.customer_id", transform: [to_string]}\n'
    ),
}

GOOD = "  - {name: has_order, relationship: order_of_customer, min: 1, on_fail: flag}\n"


def build(clauses: str = GOOD) -> object:
    project = load_project(
        {"entity_model": ENTITY_MODEL.format(clauses=clauses), **MAPPINGS}
    )
    return build_project_ir(project)


# ....................... #
# What the surface refuses


@pytest.mark.parametrize("disposition", ["quarantine", "repair", "unknown_member"])
def test_a_row_routing_disposition_is_refused(disposition: str) -> None:
    """An audit attached to the dependent side cannot route a row of the
    referenced one. Refused at the surface rather than lowered to something
    weaker, so an author who wanted quarantine finds out here."""
    with pytest.raises(SpecParseError):
        build(
            f"  - {{name: c, relationship: order_of_customer, min: 1, on_fail: {disposition}}}\n"
        )


def test_a_minimum_below_one_is_refused() -> None:
    """``min: 0`` is satisfied by every row, so it declares a check that cannot
    fire — the shape D28 spent a decision closing elsewhere."""
    with pytest.raises(SpecParseError):
        build("  - {name: c, relationship: order_of_customer, min: 0, on_fail: flag}\n")


def test_an_unknown_relationship_is_refused() -> None:
    with pytest.raises(GuardrailError, match="no declared relationship 'nosuch'"):
        build("  - {name: c, relationship: nosuch, min: 1, on_fail: flag}\n")


def test_two_checks_of_one_name_are_refused() -> None:
    """The name is the audit's identity and its artifact path."""
    with pytest.raises(GuardrailError, match="named 'has_order'"):
        build(GOOD + GOOD)


# ....................... #
# What it emits


def _audit() -> str:
    return next(
        artifact.content
        for artifact in compile_fixture(FIXTURE)
        if artifact.path == f"audits/{AUDIT}.sql"
    )


def test_the_audit_hangs_off_the_dependent_side() -> None:
    """The structural decision, asserted where it shows: the *order* model
    names the audit, because it already reads *customer* through this
    relationship. On the customer model it would be a new edge, and the
    reverse edge already exists whenever the dependent side has a
    ``referential`` rule — a cycle in exactly the configuration this check is
    written for."""
    models = {
        artifact.path: artifact.content
        for artifact in compile_fixture(FIXTURE)
        if artifact.kind is ArtifactKind.MODEL
    }
    assert AUDIT in models["models/silver/order.sql"]
    assert AUDIT not in models["models/silver/customer.sql"]


def test_the_sibling_is_declared_in_depends_on() -> None:
    """SQLMesh does not rewrite model references inside an AUDIT body (D29), so
    a sibling that is not declared resolves to a virtual-layer view that need
    not exist on a first plan — the trap D40 closed for step audits."""
    order = next(
        artifact.content
        for artifact in compile_fixture(FIXTURE)
        if artifact.path == "models/silver/order.sql"
    )
    assert "depends_on (silver.customer)" in order


def test_the_dependent_side_is_this_model_not_a_named_relation() -> None:
    """``@this_model`` is the one reference SQLMesh *does* rewrite in an audit
    body. Naming the relation instead would resolve to the virtual layer and
    put the model into its own ``depends_on``."""
    body = _audit()
    assert "@this_model AS _dependent" in body
    assert "silver.order" not in body


def test_the_count_is_of_a_dependent_column_never_of_rows() -> None:
    """The LEFT JOIN trap, and the reason this is asserted on the AST rather
    than by eye: an unmatched left row still produces one output row, so
    ``COUNT(*)`` answers 1 for a customer with no orders at all — and the check
    would pass on precisely the rows it exists to find."""
    select = parse_one(extract_select(_audit()), dialect="duckdb")
    assert isinstance(select, exp.Select)
    counts = list(select.find_all(exp.Count))
    assert counts, "the audit does not count anything"
    for count in counts:
        assert not isinstance(count.this, exp.Star)
        assert count.this.table == "_dependent"


def test_dbt_refuses_the_project_rather_than_dropping_the_check() -> None:
    project, catalog = load_fixture(FIXTURE)
    with pytest.raises(UnsupportedByTarget, match="every_customer_has_an_order"):
        compile_project(project, target=Target.DBT, dialect="duckdb", catalog=catalog)


# ....................... #
# What the audit body does, executed


@pytest.fixture
def warehouse() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE SCHEMA silver")
    connection.execute("CREATE TABLE silver.customer (customer_id VARCHAR, name VARCHAR)")
    connection.executemany(
        "INSERT INTO silver.customer VALUES (?, ?)",
        [("c1", "Ordering"), ("c2", "Silent"), ("c3", "Also silent")],
    )
    connection.execute(
        'CREATE TABLE silver."order" (order_id VARCHAR, customer_id VARCHAR, '
        "amount DECIMAL(12, 4))"
    )
    connection.executemany(
        'INSERT INTO silver."order" VALUES (?, ?, ?)',
        [("o1", "c1", "10.0"), ("o2", "c1", "20.0"), ("o3", None, "5.0")],
    )
    return connection


def _report(connection: duckdb.DuckDBPyConnection) -> list[tuple[object, ...]]:
    body = extract_select(_audit()).replace("@this_model", 'silver."order"')
    return connection.execute(body + " ORDER BY 1").fetchall()


def test_the_audit_reports_exactly_the_unreferenced_rows(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """An audit passes when it returns no rows, so what it returns is the
    report — the customers nobody ordered from, with their count beside them."""
    assert _report(warehouse) == [("c2", 0), ("c3", 0)]


def test_a_null_foreign_key_references_nobody(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """``o3`` has a NULL ``customer_id``. It must not count toward any
    customer's coverage — the join cannot match it, and a ``COUNT(*)`` would
    have folded it into whichever group it landed in."""
    assert all(count == 0 for _customer, count in _report(warehouse))
    covered = warehouse.execute(
        'SELECT COUNT(*) FROM silver."order" WHERE customer_id IS NULL'
    ).fetchone()
    assert covered == (1,)


def test_a_customer_with_orders_is_not_reported(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """The control. A body that reported every row would satisfy the assertion
    above just as well."""
    assert "c1" not in {row[0] for row in _report(warehouse)}


def test_a_higher_minimum_reports_the_under_covered(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    """``min`` generalizes past §10's example: "every order has at least two
    lines" is the same check with a different bound, and ``c1`` has exactly
    two orders — so a bound of three reports it and a bound of two does not."""
    body = extract_select(_audit()).replace("@this_model", 'silver."order"')
    at_three = body.replace("< 1", "< 3")
    reported = {row[0] for row in warehouse.execute(at_three).fetchall()}
    assert reported == {"c1", "c2", "c3"}
