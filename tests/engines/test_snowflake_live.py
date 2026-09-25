"""The authoritative compile lane for the Snowflake port: ``EXPLAIN USING JSON``
against a real account (S-0013/authoritative-layers).

**This is the oracle the surrogate lane is evidence for** (S-0012/D-1). What
answers here is Snowflake's own parser, binder and function resolution, so a
statement it accepts is a statement Snowflake compiles — a claim no emulator can
make. Marked ``engine("snowflake")`` for exactly that reason, where the
emulator lane is marked ``surrogate`` (S-0013/D-4).

**Compile-only, and structurally so.** Every submission is an ``EXPLAIN``,
which produces a plan without executing: nothing is scanned, nothing is created
and no warehouse is needed, so this lane cannot bill for query time. Execution
against a real account is phase 4's separate job, which is what keeps the
default cloud lane unable to reach a warehouse at all.

**What each sweep actually establishes**, because the two are not the same rung:

- the *corpus* sweep reaches Snowflake's parser. The account holds none of the
  corpus's relations — a compile lane creates nothing — so a statement past the
  parser is refused at the binder with ``002003`` (*object does not exist*).
  That refusal is the expected outcome; a refusal with any other code is a
  finding about bloomery's rendering and fails here.
- the *probe* sweep reaches the binder and function resolution too, by carrying
  its own typed columns in a CTE: one column per transform case, declared with
  the port's own ``physical_type``. So every function spelling and every type in
  the port's map is resolved by Snowflake, against a relation that needs no
  seeding.

Credentials come from the environment behind a GitHub Environment and never
from the repository, and the lane skips with a stated reason when they are
absent (S-0013/D-7).
"""

from __future__ import annotations

import pytest
from engines.test_snowflake_surrogate import KNOWN_GAPS
from support.compiling import compile_fixture, extract_select, spec_fixture_names
from support.execution import replay_statements
from support.snowflake import SqlApi, account, credentials_missing
from support.type_conformance import CASES, Case, probe_sql, source_columns

from bloomery.dialects import get_dialect
from bloomery.emit.lower import THIS_MODEL
from bloomery.errors import BloomeryError

pytestmark = pytest.mark.engine("snowflake")

DIALECT = "snowflake"

#: Snowflake's code for *object does not exist or not authorized* — the only
#: refusal this lane expects, because it creates nothing to be found. An
#: engine-stable code and never a message, so a reworded error does not read as
#: a behaviour change (the rule ``support.type_conformance.Divergence`` states).
OBJECT_MISSING = "002003"

#: What ``@this_model`` stands in for. The audits address the audited model
#: through SQLMesh's macro, which only the framework expands — and which
#: Snowflake would otherwise read as a stage reference. The relation it resolves
#: to does not matter to a lane that holds no relations; that it is a relation
#: does.
_AUDITED = "silver._this_model"

#: The probe relation, built out of literals in a CTE rather than seeded.
_PROBE = "probe"


@pytest.fixture(scope="module")
def snowflake() -> SqlApi:
    reason = credentials_missing()
    if reason:
        pytest.skip(reason)
    return account()


@pytest.fixture(scope="module")
def corpus() -> tuple[tuple[str, str, str], ...]:
    """``(fixture, artifact path, one statement)`` over the whole shared corpus.

    The shared fixtures rather than Snowflake-native ones (S-0012/D-6), and the
    fixtures the port refuses at compile are dropped by *compiling* them rather
    than by naming them: the refused set is pinned by name one lane over, in
    ``test_snowflake_surrogate.py``, and a second copy of it here could only
    drift.
    """
    rendered: list[tuple[str, str, str]] = []
    for name in spec_fixture_names():
        try:
            artifacts = compile_fixture(name, dialect=DIALECT)
        except BloomeryError:
            continue
        for artifact in artifacts:
            if not artifact.path.endswith(".sql"):
                continue
            # A replay artifact is several statements the caller runs as one
            # unit of work, and the SQL API takes one statement per submission.
            if artifact.path.startswith("replay/"):
                for statement in replay_statements(artifact):
                    rendered.append((name, artifact.path, statement))
                continue
            select = extract_select(artifact.content).replace(THIS_MODEL, _AUDITED)
            rendered.append((name, artifact.path, select))
    return tuple(rendered)


def _probe_cte() -> str:
    """The probe relation: one literal column per case, typed by the port."""
    columns = ", ".join(
        f"CAST('{literal.replace(chr(39), chr(39) * 2)}' AS {physical}) AS {column}"
        for column, physical, literal in source_columns(get_dialect(DIALECT))
    )
    return f"WITH {_PROBE} AS (SELECT {columns})"


# ....................... #
# The harness itself


def test_the_account_compiles_a_trivial_statement(snowflake: SqlApi) -> None:
    """Authentication, submission and the plan coming back — asserted on its own
    so a bad credential reads as a bad credential rather than as 128 findings
    about the corpus."""
    answer = snowflake.explain("SELECT 1 AS one")

    assert answer.accepted, f"{answer.code}: {answer.message}"
    assert answer.rows, "EXPLAIN returned no plan"


def test_a_statement_the_engine_cannot_compile_is_refused(snowflake: SqlApi) -> None:
    """The lane can fail. A compile lane whose refusals were never observed
    could not tell a clean corpus from an endpoint answering ``200`` to
    everything (S-0002/D-2, the same rule the gates carry)."""
    answer = snowflake.explain("SELECT NO_SUCH_FUNCTION(1)")

    assert not answer.accepted
    assert answer.code != OBJECT_MISSING, f"an unknown function read as {answer.code}"


# ....................... #
# The corpus: Snowflake's parser over every rendered statement


def test_every_rendered_statement_reaches_the_binder(
    snowflake: SqlApi, corpus: tuple[tuple[str, str, str], ...]
) -> None:
    """Every statement the corpus renders for Snowflake is compiled, and the
    only refusal allowed is the account not holding the relation.

    A refusal with any other code is what this lane exists to catch: a syntax
    error, an unknown function, an invalid type — bloomery rendering SQL
    Snowflake does not have, reported by Snowflake rather than by a surrogate.
    """
    findings = []
    compiled: list[str] = []
    for name, path, statement in corpus:
        answer = snowflake.explain(statement)
        if answer.accepted or answer.code == OBJECT_MISSING:
            compiled.append(f"{name}/{path}")
            continue
        findings.append(f"{name}/{path}: {answer.code} {answer.message}")

    listed = "\n".join(findings)
    assert not findings, f"Snowflake refused {len(findings)} statement(s):\n{listed}"
    # The corpus is built by compiling, and `corpus` drops whatever the port
    # refuses — so a port-wide compile regression empties it and leaves nothing
    # for the loop above to submit. Without this the oracle reports success
    # having asked Snowflake nothing, which is the one answer it may never give
    # (the sibling surrogate lane guards the same hole with `assert planned`).
    assert compiled, "no statement reached Snowflake; the corpus rendered nothing"


# ....................... #
# The probes: function resolution and the type map, over typed columns


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_every_transform_compiles_over_a_column_of_its_declared_type(
    snowflake: SqlApi, case: Case
) -> None:
    """Each transform, rendered by the port over a column of the type it accepts,
    is compiled by Snowflake.

    Parametrized rather than swept, because this is the sweep whose failures are
    per-case findings — ``TO_UTF8`` copied from the Trino port, a ``NUMBER``
    bound Snowflake will not take, a format string its ``TO_TIMESTAMP`` spells
    differently (S-0013/D-2, D-6). One test per case names which.
    """
    port = get_dialect(DIALECT)
    statement = f"{_probe_cte()} {probe_sql(case, port, relation=_PROBE)}"

    answer = snowflake.explain(statement)

    assert answer.accepted, f"{answer.code} {answer.message}\n{statement}"


def test_the_surrogates_gaps_are_the_surrogates_and_not_the_ports(snowflake: SqlApi) -> None:
    """Every construct the pinned emulator cannot take is compiled by Snowflake.

    This is the whole reason a lane over the real account is the oracle: the
    emulator's refusals are only evidence of *something*, and which something is
    what this test settles. Red here means one of those constructs is not
    Snowflake's after all — a finding about the port, not about the emulator —
    and it is also the count S-0013/D-5 asks whoever runs both lanes to keep.
    """
    for description, statement in KNOWN_GAPS.items():
        answer = snowflake.explain(statement)

        assert answer.accepted, f"Snowflake refuses {description}: {answer.code} {answer.message}"
