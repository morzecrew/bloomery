"""Violation predicates (RFC 0016 §5.4, D18/D19).

Three things are asserted here, and RFC 0016 §6 names all three:

- the **exhaustive** rule × disposition lowering matrix — ``product(ALL_RULES,
  ALL_DISPOSITIONS)``, every pair **executed against DuckDB in the position
  that disposition puts it in**, because "a missing pair is exactly the gap
  that ships";
- **three-valued logic** per rule: a NULL-involved comparison evaluates to SQL
  ``UNKNOWN`` and must not fire. This is asserted by *executing* the predicate
  against a null row in DuckDB and requiring ``NULL``, not ``TRUE`` — reading
  the AST would only prove the shape, not the semantics;
- **disposition precedence** ``fail > quarantine > flag``, and the rule that a
  quarantined row records all its failures, flag-level ones included.

**Why the matrix executes rather than parses.** It used to render each pair and
assert ``parse_one(f"SELECT 1 WHERE {rendered}") is not None``, which is two
failures wearing one name. The disposition axis was inert — ``violation()``
never reads ``on_fail``, so thirty parametrizations carried ten distinct
assertions — and the assertion itself was satisfied by SQL no engine will run:
``parse_one`` happily parses a window function inside a ``WHERE`` clause, which
is exactly the shape that shipped broken for ``unique`` at ``quarantine`` and
``fail`` (D33). A pair is only *lowered* if the artifact it produces is legal
where the lowering puts it, so each pair is built here the way the emitter
builds it — the windowed verdict projected once (:func:`stage`), the routing
split through :func:`~bloomery.quality.routing_predicate`, the flag collection
through :func:`~bloomery.quality.flags_expression` — and then run.

One pair is genuinely unrepresentable: ``referential`` at ``fail`` (D6). It is
asserted as a **parse refusal** rather than passing silently, and
``referential``'s real axis — ``on_missing`` — is executed beside the others.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product
from typing import TYPE_CHECKING

import duckdb
import pydantic
import pytest
from sqlglot import exp, parse_one
from support.quality_rules import ON_MISSING_RULES, referential_rule, rule_of_kind

from bloomery.ir import OnFail, QualityRuleIR
from bloomery.quality import (
    ALL_DISPOSITIONS,
    ALL_ON_MISSING,
    ALL_RULES,
    FIELD_RULES,
    ROW_RULES,
    UNKNOWN_MEMBER,
    disposition,
    failed_rule_names,
    flags_expression,
    ref_alias,
    routing_predicate,
    sole_via_column,
    source_alias,
    unknown_member_case,
    verdict,
    violation,
    window_alias,
    windowed,
    worst,
)
from bloomery.spec.quality import ReferentialRule

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


# ....................... #
# The exhaustive matrix (RFC 0016 §6), executed


@dataclass(frozen=True)
class _Specimen:
    """One rule kind's two-row population: what violates it, and what does not.

    ``columns`` is the DDL after the ``row_id`` identity; ``rows`` are its
    tuples; ``violating`` names the identities whose verdict must be TRUE. A
    clean row is not decoration — a predicate that fires on everything passes
    every "the violation was detected" assertion there is.
    """

    columns: str
    rows: tuple[tuple[object, ...], ...]
    violating: tuple[str, ...]


#: A specimen per kind of :data:`~bloomery.quality.ALL_RULES` except
#: ``referential``, which needs a joined probe and has its own axis below.
_SPECIMENS: dict[str, _Specimen] = {
    # The marker is "NULL although every source it reads was not" (§5.2), so
    # the clean row is a *genuine* null source, not merely a castable value.
    "coercible": _Specimen(
        "amount VARCHAR, _src_amount_coercible_0000 VARCHAR",
        (("bad", None, "twelve"), ("ok", None, None)),
        ("bad",),
    ),
    "not_null": _Specimen("amount VARCHAR", (("bad", None), ("ok", "1")), ("bad",)),
    "range": _Specimen("amount INTEGER", (("bad", -1), ("ok", 5)), ("bad",)),
    "length": _Specimen("amount VARCHAR", (("bad", "123456789"), ("ok", "abc")), ("bad",)),
    "pattern": _Specimen("amount VARCHAR", (("bad", "abc"), ("ok", "ABC")), ("bad",)),
    "in_enum": _Specimen("amount VARCHAR", (("bad", "z"), ("ok", "a")), ("bad",)),
    "in_set": _Specimen("amount VARCHAR", (("bad", "z"), ("ok", "a")), ("bad",)),
    # A window predicate needs a population: two rows share a value inside one
    # slice, a third shares it across slices and so is nobody's duplicate (D5).
    "unique": _Specimen(
        "amount VARCHAR, order_date VARCHAR",
        (
            ("bad", "dup", "2024-01-01"),
            ("bad_twin", "dup", "2024-01-01"),
            ("ok", "dup", "2024-01-02"),
        ),
        ("bad", "bad_twin"),
    ),
    "expression": _Specimen(
        "discount INTEGER, unit_price INTEGER, quantity INTEGER",
        (("bad", 100, 10, 2), ("ok", 1, 10, 2)),
        ("bad",),
    ),
}

#: Every kind the ``on_fail`` axis applies to. ``referential`` carries
#: ``on_missing`` instead and is exercised on that axis below.
_DISPOSABLE_RULES = tuple(kind for kind in ALL_RULES if kind != "referential")

_EXTRACT = "_extract"


@pytest.fixture
def seeded() -> Iterator[duckdb.DuckDBPyConnection]:
    with duckdb.connect(":memory:") as connection:
        yield connection


def _seed(connection: duckdb.DuckDBPyConnection, specimen: _Specimen) -> None:
    connection.execute(f"CREATE TABLE _rows (row_id VARCHAR, {specimen.columns})")
    placeholders = ", ".join("?" for _ in specimen.rows[0])
    connection.executemany(
        f"INSERT INTO _rows VALUES ({placeholders})", [list(row) for row in specimen.rows]
    )


def stage(rule: QualityRuleIR) -> str:
    """The staged extract the emitter's ``_stage`` builds (D33).

    A windowed verdict is computed **once**, as a projection above the dedupe
    ``QUALIFY``, and read back by name from every other position; an ordinary
    rule needs no such level. Mirroring that here is the whole point — the
    positions below then receive exactly what the emitter's positions receive.
    """
    if not windowed(rule):
        return "SELECT * FROM _rows"
    projected = violation(rule).sql(dialect="duckdb")
    return f"SELECT *, ({projected}) AS {window_alias(rule)} FROM _rows"


def _identities(connection: duckdb.DuckDBPyConnection, sql: str) -> tuple[str, ...]:
    return tuple(sorted(str(row[0]) for row in connection.execute(sql).fetchall()))


@pytest.mark.parametrize(("kind", "on_fail"), list(product(_DISPOSABLE_RULES, ALL_DISPOSITIONS)))
def test_every_rule_disposition_pair_executes_where_that_disposition_puts_it(
    seeded: duckdb.DuckDBPyConnection, kind: str, on_fail: OnFail
) -> None:
    """The §6 matrix, made real on both axes.

    ``flag`` lands in the single ``_quality_flags`` construct pass; ``quarantine``
    lands in the routing ``WHERE`` **and** in the conservation audit's
    ``SUM(CASE …)``; ``fail`` lands in a blocking audit body's ``WHERE``. Each is
    executed, and each is required to identify the specimen's violating rows and
    only those — so neither a predicate that never fires nor one that always
    fires can pass.
    """
    rule = rule_of_kind(kind, on_fail)
    specimen = _SPECIMENS[kind]
    _seed(seeded, specimen)
    staged = stage(rule)

    if on_fail is OnFail.FLAG:
        collection = flags_expression([(rule.name, verdict(rule))], arrays=True)
        rows = seeded.execute(
            f"SELECT row_id, {collection.sql(dialect='duckdb')} FROM ({staged}) AS {_EXTRACT}"
        ).fetchall()
        fired = tuple(sorted(row_id for row_id, flags in rows if rule.name in flags))
        # Never NULL, empty for a clean row (D23) — the read side of the
        # contract, asserted where the collection is built.
        assert all(flags is not None for _row_id, flags in rows)
        assert all(flags == [] for row_id, flags in rows if row_id not in specimen.violating)
    elif on_fail is OnFail.QUARANTINE:
        diverted = routing_predicate([rule], quarantined=True).sql(dialect="duckdb")
        keeps = routing_predicate([rule], quarantined=False).sql(dialect="duckdb")
        fired = _identities(seeded, f"SELECT row_id FROM ({staged}) AS {_EXTRACT} WHERE {diverted}")
        kept = _identities(seeded, f"SELECT row_id FROM ({staged}) AS {_EXTRACT} WHERE {keeps}")
        # The split is a partition: every row on exactly one side (§6's
        # conservation law is this statement, counted).
        assert tuple(sorted((*fired, *kept))) == tuple(sorted(str(row[0]) for row in specimen.rows))
        # …and the same predicate inside an aggregate's argument, which is the
        # third position the lowering reads a verdict from.
        counted = seeded.execute(
            f"SELECT SUM(CASE WHEN {diverted} THEN 1 ELSE 0 END) FROM ({staged}) AS {_EXTRACT}"
        ).fetchone()
        assert counted == (len(specimen.violating),)
    else:
        body = verdict(rule).sql(dialect="duckdb")
        fired = _identities(seeded, f"SELECT row_id FROM ({staged}) AS {_EXTRACT} WHERE {body}")

    assert fired == tuple(sorted(specimen.violating))


def test_the_matrix_covers_every_catalogue_kind() -> None:
    """The specimens are the matrix's data; a kind without one would silently
    drop out of ``product`` above rather than fail."""
    assert set(_SPECIMENS) | {"referential"} == set(ALL_RULES)


@pytest.mark.parametrize("on_fail", ["fail", "flag", "quarantine"])
def test_referential_refuses_an_on_fail_disposition_at_parse(on_fail: str) -> None:
    """The one unrepresentable cell of the matrix, refused rather than skipped.

    ``referential`` carries ``on_missing``, never ``on_fail`` (D6): orphans are
    an expected, recoverable condition, and a pipeline that stops on every one
    punishes the normal case. The refusal is at parse because the spec model
    forbids unknown keys — so ``on_fail: fail`` on a referential rule cannot be
    written at all, which is what makes the missing cell a decision instead of
    a hole.
    """
    with pytest.raises(pydantic.ValidationError, match="on_fail"):
        ReferentialRule.model_validate(
            {
                "rule": "referential",
                "via": "item_of_order",
                "on_missing": "flag",
                "on_fail": on_fail,
            }
        )


def test_referential_refuses_fail_as_an_on_missing_value() -> None:
    """The same decision from the other side: ``fail`` is not in the
    ``on_missing`` vocabulary either (D6)."""
    with pytest.raises(pydantic.ValidationError, match="on_missing"):
        ReferentialRule.model_validate(
            {"rule": "referential", "via": "item_of_order", "on_missing": "fail"}
        )


_REF_ROWS = (("orphan", "O9"), ("resolved", "O1"), ("null_fk", None))
_REF_PARENTS = (("O1",),)


def _seed_referential(connection: duckdb.DuckDBPyConnection) -> str:
    """The dependent extract LEFT JOINed to its referenced silver entity — the
    §5.4 probe, in the shape the emitter joins it."""
    connection.execute("CREATE TABLE _rows (row_id VARCHAR, order_id VARCHAR)")
    connection.executemany("INSERT INTO _rows VALUES (?, ?)", [list(r) for r in _REF_ROWS])
    connection.execute("CREATE TABLE _parents (order_id VARCHAR)")
    connection.executemany("INSERT INTO _parents VALUES (?)", [list(r) for r in _REF_PARENTS])
    alias = ref_alias("item_of_order")
    return (
        f"_rows AS {_EXTRACT} LEFT JOIN _parents AS {alias} "
        f"ON {_EXTRACT}.order_id = {alias}.order_id"
    )


@pytest.mark.parametrize("on_missing", ALL_ON_MISSING)
def test_referential_executes_where_its_on_missing_puts_it(
    seeded: duckdb.DuckDBPyConnection, on_missing: str
) -> None:
    """``referential`` contributes its own axis (RFC 0016 §6), and each value
    lands in a different position: ``unknown_member`` rewrites the fk in the
    entity's **projection**, ``quarantine`` drives the routing ``WHERE``,
    ``flag`` joins the flag construct. All three read the same LEFT JOIN probe,
    and none of them may fire on the NULL fk (D19)."""
    rule = ON_MISSING_RULES[on_missing]
    source = _seed_referential(seeded)

    if on_missing == "unknown_member":
        rewrite = unknown_member_case(rule, table=_EXTRACT).sql(dialect="duckdb")
        rows = dict(seeded.execute(f"SELECT {_EXTRACT}.row_id, {rewrite} FROM {source}").fetchall())
        # The orphan takes the reserved member; the resolved fk is untouched;
        # the NULL fk stays NULL — Document 5's COALESCE sketch got that wrong.
        assert rows == {"orphan": UNKNOWN_MEMBER, "resolved": "O1", "null_fk": None}
    elif on_missing == "quarantine":
        diverted = routing_predicate([rule], _EXTRACT, quarantined=True).sql(dialect="duckdb")
        keeps = routing_predicate([rule], _EXTRACT, quarantined=False).sql(dialect="duckdb")
        assert _identities(seeded, f"SELECT {_EXTRACT}.row_id FROM {source} WHERE {diverted}") == (
            "orphan",
        )
        assert _identities(seeded, f"SELECT {_EXTRACT}.row_id FROM {source} WHERE {keeps}") == (
            "null_fk",
            "resolved",
        )
    else:
        collection = flags_expression([(rule.name, verdict(rule, _EXTRACT))], arrays=True)
        rows = dict(
            seeded.execute(
                f"SELECT {_EXTRACT}.row_id, {collection.sql(dialect='duckdb')} FROM {source}"
            ).fetchall()
        )
        assert rows == {"orphan": [rule.name], "resolved": [], "null_fk": []}


def test_the_unknown_member_rewrite_refuses_a_composite_relationship(
    seeded: duckdb.DuckDBPyConnection,
) -> None:
    """D48 refuses composite ``unknown_member`` at compile time, which is what
    makes :func:`~bloomery.quality.sole_via_column` total. Reading ``[0]`` and
    ignoring the rest would be indistinguishable from the half-sentinel bug the
    day the guardrail is widened, so the accessor refuses loudly instead."""
    del seeded
    composite = QualityRuleIR(
        name="item_of_order_referential",
        kind="referential",
        column=None,
        on_fail=None,
        params=(
            ("on_missing", "unknown_member"),
            ("relationship", "item_of_order"),
            ("to_entity", "order"),
            ("via_0000", "order_id=order_id"),
            ("via_0001", "tenant=tenant"),
        ),
    )
    with pytest.raises(ValueError, match="D48"):
        sole_via_column(composite)
    with pytest.raises(ValueError, match="D48"):
        unknown_member_case(composite)
    # …and the single-column shape every compiling spec has is unchanged.
    assert sole_via_column(ON_MISSING_RULES["unknown_member"]) == "order_id"


def test_the_catalogue_is_the_union_of_the_two_levels() -> None:
    """``ALL_RULES`` is what the matrix iterates, so it must not drift from
    the field/row split the pipeline order separates."""
    assert set(ALL_RULES) == set(FIELD_RULES) | set(ROW_RULES)
    assert tuple(sorted(ALL_RULES)) == ALL_RULES


def test_a_predicate_carrying_a_window_declares_itself_windowed() -> None:
    """The catalogue's own statement of where its predicates are legal.

    SQL allows a window function in a projection and forbids it in a ``WHERE``
    clause, and the lowering reads a violation predicate from *both* — routing
    filters on it, an audit body filters on it, the conservation audit sums
    over it. A kind whose predicate contains a window must therefore be
    computed once as a column and referenced by name
    (:func:`~bloomery.quality.window_alias`), and this is the assertion that
    keeps the declaration and the predicate from drifting: a rule that grows a
    window later fails here rather than at the first engine that binds it.
    """
    for kind in ALL_RULES:
        rule = rule_of_kind(kind)
        carries = violation(rule).find(exp.Window) is not None
        assert carries is windowed(rule), kind


def test_the_window_alias_is_derived_from_the_rule_name() -> None:
    """Two windowed rules on one entity each need their own column."""
    assert window_alias(rule_of_kind("unique")) == "_win_amount_unique"


@pytest.mark.parametrize("on_missing", ALL_ON_MISSING)
def test_referential_lowers_once_per_on_missing(on_missing: str) -> None:
    """``referential`` contributes its own axis (RFC 0016 §6), one row per
    ``on_missing`` — each asserting its §5.4 lowering."""
    rule = ON_MISSING_RULES[on_missing]
    probe = violation(rule).sql(dialect="duckdb")
    # Every disposition shares the same LEFT JOIN probe (§5.4's table).
    assert probe == "_ref_item_of_order.order_id IS NULL AND (NOT order_id IS NULL)"
    if on_missing == "unknown_member":
        rewrite = unknown_member_case(rule).sql(dialect="duckdb")
        assert rewrite.startswith("CASE WHEN _ref_item_of_order.order_id IS NULL")
        assert f"THEN '{UNKNOWN_MEMBER}'" in rewrite
        assert rewrite.endswith("ELSE order_id END")


def test_ref_alias_is_derived_from_the_relationship_not_the_entity() -> None:
    """Two relationships may point at the same entity; each needs its own
    probe."""
    assert ref_alias("item_of_order") == "_ref_item_of_order"
    assert ref_alias("item_of_parent_order") == "_ref_item_of_parent_order"


# ....................... #
# Three-valued logic (RFC 0016 D19) — executed, not merely inspected


def _evaluate(rule: QualityRuleIR, row: dict[str, object]) -> bool | None:
    """Evaluate a violation predicate against one row in DuckDB."""
    columns = ", ".join(f"? AS {name}" for name in row)
    sql = f"SELECT ({violation(rule).sql(dialect='duckdb')}) FROM (SELECT {columns})"
    with duckdb.connect(":memory:") as connection:
        result = connection.execute(sql, list(row.values())).fetchone()
    assert result is not None
    return result[0]


#: Rules whose violation predicate must stay ``UNKNOWN`` on a null operand
#: (D19: ``not_null`` and ``coercible`` are the two that own nulls).
_NULL_SILENT = ("range", "length", "pattern", "in_enum", "in_set", "unique", "expression")


@pytest.mark.parametrize("kind", _NULL_SILENT)
def test_a_null_operand_never_fires(kind: str) -> None:
    rule = rule_of_kind(kind)
    row: dict[str, object] = {"amount": None, "order_date": "2024-01-01"}
    if kind == "expression":
        row = {"discount": None, "unit_price": 10, "quantity": 2}
    assert _evaluate(rule, row) is not True


@pytest.mark.parametrize("kind", _NULL_SILENT)
def test_a_definite_violation_does_fire(kind: str) -> None:
    """The mirror of the test above: silence on NULL must not be silence on
    everything."""
    violations: dict[str, dict[str, object]] = {
        "range": {"amount": -1, "order_date": "2024-01-01"},
        "length": {"amount": "123456789", "order_date": "2024-01-01"},
        "pattern": {"amount": "abc", "order_date": "2024-01-01"},
        "in_enum": {"amount": "z", "order_date": "2024-01-01"},
        "in_set": {"amount": "z", "order_date": "2024-01-01"},
        "unique": {"amount": "a", "order_date": "2024-01-01"},
        "expression": {"discount": 100, "unit_price": 10, "quantity": 2},
    }
    if kind == "unique":
        pytest.skip("a window predicate needs more than one row; covered below")
    assert _evaluate(rule_of_kind(kind), violations[kind]) is True


def test_unique_counts_within_the_partition_slice_and_ignores_nulls() -> None:
    """The slice is the entity's partition (D5): duplicates in *different*
    slices are not this rule's business, and two null rows are nobody's."""
    rendered = violation(rule_of_kind("unique")).sql(dialect="duckdb")
    sql = f"SELECT amount, ({rendered}) AS fired FROM rows ORDER BY 1 NULLS LAST"
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE rows (amount VARCHAR, order_date VARCHAR)")
        connection.executemany(
            "INSERT INTO rows VALUES (?, ?)",
            [
                ("dup", "2024-01-01"),
                ("dup", "2024-01-01"),  # same slice — a duplicate
                ("dup", "2024-01-02"),  # different slice — not a duplicate
                (None, "2024-01-01"),
                (None, "2024-01-01"),  # two nulls are not_null's business
            ],
        )
        rows = connection.execute(sql).fetchall()
    # The null rows read FALSE rather than NULL — the explicit ``IS NOT NULL``
    # conjunct is definitively false, and "does not fire" is what D19 asks for.
    assert rows == [("dup", True), ("dup", True), ("dup", False), (None, False), (None, False)]


def test_not_null_owns_nulls() -> None:
    rule = rule_of_kind("not_null")
    assert _evaluate(rule, {"amount": None}) is True
    assert _evaluate(rule, {"amount": 1}) is False


def test_coercible_fires_only_when_the_source_was_present() -> None:
    """The marker is "the projection is NULL although every source it reads
    was not" — a genuinely null source is a legitimate null, not a coercion
    failure (RFC 0016 §5.2)."""
    rule = rule_of_kind("coercible")
    alias = source_alias(rule, 0)
    assert _evaluate(rule, {"amount": None, alias: "twelve"}) is True
    assert _evaluate(rule, {"amount": None, alias: None}) is False
    assert _evaluate(rule, {"amount": 12, alias: "12"}) is False


def test_a_null_fk_is_not_an_orphan() -> None:
    """D19's headline correction of Document 5's ``COALESCE`` sketch."""
    rule = referential_rule("quarantine")
    predicate = violation(rule, table="_extract").sql(dialect="duckdb")
    sql = (
        f"SELECT ({predicate}) FROM (SELECT NULL AS order_id) AS _extract, "
        "(SELECT NULL AS order_id) AS _ref_item_of_order"
    )
    with duckdb.connect(":memory:") as connection:
        assert connection.execute(sql).fetchone() == (False,)


def test_in_set_renders_an_integer_member_as_a_number_literal() -> None:
    """The spec surface admits ``int`` beside ``str`` (``values: [1, 2]``), and
    the IR carries params as text — so without the aligned ``numeric_NNNN``
    params the member's type is lost and every one renders as a string.

    ``tier NOT IN ('1')`` on an integer column is coerced by DuckDB and
    Postgres and **refused** by Trino: one spec, one engine answering and
    another failing, which is the portability bug §5.3 exists to prevent. The
    string member beside it stays a string, because a set that mixes the two is
    still one set.
    """
    rule = QualityRuleIR(
        name="tier_in_set",
        kind="in_set",
        column="tier",
        on_fail=OnFail.FLAG,
        params=(
            ("numeric_0000", "true"),
            ("numeric_0001", "false"),
            ("value_0000", "1"),
            ("value_0001", "gold"),
        ),
    )
    for dialect in ("duckdb", "postgres", "trino"):
        assert violation(rule).sql(dialect=dialect) == "NOT tier IN (1, 'gold')", dialect

    # …and executed over the column type such a set is actually written for.
    typed = replace(rule, params=(("numeric_0000", "true"), ("value_0000", "1")))
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE t (tier INTEGER)")
        connection.execute("INSERT INTO t VALUES (1), (3)")
        rows = connection.execute(
            f"SELECT tier, ({violation(typed).sql(dialect='duckdb')}) FROM t ORDER BY tier"
        ).fetchall()
    assert rows == [(1, False), (3, True)]


def test_in_set_without_the_type_params_is_all_strings() -> None:
    """The params are emitted only when the set holds an integer, so an
    all-string set's IR bytes — and its SQL — are exactly what they were."""
    rule = QualityRuleIR(
        name="status_in_set",
        kind="in_set",
        column="status",
        on_fail=OnFail.FLAG,
        params=(("value_0000", "open"), ("value_0001", "closed")),
    )
    assert violation(rule).sql() == "NOT status IN ('open', 'closed')"


def test_in_enum_members_are_always_strings() -> None:
    """An ``enum_map`` chain maps text to text, so its admissible set is
    textual by construction — the ``in_set`` typing above is not shared."""
    rendered = violation(rule_of_kind("in_enum")).sql()
    assert rendered == "NOT amount IN ('a', 'b')"


def test_composite_predicates_are_parenthesised() -> None:
    """SQLGlot adds no precedence parentheses of its own; a mis-parenthesised
    quality predicate is a silently wrong disposition."""
    rendered = violation(rule_of_kind("range")).sql()
    assert rendered == "amount < 0 OR amount > 1000000"
    nested = violation(rule_of_kind("coercible")).sql()
    assert nested == "amount IS NULL AND (NOT _src_amount_coercible_0000 IS NULL)"


def test_expression_bodies_are_qualified_and_negated_as_a_whole() -> None:
    rendered = violation(rule_of_kind("expression"), table="_extract").sql()
    assert rendered == ("NOT (_extract.discount <= _extract.unit_price * _extract.quantity)")


def test_qualification_never_mutates_the_input_ast() -> None:
    rule = rule_of_kind("range")
    first = violation(rule, table="_extract").sql()
    second = violation(rule).sql()
    assert first.startswith("_extract.")
    assert not second.startswith("_extract.")


# ....................... #
# Disposition precedence (RFC 0016 D18)


def test_severity_order_is_fail_over_quarantine_over_flag() -> None:
    flag = rule_of_kind("range", OnFail.FLAG)
    quarantine = rule_of_kind("length", OnFail.QUARANTINE)
    fail = rule_of_kind("not_null", OnFail.FAIL)
    assert worst([flag]) is OnFail.FLAG
    assert worst([flag, quarantine]) is OnFail.QUARANTINE
    assert worst([flag, quarantine, fail]) is OnFail.FAIL
    assert worst([quarantine, fail]) is OnFail.FAIL
    assert worst([]) is None


def test_a_quarantined_row_records_its_flag_level_failures_too() -> None:
    """D18: ``failed_rules`` is the full account of why a row is not in the
    entity, not merely the part that diverted it."""
    rules = [
        rule_of_kind("range", OnFail.FLAG),
        rule_of_kind("length", OnFail.QUARANTINE),
        rule_of_kind("not_null", OnFail.FLAG),
    ]
    assert failed_rule_names(rules) == ("amount_length", "amount_not_null", "amount_range")


def test_referential_dispositions_map_onto_the_three_value_model() -> None:
    """``unknown_member`` keeps the row, so it reads as ``FLAG`` — never
    ``QUARANTINE``, which would divert the row the reserved member exists to
    keep."""
    assert disposition(ON_MISSING_RULES["flag"]) is OnFail.FLAG
    assert disposition(ON_MISSING_RULES["quarantine"]) is OnFail.QUARANTINE
    assert disposition(ON_MISSING_RULES["unknown_member"]) is OnFail.FLAG


def test_every_pair_yields_a_deterministic_disposition() -> None:
    """No rule/disposition combination needs compile-time rejection (D18):
    the outcome is defined for all of them."""
    for kind, on_fail in product(ALL_RULES, ALL_DISPOSITIONS):
        rule = rule_of_kind(kind, on_fail)
        expected = OnFail.FLAG if kind == "referential" else on_fail
        assert disposition(rule) is expected


def test_an_unknown_rule_kind_is_a_loud_key_error() -> None:
    unknown = QualityRuleIR(name="x", kind="telepathy", column="amount", on_fail=OnFail.FLAG)
    with pytest.raises(KeyError, match="telepathy"):
        violation(unknown)


def test_predicates_render_on_every_shipped_dialect() -> None:
    """One neutral AST, per-dialect legal rendering (RFC 0008 doctrine)."""
    for kind in ALL_RULES:
        node = violation(rule_of_kind(kind))
        for dialect in ("duckdb", "postgres", "trino"):
            assert isinstance(parse_one(node.sql(dialect=dialect), dialect=dialect), exp.Expression)
