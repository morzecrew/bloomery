"""The ``repair`` disposition and its recipe contract (RFC 0016 D17 → D87).

D17 deferred ``repair`` out of v1 and gated it on two things: a **repair-recipe
contract**, and a **distinct marker** separating "repaired, now correct" from
"currently flagged bad" so ``has_quality_flags`` keeps meaning *currently
suspect*. RFC 0017's step registry supplies the first; ``_quality_repairs``
is the second. Both are asserted here by running the emitted pipeline, because
the whole feature is a claim about which value ends up in the row.

The recipe under test strips a zero-width space and nothing else, while the
rule forbids a zero-width space **and** U+FFFD. That asymmetry is deliberate:
it gives the suite a row the recipe fixes and a row it cannot, which is the
only way to tell a repair from a rule that silently stopped firing.
"""

from __future__ import annotations

import duckdb
import pytest
from support.compiling import extract_select

from bloomery import ChangeClass, Target, compile_project, load_project, plan
from bloomery.resolve import build_project_ir
from bloomery.errors import SpecParseError, StepError
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.unit

ZWSP = "\u200b"
REPLACEMENT = "\ufffd"

ENTITY_MODEL = """
spec_version: 1
entities:
  customer:
    grain: one row per customer
    key: [customer_id]
    fields:
      customer_id: {type: string, required: true}
      name: {type: string}
    quarantine: {retention: 90d}
"""

#: ``name`` forbids two characters; the recipe below removes one of them.
MAPPING = """
mapping_version: 1
target: customer
source: crm__customers
key:
  customer_id: {from: "$.customer_id"}
fields:
  name:
    from: "$.name"
    transform: [to_string]
    quality:
      - rule: charset
        forbid: [U+200B, U+FFFD]
        on_fail: repair
        repair: {via: strip_invisible@1, fallback: quarantine}
unmapped: ["$._load_id", "$._ingested_at", "$._source_row_id"]
"""


def manifest(**overrides: object) -> StepManifest:
    base: dict[str, object] = {
        "ref": "strip_invisible",
        "version": 1,
        "kind": "sql_macro",
        "determinism": "pure",
        "runtime_lock": "sha256:c0ffee",
        "accepts": {"value": "string"},
        "outputs": {
            "value": {"grain": "row", "key": ["v"], "produces": {"v": {"type": "string"}}}
        },
    }
    return StepManifest.model_validate(base | overrides)


def registry(body: str = f"TRANSLATE(:value, '{ZWSP}', '')", **overrides: object) -> StepRegistry:
    return StepRegistry(
        {("strip_invisible", 1): manifest(**overrides)},
        macro_bodies={("strip_invisible", 1): body},
    )


def compile_silver(
    mapping: str = MAPPING, steps: StepRegistry | None = None
) -> dict[str, str]:
    """``{artifact stem: SELECT}`` for the silver layer of this project."""
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": mapping})
    artifacts = compile_project(
        project,
        target=Target.SQLMESH,
        dialect="duckdb",
        steps=registry() if steps is None else steps,
    )
    return {
        artifact.path.rsplit("/", 1)[-1].removesuffix(".sql"): extract_select(artifact.content)
        for artifact in artifacts
        if artifact.path.startswith("models/silver/") and artifact.path.endswith(".sql")
    }


#: ``(_source_row_id, name)`` — one row per outcome the disposition has.
ROWS = [
    ("clean", "Acme Corp"),
    ("repairable", f"Acme{ZWSP}Corp"),
    ("unrepairable", f"Acme {REPLACEMENT} Corp"),
]


@pytest.fixture
def run() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    for schema in ("bronze", "silver"):
        connection.execute(f"CREATE SCHEMA {schema}")
    connection.execute(
        "CREATE TABLE bronze.crm__customers (customer_id VARCHAR, name VARCHAR, "
        "_load_id VARCHAR, _ingested_at VARCHAR, _source_row_id VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO bronze.crm__customers VALUES (?, ?, 'load_a', '2026-01-01T00:00:00', ?)",
        [(row_id, name, row_id) for row_id, name in ROWS],
    )
    selects = compile_silver()
    for name, sql in sorted(selects.items()):
        connection.execute(f'CREATE TABLE silver."{name}" AS {sql}')
    return connection


def kept(connection: duckdb.DuckDBPyConnection) -> dict[str, tuple[str, list[str], list[str]]]:
    rows = connection.execute(
        'SELECT _source_row_id, name, _quality_flags, _quality_repairs FROM silver."customer"'
    ).fetchall()
    return {row[0]: (row[1], row[2], row[3]) for row in rows}


# ....................... #
# What the disposition actually does


def test_the_recipe_rewrites_the_value_and_the_row_is_kept(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """The point of the feature, in one row: a value that violated its rule
    reaches silver *fixed*, rather than being diverted or merely marked."""
    name, _flags, _repairs = kept(run)["repairable"]
    assert name == "AcmeCorp"


def test_a_repaired_row_is_recorded_in_the_distinct_marker_and_nowhere_else(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """D17's condition, asserted as written: the marker separating "repaired,
    now correct" from "currently flagged bad".

    ``_quality_flags`` staying empty is the load-bearing half — it is what
    ``has_quality_flags`` is derived from, so a repaired row must not read as
    suspect to any mart that already asks that question.
    """
    _name, flags, repaired = kept(run)["repairable"]
    assert repaired == ["name_charset"]
    assert flags == []


def test_a_row_the_recipe_could_not_fix_falls_to_its_fallback(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """The recipe removes a zero-width space and knows nothing about U+FFFD, so
    it runs, produces a value that still violates, and the rule's ``fallback``
    disposes of the row exactly as if no repair had been declared.

    This is why ``fallback`` is required rather than defaulted (D2): the
    alternative is a still-broken value landing in silver marked as fixed,
    which would be the ``drop`` this RFC refuses wearing a friendlier name.
    """
    assert "unrepairable" not in kept(run)
    diverted = run.execute(
        'SELECT _source_row_id, failed_rules FROM silver."customer__reject"'
    ).fetchall()
    assert diverted == [("unrepairable", ["name_charset"])]


def test_a_clean_row_is_untouched_and_records_no_repair(
    run: duckdb.DuckDBPyConnection,
) -> None:
    """The control. A recipe that ran unconditionally would rewrite this row
    too, and every assertion above would still pass."""
    assert kept(run)["clean"] == ("Acme Corp", [], [])


def test_every_row_still_lands_on_exactly_one_side(run: duckdb.DuckDBPyConnection) -> None:
    """The conservation law (§6) with a repair in the pipeline: repairing is
    not a third door out."""
    entity = run.execute('SELECT COUNT(*) FROM silver."customer"').fetchone()
    rejected = run.execute('SELECT COUNT(*) FROM silver."customer__reject"').fetchone()
    assert entity is not None
    assert rejected is not None
    assert entity[0] + rejected[0] == len(ROWS)


# ....................... #
# The shape of the emitted SQL


def test_the_marker_column_is_absent_without_a_repair_rule() -> None:
    """Unlike ``_quality_flags`` and ``_quality_ok``, this one is conditional
    — §12 budgeted the silver-schema churn once, and a third universal column
    empty for every project not using the feature is not worth re-opening every
    golden for."""
    flagged = MAPPING.replace(
        "        on_fail: repair\n        repair: {via: strip_invisible@1, fallback: quarantine}",
        "        on_fail: flag",
    )
    assert "_quality_repairs" not in compile_silver(flagged, steps=registry())["customer"]


def test_the_recipe_is_spliced_into_the_ir_rather_than_named_in_it() -> None:
    """Emission never consults the registry: the body travels in the rule's
    params the way an ``expression`` rule's does, so a version or
    ``runtime_lock`` bump lands in the IR where the fingerprint sees it."""
    assert "TRANSLATE" in compile_silver()["customer"]


def test_a_better_recipe_restates_the_entity_and_frees_its_quarantined_rows() -> None:
    """The recipe is *in* the IR, so ``plan()`` sees a version bump as an
    ordinary quality-rule change (D11) — no step wiring to diff, no registry to
    consult.

    Replay matters more than backfill here and is the part a "just re-run it"
    reading would miss: rows the old recipe could not fix are sitting in the
    reject table, and the new one may be able to. The kind is not one whose
    params define an ordered interval or a membership set, so the question is
    undecidable and D52's conservative direction applies — replay.
    """
    project = load_project({"entity_model": ENTITY_MODEL, "mapping": MAPPING})
    old = build_project_ir(project, steps=registry())
    wider = StepRegistry(
        {("strip_invisible", 1): manifest()},
        macro_bodies={("strip_invisible", 1): f"TRANSLATE(:value, '{ZWSP}{REPLACEMENT}', '')"},
    )
    new = build_project_ir(project, steps=wider)
    result = plan(old, new)
    classes = {change.change_class for change in result.changes}
    assert classes == {ChangeClass.RESTATING}
    assert "customer" in result.replay_scope.entities


# ....................... #
# The declarations refused


def test_a_repair_block_without_the_disposition_is_refused() -> None:
    broken = MAPPING.replace("on_fail: repair", "on_fail: flag")
    with pytest.raises(SpecParseError, match="one declaration"):
        load_project({"entity_model": ENTITY_MODEL, "mapping": broken})


def test_the_disposition_without_a_recipe_is_refused() -> None:
    broken = MAPPING.replace(
        "        repair: {via: strip_invisible@1, fallback: quarantine}\n", ""
    )
    with pytest.raises(SpecParseError, match="one declaration"):
        load_project({"entity_model": ENTITY_MODEL, "mapping": broken})


def test_a_recipe_taking_more_than_the_value_it_repairs_is_refused() -> None:
    """A repair rule hands the recipe one thing — the value that fired it.
    There is no ``from:`` map on a quality rule, and inventing one would make a
    rule a second mapping surface."""
    two_column = registry(
        body=f"TRANSLATE(:value, :other, '{ZWSP}')",
        accepts={"value": "string", "other": "string"},
    )
    with pytest.raises(StepError, match="accepts 2 column"):
        compile_silver(steps=two_column)


def test_two_repair_rules_on_one_column_are_refused() -> None:
    """Both rewrite the column in the same projection, so which value survives
    would depend on the order they happened to be written in — and the second
    recipe would be judging a value the first had already changed."""
    twice = MAPPING.replace(
        'unmapped: ["$._load_id", "$._ingested_at", "$._source_row_id"]',
        "      - rule: normalize\n"
        "        form: nfc\n"
        "        on_fail: repair\n"
        "        repair: {via: strip_invisible@1, fallback: flag}\n"
        'unmapped: ["$._load_id", "$._ingested_at", "$._source_row_id"]',
    )
    with pytest.raises(StepError, match="two repair rules"):
        compile_silver(twice)


def test_a_repair_on_a_column_the_dedupe_order_reads_is_refused() -> None:
    """Dedupe runs *before* the field rules (D7), so the winner would be chosen
    on the value as delivered and then have that value rewritten underneath it
    — the same reason D6 forces ``coercible`` to ``fail`` on these columns."""
    model = ENTITY_MODEL.replace(
        "    quarantine: {retention: 90d}\n",
        "    quarantine: {retention: 90d}\n"
        "    dedupe: {keep: latest_by, field: name, tie_break: [customer_id]}\n",
    )
    project = load_project({"entity_model": model, "mapping": MAPPING})
    with pytest.raises(StepError, match="read by the dedupe order"):
        compile_project(project, target=Target.SQLMESH, dialect="duckdb", steps=registry())


@pytest.mark.parametrize("kind", ["coercible", "unique"])
def test_a_rule_with_no_repairable_value_refuses_the_disposition(kind: str) -> None:
    """``coercible`` fires *because* the projection is already NULL, so the
    recipe would be handed the NULL rather than the text that failed to cast;
    ``unique`` is a property of a population, and no rewrite of one row makes a
    duplicate unique. Fixing a value before it is coerced is a Tier 1 macro in
    the mapping, which the message says."""
    broken = MAPPING.replace(
        "      - rule: charset\n        forbid: [U+200B, U+FFFD]\n",
        f"      - rule: {kind}\n",
    )
    with pytest.raises(SpecParseError, match="no repairable value"):
        load_project({"entity_model": ENTITY_MODEL, "mapping": broken})


def test_a_row_rule_refuses_the_disposition() -> None:
    """A row rule names no column, so there is nothing for a recipe to
    rewrite."""
    model = ENTITY_MODEL.replace(
        "    quarantine: {retention: 90d}\n",
        "    quarantine: {retention: 90d}\n"
        "    quality:\n"
        "      - rule: expression\n"
        "        name: named_row\n"
        '        expr: "name IS NOT NULL"\n'
        "        on_fail: repair\n"
        "        repair: {via: strip_invisible@1, fallback: flag}\n",
    )
    with pytest.raises(SpecParseError, match="no repairable value"):
        load_project({"entity_model": model, "mapping": MAPPING})
