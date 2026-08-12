"""What an ``expression`` rule may read (RFC 0016 §5.3 → D95).

``ExpressionRule.expr`` is a bare string parsed and spliced into the silver
model, and until D95 nothing checked it — the one authored-SQL surface in the
framework with no resolution step, while every neighbour has one: ``dedupe``
columns (D47), ``reconcile`` sides against a closed grammar, mart ``assert``
measures, recipe aliases exactly, ``coverage`` endpoints (D91). Its own
docstring promised "a boolean row predicate over the entity's own columns";
this module is that promise made checkable.

The subquery refusal is the load-bearing one, and it is about *corruption* at
least as much as access — see the execution test at the bottom, which is why
the rule is refused rather than merely scoped.
"""

from __future__ import annotations

import duckdb
import pytest

from bloomery import Target, compile_project, load_project
from bloomery.errors import GuardrailError
from support.compiling import extract_select

pytestmark = pytest.mark.unit

MAPPING = (
    "mapping_version: 1\ntarget: t\nsource: raw__t\n"
    'key:\n  k: {from: "$.k", transform: [to_string]}\n'
    'fields:\n  amt: {from: "$.amt", transform: [{name: to_decimal, args: [12, 4]}]}\n'
    '  live: {from: "$.live", transform: [to_bool]}\n'
    'unmapped: ["$._load_id", "$._ingested_at", "$._source_row_id"]\n'
)


def entity_model(expr: str) -> str:
    return f"""
spec_version: 1
entities:
  t:
    grain: one row per t
    key: [k]
    fields:
      k: {{type: string, required: true}}
      amt: {{type: 'decimal(12,4)'}}
      live: {{type: bool}}
      ghost: {{type: int}}
    quarantine: {{retention: 90d}}
    quality:
      - {{rule: expression, name: r, expr: "{expr}", on_fail: flag}}
"""


def compile_silver(expr: str) -> str:
    artifacts = compile_project(
        load_project({"entity_model": entity_model(expr), "mapping": MAPPING}),
        target=Target.SQLMESH,
        dialect="duckdb",
    )
    return next(a.content for a in artifacts if a.path.endswith("silver/t.sql"))


# ....................... #
# What it refuses


def test_a_subquery_is_refused() -> None:
    """The access half: a row rule is evaluated inside the model's own SELECT,
    so a subquery reads a relation the rule cannot see — including, where the
    naming policy is the tenant seam, another tenant's."""
    with pytest.raises(GuardrailError, match="contains a subquery"):
        compile_silver("amt > (SELECT MAX(x) FROM other.tenant_secrets)")


def test_a_column_the_entity_does_not_declare_is_refused() -> None:
    """The typo D47 already refuses for ``dedupe``, in its own words 'a
    run-time binder failure on a model that compiled clean'."""
    with pytest.raises(GuardrailError, match="reads no_such_column"):
        compile_silver("no_such_column > 0")


def test_a_qualified_column_is_refused() -> None:
    """The extract supplies the qualifier, so a written one either names a
    relation the rule cannot read or shadows bloomery's own."""
    with pytest.raises(GuardrailError, match="qualifies other.amt"):
        compile_silver("other.amt > 0")


def test_unparseable_sql_is_a_guardrail_error_not_a_crash() -> None:
    """It reaches ``parse_one`` either way; the difference is whether the
    author gets a batched refusal at a source path or a sqlglot traceback."""
    with pytest.raises(GuardrailError, match="not parseable SQL"):
        compile_silver("amt >")


def test_the_refusal_names_the_columns_that_are_readable() -> None:
    """A refusal that does not say what *is* allowed makes the author guess."""
    with pytest.raises(GuardrailError, match=r"Known columns:.*'amt'"):
        compile_silver("nope > 0")


# ....................... #
# What it still allows — the control


@pytest.mark.parametrize(
    "expr",
    [
        "amt > 0",
        "amt > 0 AND k IS NOT NULL",
        "CASE WHEN amt > 0 THEN TRUE ELSE FALSE END",
        "_ingested_at IS NOT NULL",
    ],
)
def test_an_ordinary_row_predicate_still_compiles(expr: str) -> None:
    """A check that refused everything would pass every test above. Ingestion
    metadata is readable for the same reason ``dedupe`` may order by it: no
    mapping declares it, and it is in the extract regardless."""
    assert "_quality_flags" in compile_silver(expr)


# ....................... #
# Why a subquery is refused rather than scoped


def test_the_qualifier_pass_would_have_corrupted_a_subquery() -> None:
    """The measured defect, kept as the reason the refusal exists.

    The pass that binds a bare column to the extract descends *into* a
    subquery, so ``amt > (SELECT amt FROM bronze.other)`` was emitted as
    ``_extract.amt > (SELECT _extract.amt FROM bronze.other)`` — correlated to
    the outer row, reading nothing from ``other``. With ``amt`` 10 against 1
    the author's predicate is true, so the rule must not fire; it fired,
    flagging a good row, and under ``quarantine`` that diverts it out of
    silver.

    Asserted by *executing* the shape the rule now refuses, built by hand: the
    emitted form can no longer be produced, and a claim about why a refusal
    exists is worth only as much as the demonstration behind it.
    """
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE SCHEMA bronze")
    connection.execute("CREATE TABLE bronze.other (amt DECIMAL(12,4))")
    connection.execute("INSERT INTO bronze.other VALUES (1)")
    connection.execute("CREATE TABLE _extract (amt DECIMAL(12,4))")
    connection.execute("INSERT INTO _extract VALUES (10)")

    author_meant = "SELECT _extract.amt > (SELECT amt FROM bronze.other LIMIT 1) FROM _extract"
    corrupted = (
        "SELECT _extract.amt > (SELECT _extract.amt FROM bronze.other LIMIT 1) FROM _extract"
    )
    assert connection.execute(author_meant).fetchone() == (True,)
    assert connection.execute(corrupted).fetchone() == (False,)


def test_a_legitimate_rule_still_reaches_the_emitted_sql() -> None:
    """End to end: the predicate an author writes survives to the model."""
    body = compile_silver("amt > 0")
    assert "_extract.amt > 0" in extract_select(body)


# ....................... #
# Round two of review, each reproduced before it was fixed


def test_a_declared_field_no_mapping_lowers_is_refused() -> None:
    """``ghost`` is declared on the entity and filled by no mapping, so it is
    never projected — the scope check read *declared fields* and let it
    through, which is the binder failure this module exists to prevent wearing
    a different hat. The readable set is now the lowered columns."""
    with pytest.raises(GuardrailError, match="reads ghost"):
        compile_silver("ghost > 0")


@pytest.mark.parametrize("expr", ["amt", "amt + 1"])
def test_a_non_boolean_expression_is_refused(expr: str) -> None:
    """``ExpressionRule`` is defined as a boolean row predicate and the
    lowering emits ``NOT (...)`` around it, which a numeric operand either
    refuses or coerces differently per dialect."""
    with pytest.raises(GuardrailError, match="not a boolean predicate"):
        compile_silver(expr)


def test_a_boolean_column_on_its_own_is_still_a_predicate() -> None:
    """The half a naive shape check would break: ``live`` is a ``bool`` field,
    so naming it alone is a perfectly good rule. Decided from the model rather
    than the AST, which is the only place the answer exists."""
    assert "_quality_flags" in compile_silver("live")


def test_a_second_statement_is_refused() -> None:
    """``parse_one`` returns a ``Block`` for ``amt > 0; DELETE FROM x``, and
    the lowering would wrap the whole block in ``NOT (...)`` — emitting
    invalid SQL rather than refusing."""
    with pytest.raises(GuardrailError, match="more than one statement"):
        compile_silver("amt > 0; DELETE FROM x")


def test_an_unquoted_column_matches_case_insensitively() -> None:
    """An unquoted SQL identifier is case-insensitive on all three targets, so
    a rule saying ``AMT`` names the same column as a field spelled ``amt``.
    Refusing it would have been a new false refusal, not a fix."""
    assert "_quality_flags" in compile_silver("AMT > 0")
