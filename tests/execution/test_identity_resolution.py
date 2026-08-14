"""Identity resolution end to end, executed (RFC 0021 §5.1).

The point of the fixture is that identity resolution needs no new spec kind —
so the thing worth executing is not the matching (that is the platform's step,
covered standalone in ``tests/unit/test_steps/test_identity_demo.py``) but the
**wiring around it**: that bloomery's emitted SQL runs against the relations a
step actually writes.

So this module does what the warehouse does. It builds the two silver sources
from bronze, runs the demonstration resolver over them, registers its two
frames as the step's output relations — which is precisely what the generated
wrappers do at run time, and the one thing bloomery never does itself
(RFC 0003) — and then runs the gold mart and both audits over the result.

That ordering is the test. A mart or an audit that reads a column the step's
wrapper does not write compiles perfectly and fails here.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import duckdb
import pytest
from support.compiling import compile_fixture, load_fixture
from support.execution import audit_body, materialize, warehouse
from support.identity import resolve

pytestmark = pytest.mark.execution

FIXTURE = "identity_resolution"


def _wired_threshold() -> Decimal:
    """The threshold the *wiring* sets, read from the spec rather than retyped.

    The generated wrapper passes `parameters:` through to the step untouched,
    so a stand-in using a different number is standing in for a run that never
    happens. This one was retyped and drifted: the fixture wired `0.9` while
    this module ran `0.85`, so the unresolved rows the wiring asks for never
    appeared here — and the contract violation they used to cause was
    invisible at every tier.
    """
    project, _catalog = load_fixture(FIXTURE)
    threshold = project.steps.steps[0].parameters["threshold"]
    assert isinstance(threshold, Decimal)
    return threshold

#: Two sources, three people, no shared identifier. `ada@example.com` appears
#: in both under different ids; Grace appears in both with no email and her
#: name written two ways; `mary@example.com` is in the CRM only.
#:
#: At the wiring's `0.9` Grace is the row that does **not** resolve — a name
#: match scores `0.85` — so the crosswalk carries two unresolved rows and the
#: warehouse sees the three-valued shape the audits are written for, rather
#: than a run where everything happens to match.
CRM_ROWS = [
    ("crm", "C-1001", "Ada@Example.com ", "Ada Lovelace"),
    ("crm", "C-1002", "", "Grace Hopper"),
    ("crm", "C-1003", "mary@example.com", "Mary Jackson"),
]
BILLING_ROWS = [
    ("billing", "AC-77", "ada@example.com", "A. Lovelace"),
    ("billing", "AC-91", "", "hopper, grace"),
]


def _silver(connection: duckdb.DuckDBPyConnection, relation: str) -> object:
    return connection.execute(f"SELECT * FROM {relation}").df()


@pytest.fixture(scope="module")
def run() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = warehouse()
    connection.execute(
        "CREATE TABLE bronze.crm__customers "
        "(system VARCHAR, id VARCHAR, email VARCHAR, full_name VARCHAR)"
    )
    connection.executemany("INSERT INTO bronze.crm__customers VALUES (?, ?, ?, ?)", CRM_ROWS)
    connection.execute(
        "CREATE TABLE bronze.billing__accounts "
        "(origin VARCHAR, account_ref VARCHAR, billing_email VARCHAR, account_name VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO bronze.billing__accounts VALUES (?, ?, ?, ?)", BILLING_ROWS
    )

    artifacts = compile_fixture(FIXTURE)
    # Silver first — the two mapped sources the step reads.
    materialize(connection, tuple(a for a in artifacts if "/silver/" in a.path))

    # The step's own execution, stood in for. bloomery emits the wrapper and
    # never runs it; here the resolver runs and its frames become the relations
    # the wrapper would have written, columns and all.
    outputs = resolve(
        crm=_silver(connection, "silver.customer_crm"),
        billing=_silver(connection, "silver.customer_billing"),
        threshold=_wired_threshold(),
    )
    for output, relation in (("customer", "silver.customer"), ("customer_xref", "silver.customer_xref")):
        frame = outputs[output]
        connection.register(f"_{output}_frame", frame)
        connection.execute(f"CREATE TABLE {relation} AS SELECT * FROM _{output}_frame")

    # Then gold, which reads what the step wrote.
    materialize(connection, tuple(a for a in artifacts if "/gold/" in a.path))
    yield connection
    connection.close()


#: The two audits the fixture emits, by the shorthand the tests name them by.
AUDITS = {
    "consistency": "audits/step_customer_xref_canonical_id_references_customer.sql",
    "confidence": "audits/step_customer_confidence_is_high.sql",
}


def _audit(relation: str, which: str = "confidence") -> str:
    """One audit's runnable body, pointed at ``relation``.

    An audit addresses its model through `@this_model`, which only the target
    expands — so the relation is substituted here, which is also what lets a
    test run the same audit against a deliberately dirtied copy.
    """
    artifact = next(a for a in compile_fixture(FIXTURE) if a.path == AUDITS[which])
    return audit_body(artifact, relation)


def test_the_mart_over_a_step_produced_entity_runs(run: duckdb.DuckDBPyConnection) -> None:
    """The claim D36/D37 make: a step output is an entity like any other, so a
    mart reads it with nothing target-specific in the way.

    Executed rather than read, because a mart projecting a column the step's
    wrapper does not write is a compile-clean model that fails on first run —
    and the compiler cannot see the difference.
    """
    rows = run.execute(
        "SELECT canonical_id, resolved_day FROM gold.mart_customers ORDER BY canonical_id"
    ).fetchall()
    # Two customers out of five source rows at the wiring's `0.9`: Ada matched
    # across the two systems by email, Mary is CRM-only. Grace's two rows score
    # `0.85` on the name and resolve to nobody, so she is in the crosswalk and
    # not in the mart — a mart counts resolved customers, and a threshold that
    # refuses a match has to mean one fewer of them.
    assert len(rows) == 2
    assert all(row[1] is not None for row in rows)


def test_every_source_row_reaches_the_crosswalk(run: duckdb.DuckDBPyConnection) -> None:
    """The crosswalk is a total map from source rows, and that is what makes it
    safe to join through. A resolver that dropped its unmatched rows would give
    a warehouse that looks clean and is short."""
    (count,) = run.execute("SELECT COUNT(*) FROM silver.customer_xref").fetchone() or (0,)
    assert count == len(CRM_ROWS) + len(BILLING_ROWS)


def test_two_systems_agree_on_one_customer(run: duckdb.DuckDBPyConnection) -> None:
    """`crm/C-1001` and `billing/AC-77` share no identifier and resolve to one
    `canonical_id` — asserted here through the *relations*, so it covers the
    mapping's normalization too: the CRM's `` Ada@Example.com `` only matches
    after `lower` and `trim` have run in the silver model."""
    rows = run.execute(
        "SELECT canonical_id FROM silver.customer_xref "
        "WHERE (source_system, source_id) IN (('crm', 'C-1001'), ('billing', 'AC-77'))"
    ).fetchall()
    assert len({row[0] for row in rows}) == 1


def test_the_sibling_consistency_audit_passes_on_a_real_run(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """RFC 0017 D40/D43: the declared `references:` between the two outputs.

    An audit passes when it returns no rows. This one runs against frames the
    resolver genuinely produced, so it is checking the two siblings against
    each other rather than against hand-written specimens.

    The audit is **three-valued** — it skips a NULL child rather than failing
    it — and at the wiring's threshold there are NULL children to skip, so the
    `IS NULL` branch is exercised rather than merely emitted. Pinned here,
    because a run where everything resolved would pass this audit whether that
    branch worked or not.
    """
    (unresolved,) = run.execute(
        "SELECT COUNT(*) FROM silver.customer_xref WHERE canonical_id IS NULL"
    ).fetchone() or (0,)
    assert unresolved == 2, "the audit's NULL branch needs NULLs to be worth running"
    assert run.execute(_audit("silver.customer_xref", "consistency")).fetchall() == []


def test_the_confidence_rule_blocks_a_low_confidence_match(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """The quality rule at the escape hatch's boundary (RFC 0017 §1).

    The rule is `on_fail: fail`, so its audit is blocking: a row below `0.8`
    stops the run. Seeded into a copy of the relation rather than the shared
    one, because the module's other assertions describe a clean run.
    """
    assert run.execute(_audit("silver.customer")).fetchall() == []

    run.execute("CREATE TABLE silver.customer_dubious AS SELECT * FROM silver.customer")
    run.execute(
        "INSERT INTO silver.customer_dubious VALUES ('cust_dubious', 0.42, TIMESTAMP '2026-01-01')"
    )
    try:
        flagged = run.execute(_audit("silver.customer_dubious")).fetchall()
        assert [row[0] for row in flagged] == ["cust_dubious"]
    finally:
        run.execute("DROP TABLE silver.customer_dubious")
