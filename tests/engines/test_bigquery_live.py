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

What it cannot settle is values — an instant, a decimal's scale, whether a row
was in fact quarantined — because a dry run never produces one. That is the
execution lane's subject, in its own module and its own CI job.

Needs `BLOOMERY_BIGQUERY_{PROJECT,DATASET,TOKEN}`; the dry runs skip with a
stated reason without them, so this module asks nothing of the network on a
fork's pull request or in a sandbox with no credential. What it still checks
there is that every statement it *would* submit is bound and qualified — the
harness's own correctness, which is otherwise only exercised where the
credential is.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import pytest

from bloomery.emit import EmittedArtifact
from support.bigquery import (
    LiveDataset,
    as_written,
    dry_run,
    live_dataset,
    provisioned_tables,
    qualify,
)
from support.compiling import compile_fixture, extract_select, spec_fixture_names

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
