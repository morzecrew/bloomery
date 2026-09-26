"""Rung 5 on BigQuery (S-0012/the-ladder): the authoritative compile lane.

A dry run is the engine's own parser, binder and type resolution answering for
a statement that is never executed and never scanned — the cheapest
authoritative layer any of the four cloud ports has, and the only rung where
something other than SQLGlot has an opinion about the port's output. Rungs 1
through 4 between them never ask BigQuery anything.

It runs the shared fixture corpus rather than a port-native one (S-0012/D-6),
and every `.sql` artifact of each fixture rather than the models alone: an
audit and a replay are SQL bloomery emits, and a dry run over them costs the
same round trip.

What a dry run cannot settle is values — an instant, a decimal's scale, whether
a row was in fact quarantined — because it never produces one. That is the
**execution lane** in the second half of this module: the same shared corpus,
run rather than parsed, over inline literal tables under an explicit byte limit.
It is a separate *job*, selected by a variable of its own
(`BLOOMERY_BIGQUERY_EXECUTE`) rather than by a separate module, so the default
cloud lane cannot execute or bill anything by accident (S-0014/ci-identity).

Needs `BLOOMERY_BIGQUERY_{PROJECT,DATASET,TOKEN}`, and the execution lane its
switch as well; both skip with a stated reason naming what is unset, so this
module asks nothing of the network on a fork's pull request or in a sandbox with
no credential. What it still checks there is that every statement it *would*
submit is bound — the macro binding for the dry runs, the inline prelude for the
execution lane — which is the harness's own correctness, otherwise exercised
only where the credential is.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import PurePosixPath

import pytest
import sqlglot
from sqlglot import exp

from bloomery.dialects import get_dialect
from bloomery.emit import ArtifactKind, EmittedArtifact
from bloomery.ir.lower import canon as lower_canon
from bloomery.transforms import DEFAULT_REGISTRY
from support.bigquery import (
    LiveDataset,
    as_written,
    dry_run,
    execute,
    executing_dataset,
    inlined,
    literal_table,
    live_dataset,
    provisioned_tables,
    qualify,
)
from support.compiling import compile_fixture, extract_select, spec_fixture_names
from support.dirty import (
    DIALECT_DIVERGENT,
    FIXTURE as DIRTY_FIXTURE,
    FLAGGED,
    KEPT,
    QUARANTINED,
    cases,
    corpus,
    expected,
)

pytestmark = pytest.mark.engine("bigquery")

#: Fixtures that exist to be refused, and never reach a dialect at all: a
#: `convert` with no rate relation (S-0040/D-4), a fan-out trap, a mart over an
#: SCD2 entity. Named rather than caught, because `except: continue` around a
#: corpus sweep turns a resolver regression into a smaller sweep that still
#: passes.
REFUSED_BY_DESIGN = frozenset({"currency_convert_refusal", "fanout_trap", "scd2_mart_refusal"})

CORPUS = tuple(name for name in spec_fixture_names() if name not in REFUSED_BY_DESIGN)


@pytest.fixture(scope="module")
def dataset() -> LiveDataset:
    return live_dataset()


@pytest.fixture(scope="module")
def provisioned(dataset: LiveDataset) -> frozenset[str]:
    return provisioned_tables(dataset)


#: SQLMesh's macro for the relation an audit is attached to, which the engine
#: substitutes with the audited model's table. `extract_select` expands
#: `@execution_ds` and not this one, and it sits in a FROM or JOIN position — so
#: left alone it reaches BigQuery's parser as a table name, and the refusal
#: would be reported as a port failure that is the harness's leak. Every other
#: engine lane binds it the same way (tests/engines/test_trino.py:311,
#: tests/engines/test_merged_cleaning_engines.py:352);
#: this lane binds it to the *declared* relation rather than a stand-in, because
#: a dry run resolves names and types and a stand-in resolves neither.
THIS_MODEL = "@this_model"

#: The envelope that declares an audit, in the two spellings bloomery emits: a
#: SQLMesh `MODEL (...)` header, and the `@model(...)` decorator of the Python
#: wrapper a step-backed model gets.
_SQL_RELATION = re.compile(r"^  name (\S+),$", re.M)
_SQL_AUDITS = re.compile(r"^  audits \(([^)]*)\)", re.M)
_PY_RELATION = re.compile(r"@model\(\s*'([^']+)'")
_PY_AUDITS = re.compile(r"audits=\[([^\]]*)\]")
_AUDIT_NAME = re.compile(r"\w+")


def audited_relations(artifacts: Sequence[EmittedArtifact]) -> dict[str, str]:
    """Audit name → the relation its `@this_model` stands for.

    Read from the emitted envelopes rather than from the fixture spec: what the
    engine would substitute is what the model it is attached to declares, and
    the audit artifact itself names only the audit.
    """
    bound: dict[str, str] = {}
    for artifact in artifacts:
        if artifact.path.endswith(".sql"):
            # The envelope ends at its closing `);` and contains no other one.
            envelope = artifact.content.partition(");")[0]
            relation = _SQL_RELATION.search(envelope)
            audits = _SQL_AUDITS.search(envelope)
        else:
            relation = _PY_RELATION.search(artifact.content)
            audits = _PY_AUDITS.search(artifact.content)
        if not (relation and audits):
            continue
        for name in _AUDIT_NAME.findall(audits.group(1)):
            bound[name] = relation.group(1)
    return bound


def statements(fixture: str) -> list[tuple[str, str]]:
    """The fixture's SQL, each statement bound and ready to submit.

    `config.yaml` carries no statement and a step-backed model is a `.py`, whose
    body is Python the engine never sees — but its wrapper is where such a
    model's audits are declared, so the binding is read from every artifact and
    only the `.sql` ones are submitted.
    """
    artifacts = compile_fixture(fixture, dialect="bigquery")
    audited = audited_relations(artifacts)

    submitted: list[tuple[str, str]] = []
    for artifact in artifacts:
        if not artifact.path.endswith(".sql"):
            continue
        sql = extract_select(artifact.content)
        if THIS_MODEL in sql:
            audit = artifact.path.removeprefix("audits/").removesuffix(".sql")
            # Asserted rather than skipped: an audit no emitted model claims is
            # a finding in the emitter, and dropping it here would hide it
            # behind a lane that still passes.
            assert audit in audited, (
                f"{fixture}/{artifact.path}: no emitted model declares audit {audit!r}, "
                f"so {THIS_MODEL} has no relation to bind to"
            )
            sql = sql.replace(THIS_MODEL, as_written(audited[audit]))
        submitted.append((artifact.path, sql))
    return submitted


@pytest.mark.parametrize("fixture", CORPUS)
def test_every_statement_is_bound_before_it_is_submitted(fixture: str) -> None:
    """The macro binding, asserted without a credential.

    `qualify` refuses an unexpanded macro, but only where the dataset is
    configured — so leakage would be invisible in every run that skips, and the
    run that does not skip would report BigQuery's refusal against the port. A
    fabricated dataset exercises the rewrite and its guard offline: `qualify` is
    pure text and the token is never used.
    """
    offline = LiveDataset(project="p", dataset="d", token="")
    for _path, statement in statements(fixture):
        qualify(statement, offline)


def test_the_dataset_resolves_something(dataset: LiveDataset, provisioned: frozenset[str]) -> None:
    """The dedicated dataset exists before the lane does (S-0014/D-5).

    Without this the lane is green over an empty dataset: every fixture skips
    for want of its relations, the run reports no failure, and a report reads
    an authoritative rung that asked the engine nothing.
    """
    assert provisioned, (
        f"{dataset} holds no tables: a dry run over a query that resolves no name checks "
        f"syntax and roughly what rung 3 checks for free. Provision the dataset first — "
        f"the relations each fixture wants are named in its skip message."
    )


@pytest.mark.parametrize("fixture", CORPUS)
def test_the_engine_accepts_every_statement(
    fixture: str, dataset: LiveDataset, provisioned: frozenset[str]
) -> None:
    """Every emitted statement parses, binds and type-checks on BigQuery."""
    checked = 0
    missing: set[str] = set()

    for path, statement in statements(fixture):
        sql, relations = qualify(statement, dataset)
        absent = relations - provisioned
        if absent:
            missing |= absent
            continue
        # A `DryRunRejected` here is the finding: it carries BigQuery's own
        # diagnostic, with the line and column of what the port rendered.
        result = dry_run(dataset, sql)
        assert result.get("schema", {}).get("fields"), (
            f"{fixture}/{path}: the dry run returned no output schema, so nothing "
            f"was type-resolved"
        )
        checked += 1

    if not checked:
        pytest.skip(f"{fixture}: {dataset} has none of {sorted(missing)}")


# ....................... #
# The execution lane

#: The shared corpus's spec project, and the three of its eleven mappings this
#: lane runs. Between them they carry every value question a dry run cannot
#: answer: `numerics.csv` the declared decimal's scale, `SAFE_CAST`'s NULL and
#: the NULL that is not a coercion failure; `dates.csv` the exact instant a
#: parsed wall clock lands on; `unicode.csv` NFC normalization, a `charset`
#: denylist, a regexp predicate and the corpus's one quarantined row. The other
#: eight are the dry-run lane's business, where they cost a parse rather than a
#: job.
DIRTY_SEEDS = {
    "unicode.csv": "bronze.dirty__unicode",
    "numerics.csv": "bronze.dirty__numerics",
    "dates.csv": "bronze.dirty__dates",
}
DIRTY_ENTITIES = {
    "unicode.csv": "dirty_name",
    "numerics.csv": "dirty_number",
    "dates.csv": "dirty_date",
}


def dirty_sources() -> dict[str, str]:
    """``namespace.relation`` → the SELECT that stands for it, for :func:`inlined`.

    The bronze relations are the corpus files themselves as literal rows; the
    silver ones are the emitted model bodies, unedited. A mapping this lane does
    not seed still contributes its models and is dropped by :func:`inlined`,
    which is what keeps this list to the three files rather than to the graph.
    """
    sources = {
        relation: literal_table(corpus(name)) for name, relation in DIRTY_SEEDS.items()
    }
    for artifact in compile_fixture(DIRTY_FIXTURE, dialect="bigquery"):
        if artifact.kind is not ArtifactKind.MODEL or not artifact.path.endswith(".sql"):
            continue
        path = PurePosixPath(artifact.path)
        sources[f"{path.parent.name}.{path.stem}"] = extract_select(artifact.content)
    return sources


def dispositions(
    run: Callable[[str], list[tuple[object, ...]]], entity: str
) -> dict[str, tuple[str, tuple[str, ...]]]:
    """``{_source_row_id: (disposition, fired rule names)}`` — BigQuery's answer
    in the vocabulary :func:`support.dirty.dispositions` reads off DuckDB.

    **Both sides of the split**, for the reason that function gives: a lane that
    read only the entity cannot tell correctly quarantined from silently
    dropped, and a row in neither table shows up as an identity missing from
    this mapping rather than as a label.
    """
    landed: dict[str, tuple[str, tuple[str, ...]]] = {}
    for row_id, flags in run(f"SELECT _source_row_id, _quality_flags FROM silver.{entity}"):
        rules = tuple(str(rule) for rule in flags or ())
        landed[str(row_id)] = (FLAGGED if rules else KEPT, rules)
    for row_id, rules in run(
        f"SELECT _source_row_id, failed_rules FROM silver.{entity}__reject "
        f"WHERE resolved_at IS NULL"
    ):
        landed[str(row_id)] = (QUARANTINED, tuple(str(rule) for rule in rules or ()))
    return landed


def canon(value: str) -> bytes:
    """The reject-table encoding, in Python: ``S<character length>:<value>``.

    Character length rather than utf-8 byte length — the deviation
    :mod:`bloomery.quality.reject` records, because no byte-length function is
    portable across the shipped dialects. Spelled the way
    `tests/engines/test_trino.py:66` spells it, so the two engines are compared
    against one encoder rather than against each other.
    """
    return f"S{len(value)}:{value}".encode()


@pytest.fixture(scope="module")
def executing() -> LiveDataset:
    return executing_dataset()


@pytest.fixture(scope="module")
def corpus_run(executing: LiveDataset) -> Callable[[str], list[tuple[object, ...]]]:
    """Query the dirty corpus's own models over the dirty corpus's own rows."""
    sources = dirty_sources()

    def run(sql: str) -> list[tuple[object, ...]]:
        return execute(executing, inlined(sql, sources))

    return run


@pytest.fixture(scope="module")
def landed(
    corpus_run: Callable[[str], list[tuple[object, ...]]],
) -> dict[str, dict[str, tuple[str, tuple[str, ...]]]]:
    """``{corpus file: {_source_row_id: (disposition, rules)}}``, read once.

    Module-scoped because it is six jobs, and every case below is an assertion
    about the same six answers.
    """
    return {name: dispositions(corpus_run, DIRTY_ENTITIES[name]) for name in DIRTY_SEEDS}


def test_the_corpus_inlines_without_a_credential() -> None:
    """The prelude, asserted offline, on the argument
    :func:`test_every_statement_is_bound_before_it_is_submitted` makes about the
    macro binding: every run without a credential skips the lane, so a rewrite
    that silently stopped binding would be invisible until the one run that does
    not skip, and would report BigQuery refusing a relation the port never
    wrote. :func:`inlined` is pure text and no token is used here.
    """
    sources = dirty_sources()
    for entity in DIRTY_ENTITIES.values():
        for relation in (entity, f"{entity}__reject"):
            statement = inlined(f"SELECT * FROM silver.{relation}", sources)
            remaining = [
                f"{table.db}.{table.name}"
                for table in sqlglot.parse_one(statement, read="bigquery").find_all(exp.Table)
                if table.db
            ]
            assert not remaining, f"silver.{relation} still reads {sorted(set(remaining))}"


@pytest.mark.parametrize("name", sorted(DIRTY_SEEDS))
def test_every_corpus_row_lands_on_the_side_the_corpus_says(
    landed: dict[str, dict[str, tuple[str, tuple[str, ...]]]], name: str
) -> None:
    """The corpus's own ``_expected`` column, answered by BigQuery rather than by
    DuckDB — which is the comparison S-0012/D-6 is for: a divergence presents as
    one file's one specimen, in a table the other engines' tiers already assert.

    A row absent from both the entity and its reject table is absent from
    ``observed`` and the comparison says which — the failure §6 of S-0033 says a
    survivors-only test cannot see.
    """
    case_of = cases(name)
    observed = {
        case_of[row_id]: disposition for row_id, (disposition, _rules) in landed[name].items()
    }
    declared = expected(name)
    # A `dialect_divergent` row's disposition is a property of the engine, not of
    # the data (`tests/support/dirty.py:79`), so the claim over it is
    # consistency: it landed somewhere, and which side is the matrix's to record.
    divergent = {case for case, want in declared.items() if want == DIALECT_DIVERGENT}
    assert {case: side for case, side in observed.items() if case not in divergent} == {
        case: want for case, want in declared.items() if case not in divergent
    }
    for case in sorted(divergent):
        assert observed.get(case) in {KEPT, FLAGGED, QUARANTINED}, (
            f"{name}: {case} is in neither silver.{DIRTY_ENTITIES[name]} nor its reject table"
        )


def test_the_quarantined_row_was_in_fact_quarantined(
    landed: dict[str, dict[str, tuple[str, tuple[str, ...]]]],
    corpus_run: Callable[[str], list[tuple[object, ...]]],
) -> None:
    """The claim a dry run cannot make at all, and the one the lane exists for.

    `unicode.csv`'s lone-surrogate escape is the file's single ``quarantine``
    specimen: it must be in the reject table, out of the entity, and counted
    once — §6's conservation law, which is the only assertion that can tell a
    quarantine from a row the engine dropped on the floor.
    """
    quarantined = {
        row_id for row_id, (side, _rules) in landed["unicode.csv"].items() if side == QUARANTINED
    }
    case_of = cases("unicode.csv")
    assert {case_of[row_id] for row_id in quarantined} == {"lone_surrogate_escape"}
    kept = corpus_run("SELECT COUNT(*) FROM silver.dirty_name")[0][0]
    assert kept + len(quarantined) == len(corpus("unicode.csv"))
    # A reject row records every failure it carries, flag-level ones included;
    # this specimen carries exactly one, the backslash its `pattern` rule
    # refuses. A row diverted by some *other* rule would be a different defect
    # wearing the same count.
    assert landed["unicode.csv"][next(iter(quarantined))][1] == ("name_pattern",)


def test_the_reject_id_agrees_with_the_python_encoder(
    corpus_run: Callable[[str], list[tuple[object, ...]]],
) -> None:
    """``reject_id``'s hex, checked against the canon-bytes digest computed here
    in Python rather than against BigQuery agreeing with itself.

    Cross-engine *agreement* is the property identity needs (S-0026/D-21): a
    replay run on one engine has to find the row another quarantined. The casing
    is half of it — ``TO_HEX`` differs from ``SHA256``'s hex by case alone on
    some engines, and a digest that disagrees in case only is a digest that
    disagrees.
    """
    rows = corpus_run(
        "SELECT _source_row_id, source_relation, reject_id FROM silver.dirty_number__reject "
        "ORDER BY _source_row_id"
    )
    assert rows, "the numerics corpus quarantines rows; a reject table with none is the finding"
    for row_id, relation, digest in rows:
        assert re.fullmatch(r"[0-9a-f]{64}", str(digest)), (
            f"{row_id}: {digest!r} is not lower-case hex, so this engine's reject ids cannot be "
            f"compared with any other's"
        )
        assert digest == hashlib.sha256(canon(str(relation)) + canon(str(row_id))).hexdigest()


def test_the_reject_payload_is_readable_back_as_json(
    corpus_run: Callable[[str], list[tuple[object, ...]]],
) -> None:
    """``raw`` is what replay re-runs the mapping against and ``key_values`` is
    what a human greps for, so a payload BigQuery writes and cannot read back
    makes the reject table a dead end rather than a recovery path. Both are JSON
    the port constructed, and reading them is the only check that it is JSON.
    """
    assert corpus_run(
        "SELECT JSON_EXTRACT_SCALAR(raw, '$.raw_amount'), "
        "JSON_EXTRACT_SCALAR(key_values, '$.case_name') "
        "FROM silver.dirty_number__reject WHERE _source_row_id = 'num_002'"
    ) == [("12,50", "comma_decimal")]


def test_the_declared_decimal_rounds_at_its_declared_scale(
    corpus_run: Callable[[str], list[tuple[object, ...]]],
) -> None:
    """``decimal(38, 9)``, executed — the one thing a dry run answers with a type
    name and nothing else.

    `scale_overflow_rounds` carries ten fractional digits: that does not fail the
    cast, it *rounds* (`tests/fixtures/dirty/numerics.csv:19`), so the value it
    comes back as is what pins the scale the port actually gave the column —
    which is the bound S-0014/D-7 is open on. `negative_zero` is the second
    half: the sign must not survive a coercion to zero (S-0020), and it survives
    in the value's text long after it stops mattering to ``=``.
    """
    rows = corpus_run(
        "SELECT case_name, amount, ARRAY_TO_STRING(_quality_flags, ',') FROM silver.dirty_number "
        "WHERE case_name IN ('clean_control', 'scale_overflow_rounds', 'negative_zero')"
    )
    values = {str(case): (amount, flags) for case, amount, flags in rows}
    assert values["clean_control"] == (Decimal("12.50"), "")
    assert values["scale_overflow_rounds"] == (Decimal("12.5"), "amount_text_pattern")
    assert str(values["negative_zero"][0]).lstrip("-") == str(values["negative_zero"][0])


def test_the_parsed_wall_clock_lands_on_the_exact_instant(
    corpus_run: Callable[[str], list[tuple[object, ...]]],
) -> None:
    """`utc_control` and `iso_control`, to the second.

    A `timestamp` is zoneless UTC (S-0021) and this port renders it as a
    BigQuery ``DATETIME`` rather than a ``TIMESTAMP`` (S-0014/D-1), so the value
    that comes back is a wall clock already in UTC: `utc_control`'s trailing
    ``Z`` names the zone the type is in and truncating it loses nothing
    (S-0052/D-4), which is a claim about a value and therefore only checkable
    here.
    """
    rows = corpus_run(
        "SELECT case_name, observed_at FROM silver.dirty_date "
        "WHERE case_name IN ('iso_control', 'utc_control')"
    )
    assert {str(case): instant for case, instant in rows} == {
        "iso_control": datetime(2025, 12, 31, 0, 0),
        "utc_control": datetime(2025, 12, 30, 21, 0),
    }


def test_a_rendered_regexp_capture_returns_its_group(executing: LiveDataset) -> None:
    """``regex_extract``, executed over two literals rather than over the corpus.

    No fixture declares the transform — `rg -n "regex_extract" tests/fixtures`
    finds nothing — so the shared corpus has no capture specimen to run, and a
    capture group is on the list of what this lane owes. The port's own
    rendering is executed instead, with the non-matching row beside the matching
    one: a capture that came back as the whole subject, or as an empty string
    where the pattern does not match, are the two ways this goes wrong quietly.
    """
    rendered = get_dialect("bigquery").render(
        lower_canon(
            DEFAULT_REGISTRY["regex_extract"].builder(exp.column("raw"), r"^ORD-([0-9]+)$", 1)
        ).ast()
    )
    assert execute(
        executing,
        f"SELECT raw, {rendered} FROM (SELECT 'ORD-42' AS raw UNION ALL SELECT 'nope') "
        f"ORDER BY raw",
    ) == [("ORD-42", "42"), ("nope", None)]
