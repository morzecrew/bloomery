"""E2E tier (RFC 0009 §5.2 tier 6, M11): the SQLMesh replan no-op test.

Compiled artifacts are written into a real SQLMesh project (pinned sqlmesh,
DuckDB gateway — no containers), loaded through ``sqlmesh.Context`` (which
raises on malformed ``MODEL`` blocks), and applied with
``plan(auto_apply=True)``. Then the same specs are compiled *again*, the
files rewritten byte-identically, and a fresh ``Context`` plans against the
persisted state: the second plan must report **no changes**. That is
determinism (RFC 0003) verified through a third party — bloomery and
SQLMesh's own fingerprinting agree that nothing moved.

Builtin audits declared in the ``MODEL`` blocks (e.g. ecom_basic's
``not_null``) run during apply, so a passing apply also exercises the audit
lowering. Custom audit artifacts (``audits/*.sql``) are written by the same
scaffold — the RFC 0016 fixture emits four (the ingestion-metadata contract,
the §6 conservation law, one ``on_fail: fail`` rule, and the reconcile check's
**non-blocking** one), so a passing apply also proves the ``blocking false``
grammar and the ``@execution_ds`` run-context macro against the pinned sqlmesh.

The conservation audit is the one that had to be *designed* against this test.
SQLMesh rewrites model references inside a MODEL query to the physical snapshot
table but not inside an AUDIT body, so an audit that read the sibling reject
relation resolved to a virtual-layer view that does not exist yet on a first
plan — and failed the run it existed to protect. Only a real ``plan`` against a
real framework shows that; the DuckDB execution tier renders audit bodies
itself and would have stayed green.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from decimal import Decimal
import sys
from pathlib import Path

import duckdb
import pytest
from sqlmesh import Context

import support.identity as support_identity
from support.compiling import compile_fixture

from bloomery.quality import ENTITY_GRAIN_ROW

pytestmark = pytest.mark.e2e

CONFIG_TEMPLATE = """\
gateways:
  local:
    connection:
      type: duckdb
      database: {database}
default_gateway: local
model_defaults:
  dialect: duckdb
  start: 2024-01-01
disable_anonymized_analytics: true
"""


def _seed_minimal(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE TABLE bronze.raw__events (id VARCHAR, kind VARCHAR, ts VARCHAR)")
    conn.executemany(
        "INSERT INTO bronze.raw__events VALUES (?, ?, ?)",
        [
            ("e1", "click", "2024-01-02T03:04:05"),
            ("e2", "view", "2024-02-03T04:05:06"),
        ],
    )


def _seed_ecom_basic(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE bronze.shopify__order_lines ("
        'order_id VARCHAR, "index" BIGINT, total DECIMAL(12, 4), qty BIGINT, created_at VARCHAR)'
    )
    conn.execute(
        "INSERT INTO bronze.shopify__order_lines VALUES (?, ?, ?, ?, ?)",
        ("o1", 1, Decimal("30.00"), 3, "2024-01-02T03:04:05"),
    )
    conn.execute("CREATE TABLE bronze.shopify__orders (id VARCHAR, customer JSON)")
    conn.execute(
        "INSERT INTO bronze.shopify__orders VALUES (?, ?)",
        ("o1", '{"id": "c1"}'),
    )


def _seed_semi_additive_inventory(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE bronze.wms__stock_levels (warehouse VARCHAR, day VARCHAR, on_hand BIGINT, "
        "operator_note VARCHAR, _ingested_at TIMESTAMP, _load_id VARCHAR, _source_row_id VARCHAR)"
    )
    conn.executemany(
        "INSERT INTO bronze.wms__stock_levels VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("A", "2024-01-01", 100, "operator note", "2024-01-01 00:00:00", "L1", "r1"),
            # Negative: fires both the flag rule and the quarantining range
            # rule, so it routes to the reject table carrying *both* names
            # (RFC 0016 D18).
            ("A", "2024-01-02", -5, "operator note", "2024-01-02 00:00:00", "L1", "r2"),
            ("B", "2024-01-01", 40, "operator note", "2024-01-01 00:00:00", "L1", "r3"),
        ],
    )


def _verify_semi_additive_inventory(conn: duckdb.DuckDBPyConnection) -> None:
    """The RFC 0016 surfaces, applied by SQLMesh itself: the two-way split, the
    reject row's ``failed_rules``, the reconcile model, and the quality mart —
    including its ``run_date``, which only has a value because **SQLMesh**
    expanded ``@execution_ds`` (bloomery never read a clock, §5.8)."""
    kept = conn.execute(
        "SELECT warehouse_id, stock_level, _quality_ok FROM silver.inventory_level "
        "ORDER BY warehouse_id, stock_date"
    ).fetchall()
    assert kept == [("A", 100, True), ("B", 40, True)]

    rejected = conn.execute(
        "SELECT _source_row_id, failed_rules, resolved_at FROM silver.inventory_level__reject"
    ).fetchall()
    assert rejected == [("r2", ["stock_level_not_negative", "stock_level_range_min"], None)]

    # The mart gained has_quality_flags as an ordinary dimension (§5.5), and
    # quarantined rows never reached it — mart rowcounts legitimately differ
    # from bronze (D15).
    #
    # **Both values are FALSE here for a fixture reason, not a lowering one**,
    # and saying so is the point: this fixture's only flag rule fires on
    # negative levels, which its quarantining `range` rule also diverts, so no
    # surviving row can carry a flag. That makes the assertion below unable to
    # distinguish the real dimension from a constant `FALSE` — which is exactly
    # how an inverted polarity once shipped past every tier but the goldens
    # (D64). The polarity itself is asserted in both directions, and through a
    # `MetricRequest`, in ``tests/execution/test_quality_precedence.py``; what
    # this line proves is the narrower claim that a *diverted* row is absent
    # from the mart entirely.
    mart = conn.execute(
        "SELECT warehouse_id, has_quality_flags FROM gold.mart_inventory ORDER BY warehouse_id"
    ).fetchall()
    assert mart == [("A", False), ("B", False)]

    reconciled = conn.execute(
        "SELECT warehouse_id, difference, within_tolerance "
        "FROM silver.stock_level_matches_snapshot__reconcile ORDER BY warehouse_id"
    ).fetchall()
    assert reconciled == [("A", 0, True), ("B", 0, True)]

    quality = {
        rule: (evaluated, failed, quarantined)
        for rule, evaluated, failed, quarantined in conn.execute(
            "SELECT rule, rows_evaluated, rows_failed, rows_quarantined "
            "FROM gold.mart_data_quality ORDER BY rule"
        ).fetchall()
    }
    # One row per rule evaluation, one per reconcile check, and one accounting
    # row per entity (§5.8): a rule row reports what its own predicate did, and
    # the population counts beside it belong to the entity — repeating them per
    # rule made SUM return a multiple of the truth.
    assert quality["stock_level_range_min"] == (0, 1, 0)
    assert quality["stock_level_not_negative"] == (0, 1, 0)  # fired; diverts nothing
    assert quality[ENTITY_GRAIN_ROW] == (3, 0, 1)  # 2 kept + 1 diverted, 1 diverted row
    assert "stock_level_matches_snapshot" in quality
    (run,) = conn.execute(
        "SELECT DISTINCT run_id IS NULL, run_date IS NOT NULL FROM gold.mart_data_quality"
    ).fetchall()
    assert run == (True, True)


def _verify_minimal(conn: duckdb.DuckDBPyConnection) -> None:
    rows = conn.execute(
        "SELECT event_id, kind, occurred_at FROM silver.event ORDER BY event_id"
    ).fetchall()
    assert rows == [
        ("e1", "click", datetime(2024, 1, 2, 3, 4, 5)),
        ("e2", "view", datetime(2024, 2, 3, 4, 5, 6)),
    ]


def _verify_ecom_basic(conn: duckdb.DuckDBPyConnection) -> None:
    row = conn.execute("SELECT unit_price FROM silver.order_item").fetchone()
    assert row is not None
    unit_price = row[0]
    assert isinstance(unit_price, Decimal)
    assert unit_price == Decimal("10.00")
    mart = conn.execute(
        "SELECT order_id, line_no, quantity, order_customer_id FROM gold.mart_order_items"
    ).fetchone()
    assert mart == ("o1", 1, 3, "c1")


def _seed_step_resolution(connection: duckdb.DuckDBPyConnection) -> None:
    """The step fixture's only bronze input. Its two silver relations are
    written by generated Python wrappers, not by bloomery SQL."""
    connection.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    connection.execute(
        "CREATE TABLE bronze.crm__customers AS SELECT * FROM (VALUES "
        "('crm', 'c-1', 'a@example.com', 'Ada'), ('crm', 'c-2', 'b@example.com', 'Bea')) "
        "AS t(system, id, email, name)"
    )


def _verify_step_resolution(connection: duckdb.DuckDBPyConnection) -> None:
    """Both wrappers ran, the contract assertion passed, and the consistency
    audit resolved its sibling — a plan that applies at all is the assertion
    (RFC 0017 D42/D44)."""
    customers = connection.execute(
        "SELECT canonical_id FROM silver.customer ORDER BY 1"
    ).fetchall()
    assert customers == [("c-1",), ("c-2",)]
    xref = connection.execute(
        "SELECT source_id, canonical_id FROM silver.customer_xref ORDER BY 1"
    ).fetchall()
    assert xref == [("c-1", "c-1"), ("c-2", "c-2")]


def _seed_identity_resolution(connection: duckdb.DuckDBPyConnection) -> None:
    """Two sources with no shared identifier — the situation the step exists
    for. `crm/C-1001` and `billing/AC-77` are one person by email.

    Grace is here with **no email at all**, and at the wiring's `0.9` she
    resolves to nobody: her two rows reach the crosswalk with a NULL
    `canonical_id`. That is the shape a plan has to survive, because the
    wrapper's contract assertion runs before the relation is written — with
    the column declared `required` the step aborted here, and the fixture
    could not be planned at the threshold it wires.
    """
    connection.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    connection.execute(
        "CREATE TABLE bronze.crm__customers AS SELECT * FROM (VALUES "
        "('crm', 'C-1001', 'Ada@Example.com ', 'Ada Lovelace'), "
        "('crm', 'C-1002', NULL, 'Grace Hopper'), "
        "('crm', 'C-1003', 'mary@example.com', 'Mary Jackson')) "
        "AS t(system, id, email, full_name)"
    )
    connection.execute(
        "CREATE TABLE bronze.billing__accounts AS SELECT * FROM (VALUES "
        "('billing', 'AC-77', 'ada@example.com', 'A. Lovelace'), "
        "('billing', 'AC-91', NULL, 'hopper, grace')) "
        "AS t(origin, account_ref, billing_email, account_name)"
    )


def _verify_identity_resolution(connection: duckdb.DuckDBPyConnection) -> None:
    """Two people out of five source rows, the crosswalk total over them, and
    a mart over the step-produced entity that SQLMesh actually built.

    The mart is the assertion that matters here: it reads `silver.customer`,
    which no bloomery SQL writes, so a plan that applies is a plan where the
    wrapper ran first and the gold model resolved its dependency on a relation
    a Python model produced.

    Grace's two rows are the second assertion, and they are why the plan is
    worth running at all: the crosswalk carries them unresolved, so the
    contract assertion inside the Python model has met a NULL in the column it
    checks — the case that used to abort the step.
    """
    customers = connection.execute("SELECT COUNT(*) FROM silver.customer").fetchone()
    assert customers == (2,)
    xref = connection.execute("SELECT COUNT(*) FROM silver.customer_xref").fetchone()
    assert xref == (5,)
    unresolved = connection.execute(
        "SELECT COUNT(*) FROM silver.customer_xref WHERE canonical_id IS NULL"
    ).fetchone()
    assert unresolved == (2,)
    matched = connection.execute(
        "SELECT COUNT(DISTINCT canonical_id) FROM silver.customer_xref "
        "WHERE source_id IN ('C-1001', 'AC-77')"
    ).fetchone()
    assert matched == (1,)
    mart = connection.execute(
        "SELECT COUNT(*), COUNT(resolved_day) FROM gold.mart_customers"
    ).fetchone()
    assert mart == (2, 2)


def _seed_coverage_check(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("CREATE TABLE bronze.crm__customers (id VARCHAR, name VARCHAR)")
    conn.executemany(
        "INSERT INTO bronze.crm__customers VALUES (?, ?)",
        [("c1", "Ordering Customer"), ("c2", "Silent Customer")],
    )
    conn.execute(
        "CREATE TABLE bronze.shop__orders (id VARCHAR, customer_id VARCHAR, amount VARCHAR)"
    )
    # `c2` deliberately has none: the check exists to notice exactly that row.
    conn.executemany(
        "INSERT INTO bronze.shop__orders VALUES (?, ?, ?)",
        [("o1", "c1", "10.0"), ("o2", "c1", "20.0")],
    )


def _verify_coverage_check(conn: duckdb.DuckDBPyConnection) -> None:
    """The audit is **non-blocking**, so a plan that applies is the assertion
    that it loaded and ran without stopping the run — which is the half no
    other tier can see (RFC 0016 D90). The rows are checked too, because an
    audit attached to a model that failed to build would also "not block"."""
    rows = conn.execute("SELECT customer_id FROM silver.customer ORDER BY 1").fetchall()
    assert rows == [("c1",), ("c2",)]
    orders = conn.execute("SELECT COUNT(*) FROM silver.\"order\"").fetchone()
    assert orders == (2,)


Seeder = Callable[[duckdb.DuckDBPyConnection], None]
Verifier = Callable[[duckdb.DuckDBPyConnection], None]

FIXTURES: dict[str, tuple[Seeder, Verifier, frozenset[str]]] = {
    "minimal": (_seed_minimal, _verify_minimal, frozenset({"silver.event"})),
    "ecom_basic": (
        _seed_ecom_basic,
        _verify_ecom_basic,
        frozenset(
            {"silver.order", "silver.order_item", "gold.dim_date", "gold.mart_order_items"}
        ),
    ),
    # The RFC 0016 fixture: split silver model, reject table, reconcile model
    # plus its non-blocking audit, and the quality mart — applied by SQLMesh
    # itself, which is the only way to know the emitted macros, the
    # ``blocking false`` audit grammar and the model dependency order are real.
    "semi_additive_inventory": (
        _seed_semi_additive_inventory,
        _verify_semi_additive_inventory,
        frozenset(
            {
                "silver.inventory_level",
                "silver.inventory_level__reject",
                "silver.stock_level_matches_snapshot__reconcile",
                "gold.dim_date",
                "gold.mart_inventory",
                "gold.mart_data_quality",
            }
        ),
    ),
    # RFC 0017: the step fixture is here because *nothing else loads SQLMesh*,
    # and that gap hid three defects in a row — an audit emitted and never run,
    # a wrapper that never loaded at all (a module-global `Decimal` broke
    # SQLMesh's dependency serialization), and an audit whose sibling resolved
    # to a virtual-layer view that does not exist on a first plan. Each was
    # green in every other tier: the goldens pinned bytes, `ast.parse` proved
    # grammar, and the execution tier ran the audit's SELECT with SQLMesh
    # nowhere in the loop. Only a real plan sees any of it.
    "step_resolution": (
        _seed_step_resolution,
        _verify_step_resolution,
        frozenset({"silver.customer_raw", "silver.customer", "silver.customer_xref"}),
    ),
    # RFC 0016 D90: a coverage audit is a shape nothing else here has — a body
    # joining ``@this_model`` to a *sibling*, and a ``depends_on`` that exists
    # only because of the audit. The comment above ``step_resolution`` is the
    # argument for it being here: that exact combination is what hid three
    # defects, and only a real plan resolves a sibling reference at all.
    "coverage_check": (
        _seed_coverage_check,
        _verify_coverage_check,
        frozenset({"silver.customer", "silver.order"}),
    ),
    # RFC 0021 §5.1: identity resolution, which `step_resolution` cannot show
    # — two *inputs*, an `on_fail: fail` rule on a step output, and a mart over
    # the resolved entity. That mart is why this cell exists rather than being
    # covered by the execution tier: it reads a relation a Python model writes,
    # so only a real plan proves SQLMesh orders the two.
    "identity_resolution": (
        _seed_identity_resolution,
        _verify_identity_resolution,
        frozenset(
            {
                "silver.customer_crm",
                "silver.customer_billing",
                "silver.customer",
                "silver.customer_xref",
                "gold.dim_date",
                "gold.mart_customers",
            }
        ),
    ),
}


def _write_project(root: Path, fixture: str, warehouse: Path) -> None:
    """Materialize a compiled fixture as an on-disk SQLMesh project."""
    (root / "config.yaml").write_text(CONFIG_TEMPLATE.format(database=warehouse))
    for artifact in compile_fixture(fixture):
        dest = root / artifact.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(artifact.content)
    _write_platform_steps(root, fixture)


def _write_platform_steps(root: Path, fixture: str) -> None:
    """The platform package a generated wrapper imports at run time.

    It lives here rather than in ``tests/fixtures/`` because it is *step body*
    — platform-repo territory the RFC puts outside bloomery entirely (§6). The
    body is deliberately trivial and honest: it resolves each source row to
    itself, so both outputs agree and the consistency audit has something
    correct to pass on.
    """
    if fixture == "identity_resolution":
        # The demonstration resolver itself, copied in — not a stand-in. It
        # imports nothing but the standard library and pandas precisely so it
        # can be dropped into a generated package and run there, which is what
        # the platform's own registry does with its real one.
        package = root / "platform_steps"
        package.mkdir(exist_ok=True)
        (package / "__init__.py").write_text("")
        (package / "resolve_customers.py").write_text(
            Path(support_identity.__file__).read_text()
        )
        return
    if fixture != "step_resolution":
        return
    package = root / "platform_steps"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("")
    (package / "resolve_customers.py").write_text(
        "import pandas as pd\n\n\n"
        "def resolve(raw, threshold):\n"
        "    canonical = raw['source_id']\n"
        "    return {\n"
        "        'customer': pd.DataFrame(\n"
        "            {'canonical_id': canonical, 'confidence': [threshold] * len(raw)}\n"
        "        ),\n"
        "        'customer_xref': pd.DataFrame(\n"
        "            {'source_system': raw['source_system'], 'source_id': raw['source_id'],\n"
        "             'canonical_id': canonical, 'method': ['exact'] * len(raw)}\n"
        "        ),\n"
        "    }\n"
    )


#: The package name every generated wrapper imports (RFC 0017 D13). One name
#: across all fixtures, because it is the *platform's* package — which is why
#: it has to be evicted between them rather than renamed per fixture.
PLATFORM_PACKAGE = "platform_steps"


@pytest.fixture
def _importable() -> Iterator[Callable[[Path], None]]:
    """Make a project root importable for one test, then undo it.

    Both halves matter. Leaving the path on `sys.path` lets a later cell import
    an earlier cell's package; leaving the module in `sys.modules` makes it
    certain, because the name is already bound and the path is never consulted.
    """
    added: list[str] = []

    def insert(root: Path) -> None:
        added.append(str(root))
        sys.path.insert(0, str(root))

    yield insert
    for entry in added:
        if entry in sys.path:
            sys.path.remove(entry)
    stale = [
        name
        for name in sys.modules
        if name == PLATFORM_PACKAGE or name.startswith(f"{PLATFORM_PACKAGE}.")
    ]
    for name in stale:
        del sys.modules[name]


@pytest.mark.parametrize("fixture", sorted(FIXTURES))
def test_replan_is_a_no_op(
    fixture: str, tmp_path: Path, _importable: Callable[[Path], None]
) -> None:
    seed, verify, expected_models = FIXTURES[fixture]

    warehouse = tmp_path / "warehouse.db"
    seeding = duckdb.connect(str(warehouse))
    seeding.execute("SET TimeZone = 'UTC'")
    seeding.execute("CREATE SCHEMA bronze")
    seed(seeding)
    seeding.close()

    first = compile_fixture(fixture)
    _write_project(tmp_path, fixture, warehouse)
    # A generated step wrapper imports its platform package at *run* time
    # (RFC 0017 D13), so the project root has to be importable — in a real
    # deployment the step runtime installs it.
    #
    # Undone afterwards, and the package evicted with it: two step fixtures
    # ship a `platform_steps.resolve_customers` apiece, and whichever ran first
    # stayed in `sys.modules` for the second — which then called *its*
    # entrypoint with the other's keyword arguments. One step fixture hid this
    # completely; the second one turned it into a failure that depends on
    # alphabetical order.
    _importable(tmp_path)

    # Context raises on malformed MODEL blocks — loading alone is a check.
    context = Context(paths=str(tmp_path))
    try:
        assert {model.name for model in context.models.values()} == expected_models
        plan = context.plan(no_prompts=True, auto_apply=True)
        assert plan.has_changes  # everything is new on the first apply
    finally:
        context.close()

    # Compile again from the same specs: byte-identical artifacts (RFC 0003),
    # rewritten in place so SQLMesh re-reads them from disk.
    second = compile_fixture(fixture)
    assert second == first
    _write_project(tmp_path, fixture, warehouse)

    replan_context = Context(paths=str(tmp_path))
    try:
        replan = replan_context.plan(no_prompts=True, auto_apply=True)
        assert replan.has_changes is False
        assert list(replan.new_snapshots) == []
        assert replan.modified_snapshots == {}
    finally:
        replan_context.close()

    # The first apply materialized through SQLMesh's own runner (audits
    # included); the replan changed nothing — the data is still right.
    warehouse_conn = duckdb.connect(str(warehouse), read_only=True)
    try:
        verify(warehouse_conn)
    finally:
        warehouse_conn.close()
