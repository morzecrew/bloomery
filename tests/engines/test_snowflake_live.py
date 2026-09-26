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

import hashlib
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from itertools import groupby

import pytest
import sqlglot
from engines.test_snowflake_surrogate import KNOWN_GAPS
from engines.test_postgres_text_rules import ROWS as TEXT_ROWS
from engines.test_trino import ENTITY, FIXTURE, ROWS, SOURCE_RELATION
from engines.test_zoneless_utc import INSTANT_DATE, ISO_TEXTS, SESSIONS, TOKYO
from sqlglot import exp
from sqlglot.expressions.core import Expression
from support.compiling import compile_fixture, extract_select, spec_fixture_names
from support.execution import replay_statements
from support.snowflake import (
    SqlApi,
    account,
    credentials_missing,
    execution_missing,
    scratch_database,
)
from support.type_conformance import (
    CASES,
    Case,
    assert_matches_known,
    canonical,
    measure,
    probe_sql,
    source_columns,
)

from bloomery.dialects import get_dialect
from bloomery.emit.lower import THIS_MODEL
from bloomery.errors import BloomeryError
from bloomery.ir import OnFail, QualityRuleIR
from bloomery.ir.lower import canon
from bloomery.quality import violation
from bloomery.resolve.build import _try_cast_shape
from bloomery.transforms import DEFAULT_REGISTRY
from bloomery.typing import IntType, LogicalType, StringType

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

#: The execution corpus's own seed tables, beside the probe: one row of
#: specimens the shared corpus has no column for, S-0052's ISO table, and the
#: text tier's five Unicode specimens.
_SPECIMEN = "specimen"
_ISO = "iso"
_NAMES = "names"

#: The namespaces the emitted silver models address.
_SCHEMAS = ("bronze", "silver")

#: 23:30 in Berlin on 2026-01-06 and 07:30 in Tokyo on 2026-01-07 are one
#: instant, and this is it — the pair S-0045 measured landing in two days.
UTC_INSTANT = datetime(2026, 1, 6, 22, 30)

#: Two readers and a hostile account. The third is the one only a live session
#: can pose: ``TIMESTAMP_TYPE_MAPPING`` is what makes Snowflake's bare
#: ``TIMESTAMP`` an alias for the type D-1 forbids.
_READERS = (
    {"TIMEZONE": SESSIONS[0]},
    {"TIMEZONE": SESSIONS[1]},
    {"TIMEZONE": SESSIONS[1], "TIMESTAMP_TYPE_MAPPING": "TIMESTAMP_LTZ"},
)

#: Snowflake's ``VARCHAR`` ceiling, which is also the length it reports for
#: every unbounded one.
_MAX_VARCHAR = 16777216


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


def _probe_columns() -> str:
    """One literal column per case, typed by the port."""
    return ", ".join(
        f"CAST('{literal.replace(chr(39), chr(39) * 2)}' AS {physical}) AS {column}"
        for column, physical, literal in source_columns(get_dialect(DIALECT))
    )


def _probe_cte() -> str:
    """The probe relation as a CTE — what a lane holding no relations can carry."""
    return f"WITH {_PROBE} AS (SELECT {_probe_columns()})"


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


# ....................... #
# The execution corpus (S-0013/local-execution): the handful of questions a plan
# cannot settle
#
# Everything above compiles and nothing above runs, which is why every rung so
# far can be green over a mapping that means something else. These tests scan
# tiny seeded tables and compare *values* — and types, against the same
# register the three shipped ports answer to.
#
# A separate job from the compile lane and gated on a separate variable: a
# statement that scans needs a warehouse, an `EXPLAIN` does not, and keeping
# the two apart is what stops the default cloud lane being able to bill.
# Everything created lives in a transient database named for the run and is
# dropped with it.


@pytest.fixture(scope="module")
def warehouse() -> Iterator[SqlApi]:
    """An account with somewhere to put relations, holding the seed tables.

    Tables rather than literals or a CTE: a constant subquery is folded at plan
    time on at least one engine this project ships for, and a guarded cast
    probed over a folded constant is not the one a row meets (S-0033/D-84).
    """
    reason = execution_missing()
    if reason:
        pytest.skip(reason)
    with scratch_database(account(), schemas=_SCHEMAS) as client:
        for statement in _seed_statements():
            client.rows(statement)
        yield client


def _seed_statements() -> tuple[str, ...]:
    """Every statement the seed is built from, in order.

    A function rather than a fixture body so that
    :func:`test_the_lanes_own_seed_is_snowflake_syntax` can read them without an
    account: this is the hand-written SQL in a lane whose every other statement
    is rendered by the port, and it is therefore the only SQL here that no
    parser has looked at.
    """
    tokyo_local, _tokyo_zone = TOKYO
    return (
        f"CREATE TABLE {_PROBE} AS SELECT {_probe_columns()}",
        f"CREATE TABLE {_SPECIMEN} (tokyo_ts TIMESTAMP_NTZ, amount NUMBER(38, 0), "
        "bad_int VARCHAR, not_a_sku VARCHAR, missing VARCHAR)",
        f"INSERT INTO {_SPECIMEN} VALUES "
        f"('{tokyo_local}', 42, 'abc', 'nope', CAST(NULL AS VARCHAR))",
        f"CREATE TABLE {_ISO} (ord NUMBER(38, 0), spelling VARCHAR)",
        f"INSERT INTO {_ISO} SELECT * FROM (VALUES "
        + ", ".join(
            f"({index}, {_literal(text)})" for index, (text, _expected) in enumerate(ISO_TEXTS)
        )
        + ") AS t(ord, spelling)",
        f"CREATE TABLE {_NAMES} (ord NUMBER(38, 0), name VARCHAR)",
        f"INSERT INTO {_NAMES} SELECT * FROM (VALUES "
        + ", ".join(f"({index}, {_literal(row[0])})" for index, row in enumerate(TEXT_ROWS))
        + ") AS t(ord, name)",
    )


def _literal(value: str | None) -> str:
    """A Snowflake string literal, every non-ASCII character spelled ``CHAR(n)``.

    Escapes, never the characters: a specimen that looks identical to its
    control in a diff cannot be reviewed — the Trino tier's rule for its
    ``U&'…'`` literals, in the spelling Snowflake has.
    """
    if value is None:
        return "CAST(NULL AS VARCHAR)"
    quote = chr(39)
    return " || ".join(
        f"{quote}{''.join(run).replace(quote, quote * 2)}{quote}"
        if is_ascii
        else " || ".join(f"CHAR({ord(character)})" for character in run)
        for is_ascii, run in ((key, list(group)) for key, group in groupby(value, str.isascii))
    )


def _case(case_id: str) -> Case:
    """One case of the shared corpus, by name — the value and the expected type
    both come from there rather than from a second table kept beside it."""
    return next(case for case in CASES if case.id == case_id)


def _cell(client: SqlApi, statement: str) -> object:
    rows = client.rows(statement)
    assert len(rows) == 1, f"{statement} returned {len(rows)} rows"
    return rows[0][0]


def _built(
    name: str, column: str, args: tuple[object, ...], source: LogicalType | None
) -> Expression:
    """One transform's AST over ``column``.

    ``source`` is the type entering the step, which a spec declaring ``types``
    is handed (S-0046/D-1) — the shared corpus carries it per case, and a probe
    over a column the corpus has no case for has to say it here.
    """
    spec = DEFAULT_REGISTRY[name]
    extra = {"input_type": source} if spec.types else {}
    return spec.builder(exp.column(column), *args, **extra)


def _transform_sql(
    name: str, column: str, *args: object, source: LogicalType | None = None
) -> str:
    """One transform over ``column``, rendered the way emit renders it: through
    the canonical text round trip (S-0020/D-2) and then through the port."""
    return get_dialect(DIALECT).render(canon(_built(name, column, args, source)).ast())


def _quality_sql(
    name: str, column: str, *args: object, source: LogicalType | None = None
) -> str:
    """The same, shaped as a quality-carrying entity's lowering shapes it: every
    cast in the chain becomes a ``TRY_CAST`` (S-0033/D-3), which is the only
    place this port's ``TRY_CAST`` rewrite is reachable from."""
    shaped = _try_cast_shape(_built(name, column, args, source))
    return get_dialect(DIALECT).render(canon(shaped).ast())


def _text_rule(kind: str, params: tuple[tuple[str, str], ...]) -> QualityRuleIR:
    return QualityRuleIR(
        name=f"name_{kind}", kind=kind, column="name", on_fail=OnFail.FLAG, params=params
    )


# ....................... #
# The lane can run at all


def test_the_lanes_own_seed_is_snowflake_syntax() -> None:
    """The seed statements parse as Snowflake — checked without an account.

    Every other statement this lane submits is rendered by the port and has
    already met a parser two rungs down. The seed has not: it is hand-written,
    it is assembled out of ``VALUES`` lists and ``CHAR(n)`` literals, and an
    account is the most expensive place to discover a missing bracket. So the
    one check that needs no credential runs everywhere, and a typo fails the
    acceptance command rather than the first scheduled live run.
    """
    for statement in (*_seed_statements(), *_bronze_statements()):
        sqlglot.parse_one(statement, read=DIALECT)


def test_the_account_executes_and_canonicalizes_a_row(warehouse: SqlApi) -> None:
    """Warehouse, database and the row coming back typed — asserted on its own
    so a warehouse that will not resume reads as a warehouse that will not
    resume rather than as a corpus of findings."""
    assert warehouse.rows(f"SELECT COUNT(*) FROM {_SPECIMEN}") == ((1,),)


# ....................... #
# The declared-versus-produced type register, on the fourth port


def test_declared_types_are_what_snowflake_produces(warehouse: SqlApi) -> None:
    """The battery the three shipped ports answer to (S-0045/D-5), here.

    A view rather than the result-set metadata, because the SQL API names a
    column's type by *family* — ``FIXED`` covers every scale — and a
    ``NUMBER(12, 4)`` that came back ``NUMBER(38, 0)`` is exactly the finding
    this register exists to hold.
    """
    port = get_dialect(DIALECT)

    def run(sql: str) -> str:
        created = warehouse.submit(f"CREATE OR REPLACE VIEW {_PROBE}_view AS {sql}")
        if not created.accepted:
            return f"error:{created.code}"
        described = warehouse.rows(f"DESCRIBE VIEW {_PROBE}_view")
        return _produced(str(described[0][1]))

    assert_matches_known(measure(port, run, relation=_PROBE), port=DIALECT)


def _produced(spelling: str) -> str:
    """Snowflake's type for the probe column, made comparable with the port's.

    The maximum ``VARCHAR`` length is dropped for the reason
    :func:`~support.type_conformance.canonical` drops timestamp precision:
    bloomery's ``string`` declares no length, so the engine's ceiling is its
    spelling of *unbounded* and not a claim a port could be wrong about. A
    narrower one survives, because that one would be.
    """
    return canonical(spelling.replace(f"VARCHAR({_MAX_VARCHAR})", "VARCHAR"), dialect=DIALECT)


# ....................... #
# Timezone normalization (S-0013/D-1)


def test_to_utc_is_one_instant_whoever_reads_it(warehouse: SqlApi) -> None:
    """The invariant the port's whole timestamp mapping exists for: one instant,
    one value, one date, under any session zone — and under an account that has
    pointed the bare ``TIMESTAMP`` alias at ``TIMESTAMP_LTZ``.

    The third reader is not decoration. ``TIMESTAMP`` is an *alias* on
    Snowflake, resolved through ``TIMESTAMP_TYPE_MAPPING``, so an account may
    turn every unqualified timestamp into the one type D-1 forbids without a
    line of bloomery changing — which is why the port spells the type
    explicitly, and why only a session that sets the parameter can show that
    spelling working.
    """
    berlin = probe_sql(_case("to_utc-timestamp"), get_dialect(DIALECT), relation=_PROBE)
    _tokyo_local, tokyo_zone = TOKYO
    tokyo = _transform_sql("to_utc", "tokyo_ts", tokyo_zone)

    seen = {}
    for reader in _READERS:
        answer = warehouse.submit(
            f"SELECT ({berlin}) AS berlin, ({tokyo}) AS tokyo, "
            f"CAST(({berlin}) AS DATE) AS berlin_day, CAST(({tokyo}) AS DATE) AS tokyo_day "
            f"FROM {_PROBE}, {_SPECIMEN}",
            parameters=reader,
        )
        assert answer.accepted, f"{reader}: {answer.code} {answer.message}"
        assert not any(type_ == "TIMESTAMP_LTZ" for _name, type_ in answer.columns), (
            f"{reader}: a timestamp came back as TIMESTAMP_LTZ — {answer.columns}"
        )
        seen[tuple(sorted(reader.items()))] = answer.rows[0]

    assert len(set(seen.values())) == 1, f"the instant moved with the reader: {seen}"
    berlin_ts, tokyo_ts, berlin_day, tokyo_day = next(iter(seen.values()))
    assert berlin_ts == tokyo_ts == UTC_INSTANT
    assert berlin_day == tokyo_day == date.fromisoformat(INSTANT_DATE)


# ....................... #
# ISO parsing (S-0044, S-0052)


def test_iso_parse_reads_every_form_the_table_names(warehouse: SqlApi) -> None:
    """S-0052's table, executed: ``parse_ts: ISO8601`` reads a local wall clock,
    keeps it, and answers NULL for the two forms that carry their own offset and
    are therefore out of contract.

    The same table the PostgreSQL and Trino tiers are held to, so a port that
    reads one of these forms differently presents as one row of one shared
    expectation rather than as a Snowflake-shaped footnote.
    """
    expression = _transform_sql("parse_ts", "spelling", "ISO8601")

    rows = warehouse.rows(f"SELECT spelling, ({expression}) FROM {_ISO} ORDER BY ord")

    assert rows == tuple(ISO_TEXTS)


def test_snowflakes_auto_format_takes_the_t_separated_form(warehouse: SqlApi) -> None:
    """The one question the port left open for this lane, measured.

    The port strips the ``T`` to the space-separated spelling because the two
    fail asymmetrically — a needless ``REPLACE`` costs nothing, an identity that
    turns out to be wrong NULLs good data into the reject table. ``AUTO``
    documents the ``T`` form, so this is the likely answer; red here is not a
    defect but the finding that the rewrite is load-bearing, and it belongs in
    the port's docstring rather than in a fix.
    """
    parsed = _cell(
        warehouse, f"SELECT TRY_CAST(spelling AS TIMESTAMP_NTZ) FROM {_ISO} WHERE ord = 0"
    )

    assert parsed == ISO_TEXTS[0][1]


# ....................... #
# Decimal division (S-0020/D-5)


def test_decimal_division_stays_decimal(warehouse: SqlApi) -> None:
    """``3.5 / 2`` is ``1.75`` exactly, in a fixed-point type.

    A float here is not a rounding inconvenience, it is the corruption S-0020
    bans outright — and the SQL API hands every value over as text, so a
    ``REAL`` would arrive looking perfectly reasonable.
    """
    case = _case("divide-decimal(12,4)")

    answer = warehouse.submit(probe_sql(case, get_dialect(DIALECT), relation=_PROBE))

    assert answer.accepted, f"{answer.code} {answer.message}"
    assert answer.rows == ((Decimal("1.75"),),)
    assert answer.columns[0][1] == "FIXED", f"division produced {answer.columns[0][1]}"


# ....................... #
# TRY_CAST (the rewrite `_string_try_cast` exists for)


def test_try_cast_nulls_what_it_cannot_coerce_rather_than_aborting(warehouse: SqlApi) -> None:
    """The whole quality system rests on this one behaviour: an uncastable cell
    becomes a NULL the ``coercible`` rule disposes of, never an error that ends
    the run.

    All three operands the rewrite was built for, because the rewrite is the
    only reason any of them work: a string that will not coerce, a source that
    is not a string at all — Snowflake's ``TRY_CAST`` takes a string operand
    only, and the generator quietly emits a plain ``CAST`` otherwise — and a
    NULL, which must stay a NULL by propagation rather than become one by
    failing.
    """
    answer = warehouse.submit(
        f"SELECT ({_quality_sql('to_int', 'bad_int', source=StringType())}) AS uncastable, "
        f"({_quality_sql('to_int', 'amount', source=IntType())}) AS not_a_string, "
        f"({_quality_sql('to_int', 'missing', source=StringType())}) AS absent "
        f"FROM {_SPECIMEN}"
    )

    assert answer.accepted, f"{answer.code} {answer.message}"
    assert answer.rows == ((None, 42, None),)


# ....................... #
# Regexp extraction (the capture group S-0045/D-5 restores)


def test_regex_extract_returns_the_group_and_not_the_match(warehouse: SqlApi) -> None:
    """``sku-([0-9]+)`` over ``sku-42`` is ``42``.

    The group is the assertion. Snowflake's ``REGEXP_SUBSTR`` takes its
    ``group_num`` sixth, after two positional arguments and a parameters
    string, and a port that lost the group in the canonical round trip returns
    the whole match — a value that looks like a value and is the wrong one.
    """
    hit = probe_sql(_case("regex_extract-string"), get_dialect(DIALECT), relation=_PROBE)
    miss = _transform_sql("regex_extract", "not_a_sku", "sku-([0-9]+)", 1)

    assert _cell(warehouse, hit) == "42"
    # `regex_extract` declares `nullifies`, which is the portable reading of a
    # non-match: DuckDB answers `''` and the other ports answer NULL.
    assert _cell(warehouse, f"SELECT ({miss}) FROM {_SPECIMEN}") is None


# ....................... #
# VARIANT extraction (S-0013/D-6 — the one type that left the base adapter)


def test_variant_extraction_reads_a_path_at_both_depths(warehouse: SqlApi) -> None:
    """``VARIANT`` was chosen over the base adapter's ``JSON`` because it is
    what Snowflake's own semi-structured functions take and return. Reading a
    path back out of a column declared that way is what makes that a mapping
    rather than a spelling.
    """
    port = get_dialect(DIALECT)

    deep = _cell(warehouse, probe_sql(_case("json_path-variant-deep"), port, relation=_PROBE))
    shallow = _cell(warehouse, probe_sql(_case("json_path-variant-shallow"), port, relation=_PROBE))

    assert deep == "x"
    assert shallow == {"b": "x"}


# ....................... #
# Unicode (S-0033/D-86, and the one capability this port does not declare)


def test_snowflake_still_has_no_normalization_function(warehouse: SqlApi) -> None:
    """The evidence under ``UNICODE_NORMALIZE`` being the one flag this port
    withholds.

    The refusal is what makes a ``normalize`` rule a compile error here instead
    of SQL that renders cleanly and dies on a function the engine never had.
    Red means Snowflake has grown one — a capability to declare, not a defect —
    and the flag can be restored.
    """
    answer = warehouse.submit(f"SELECT NORMALIZE(name, NFC) FROM {_NAMES}")

    assert not answer.accepted, "Snowflake now normalizes; the port may declare the capability"


def test_charset_deletes_rather_than_substitutes(warehouse: SqlApi) -> None:
    """``TRANSLATE(x, members, '')`` removing a character when ``to`` is shorter
    is the whole construction, and it carries no capability flag because all
    three shipped engines spell it identically — a claim this fourth port is
    the first thing to test.

    The same five specimens and the same verdicts the PostgreSQL and Trino
    tiers hold, including the null: NULL is neither a pass nor a violation, and
    a rule that fired on one would fire on every nullable column (D19).
    """
    forbid = _text_rule("charset", (("forbid_0000", "U+200B"),))
    allow = _text_rule("charset", (("allow_0000", "U+0020-U+007E"),))

    assert _verdicts(warehouse, forbid) == [row[2] for row in TEXT_ROWS]
    assert _verdicts(warehouse, allow) == [row[3] for row in TEXT_ROWS]


def _verdicts(client: SqlApi, rule: QualityRuleIR) -> list[object]:
    predicate = get_dialect(DIALECT).render(violation(rule))
    rows = client.rows(f"SELECT ord, ({predicate}) FROM {_NAMES} ORDER BY ord")
    return [fired for _ord, fired in rows]


# ....................... #
# Null behaviour


def test_a_null_stays_a_null_and_a_default_stays_a_default(warehouse: SqlApi) -> None:
    """NULL through the transforms that meet one, on the engine.

    ``coalesce`` is the only one that may answer something else, and it must —
    a port where the two behaved alike would either lose every default or
    swallow every missing value.
    """
    answer = warehouse.submit(
        f"SELECT ({_transform_sql('coalesce', 'missing', 'unknown', source=StringType())}) AS filled, "
        f"({_transform_sql('nullif', 'missing', 'sentinel', source=StringType())}) AS kept_null, "
        f"({_transform_sql('upper', 'missing')}) AS upper_null, "
        f"({_transform_sql('regex_extract', 'missing', 'sku-([0-9]+)', 1)}) AS no_match "
        f"FROM {_SPECIMEN}"
    )

    assert answer.accepted, f"{answer.code} {answer.message}"
    assert answer.rows == (("unknown", None, None, None),)


# ....................... #
# Quarantine row disposition — the one question that needs the emitted models
# themselves, materialized and read back


@pytest.fixture(scope="module")
def quarantined(warehouse: SqlApi) -> SqlApi:
    """The quality-carrying fixture's silver models, built over a seeded bronze
    table — the same four rows the PostgreSQL and Trino tiers seed, so a
    disagreement between the three engines is legible as a diff rather than as
    two unrelated corpora.
    """
    for statement in _bronze_statements():
        warehouse.rows(statement)
    artifacts = {
        artifact.path: artifact for artifact in compile_fixture(FIXTURE, dialect=DIALECT)
    }
    # The entity before its reject table: both read the same staged extract, and
    # ordering keeps a failure legible.
    for name in (ENTITY, f"{ENTITY}__reject"):
        body = extract_select(artifacts[f"models/silver/{name}.sql"].content)
        warehouse.rows(f"CREATE TABLE silver.{name} AS {body}")
    return warehouse


def test_the_right_rows_are_kept_and_diverted(quarantined: SqlApi) -> None:
    """One clean row survives; each specimen diverts on the rule that names its
    failure, and every bronze row is accounted for on one side or the other —
    S-0033's conservation law, on the fourth engine.

    ``_quality_flags`` is asserted beside them because its Snowflake spelling is
    the one every silver model carries and the one the emulator could not take:
    an empty ``ARRAY_CONSTRUCT()`` cast to the untyped ``ARRAY``. The contract
    is that it is never NULL (D23), which is a value question and so a question
    for this rung.
    """
    kept = quarantined.rows(
        f"SELECT _source_row_id, _quality_flags FROM silver.{ENTITY} ORDER BY _source_row_id"
    )
    diverted = dict(
        (row_id, rules)
        for row_id, rules in quarantined.rows(
            f"SELECT _source_row_id, failed_rules FROM silver.{ENTITY}__reject"
        )
    )

    assert [row_id for row_id, _flags in kept] == ["r1"]
    assert kept[0][1] == [], f"_quality_flags on a clean row is {kept[0][1]!r}, not an empty array"
    assert "stock_date_coercible" in diverted["r2"]
    assert "stock_level_coercible" in diverted["r3"]
    assert "stock_level_not_negative" in diverted["r5"]
    assert len(kept) + len(diverted) == len(ROWS)


def test_the_reject_id_agrees_with_the_python_encoder(quarantined: SqlApi) -> None:
    """``SHA2(msg, 256)`` returns the lowercase hex digest directly, which is
    ``reject_id``'s contract — so this port inherits none of Trino's
    ``TO_UTF8``/``TO_HEX``/``LOWER`` wrapping (S-0013/D-2).

    That claim is only checkable against a *value*, and against one computed
    somewhere else: the canon-bytes digest built here in Python, rather than
    Snowflake agreeing with itself. Cross-engine agreement is the property
    ``reject_id`` needs — a replay run on one engine has to find the row
    another quarantined.
    """
    rows = quarantined.rows(
        f"SELECT _source_row_id, reject_id FROM silver.{ENTITY}__reject ORDER BY _source_row_id"
    )

    assert rows == tuple(
        (
            row_id,
            hashlib.sha256(_canon_bytes(SOURCE_RELATION) + _canon_bytes(str(row_id))).hexdigest(),
        )
        for row_id, _digest in rows
    )


def _bronze_statements() -> tuple[str, ...]:
    """The bronze table the emitted silver models read, and its four rows."""
    values = ", ".join("(" + ", ".join(_literal(field) for field in row) + ")" for row in ROWS)
    return (
        f"CREATE TABLE bronze.{SOURCE_RELATION} (warehouse VARCHAR, day VARCHAR, "
        "on_hand VARCHAR, sku VARCHAR, _load_id VARCHAR, _ingested_at VARCHAR, "
        "_source_row_id VARCHAR)",
        f"INSERT INTO bronze.{SOURCE_RELATION} VALUES {values}",
    )


def _canon_bytes(value: str) -> bytes:
    """The reject-table encoding, in Python: ``S<character length>:<value>`` —
    character length rather than utf-8 byte length, the deviation
    :mod:`bloomery.quality.reject` records because no byte-length function is
    portable across the shipped dialects."""
    return f"S{len(value)}:{value}".encode()
