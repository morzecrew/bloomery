"""Engine tier (S-0026/tier-contracts tier 5): the **real** Databricks SQL
warehouse, asked whether the generated SQL is acceptable (S-0016).

Two lanes in one module, kept apart by name so CI can run them as separate jobs
(S-0016/D-10 — the cheap one cannot accidentally scan or bill):

``test_compile_*`` — the authoritative lane. ``EXPLAIN EXTENDED`` over every
model the shared fixture corpus emits, which is the real analyzer saying the
statement is accepted, and ``DESCRIBE QUERY`` over the same statement, which is
the real analyzer saying what types the result carries — checked against the
types the compiler declared for the entity's fields. ``DESCRIBE QUERY`` is part
of this lane rather than an optional extra (S-0016/D-4): it is the one rung
where the declared-versus-produced contract meets Databricks' own analyzer, and
the surrogate is precisely where Spark and Databricks SQL are documented to
differ. Neither statement executes anything or scans any data.

``test_runtime_*`` — a deliberately small corpus over tiny tables, for the five
things no compile can settle: an instant (does ``to_utc`` land on the right
wall clock, is ``utc_now`` UTC), a scale (does ``DECIMAL(12, 4)`` keep its four
digits), a capture (does the rewritten ``regexp_extract`` return group 1), a hex
casing (is the ``reject_id`` digest the lowercase hex every other port
produces), and a quarantine (does the failing row actually leave silver and land
in the reject table).

**No credentials, no failure** (S-0016/D-10): the five variables are absent for
every contributor who has not set them up, and the lane then skips with a
stated reason. It runs on ``main``, on a schedule and on manual dispatch,
behind the ``databricks-free`` GitHub Environment.

**Every relation this lane makes carries its own prefix** (S-0067/D-8): a live
warehouse is the most shared machine the suite touches — two CI runs and a
maintainer's laptop can be on it at once — so nothing here is addressed by a
literal another run could also pick.

Bronze sources are created as empty ``STRING`` columns read off the emitted
SQL. That is not an approximation of the source types: bloomery casts every
source expression explicitly (``TRY_CAST(position AS BIGINT)``,
``properties:gift_note``), so the produced types this lane checks come from the
casts and not from the column, and a column the derivation misses surfaces as
the engine's own ``UNRESOLVED_COLUMN`` rather than as a pass.

Opt-in; needs credentials rather than Docker, and excluded from ``just test``.
"""

from __future__ import annotations

import datetime
import hashlib
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import pytest
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import build_scope
from sqlglot.tokens import TokenType
from support import databricks as live
from support.compiling import compile_fixture, extract_select, load_fixture
from support.type_conformance import CASES, canonical, probe_sql, source_columns

from bloomery.dialects import get_dialect
from bloomery.emit import ArtifactKind
from bloomery.typing import parse_type

CREDENTIALS = live.credentials()

pytestmark = pytest.mark.engine("databricks")

#: On every test that talks to the warehouse — but *not* on the derivation test
#: at the end of this module, which is the one thing here a machine with no
#: credentials can still check. A lane whose every test skips is a lane whose
#: helpers are unexercised until someone sets up a workspace.
needs_warehouse = pytest.mark.skipif(
    CREDENTIALS is None,
    reason=live.missing_reason() if CREDENTIALS is None else "",
)

PORT = get_dialect("databricks")

#: The fixture whose emitted SQL carries the quality pipeline: two sources
#: merged, coercible rules, a reject table and a replay. The runtime lane seeds
#: two rows into it, which is the whole of its data.
QUALITY_FIXTURE = "multi_source_quality"

_CASES = {case.id: case for case in CASES}


# ....................... #
# The scratch namespace


@dataclass
class Scratch:
    """The run's own corner of ``catalog.schema``, and the rewrite that puts
    the emitted SQL there.

    The emitted relations are two-part (``bronze.shopify__order_lines``) and the
    lane owns one schema, so the namespace folds into the name:
    ``<prefix>bronze__shopify__order_lines``. Everything this fixture creates is
    dropped when it finishes.
    """

    warehouse: live.Warehouse
    prefix: str
    created: list[tuple[str, str]] = field(default_factory=list)

    def relation(self, namespace: str, name: str) -> str:
        credentials = self.warehouse.credentials
        return f"{credentials.catalog}.{credentials.schema}.{self.prefix}{namespace}__{name}"

    def rewrite(self, sql: str) -> str:
        """Every two-part relation reference moved into the scratch namespace,
        spliced into the emitted text — which is otherwise submitted character
        for character.

        Never a parse and re-render: SQLGlot's generator rewrites the port's own
        spellings on the way back out — ``TO_JSON(NAMED_STRUCT(…))`` becomes
        ``TO_JSON(STRUCT(… AS …))``, the backticks around the reserved name
        ``order`` are dropped, an extra ``CAST(… AS TIMESTAMP)`` appears inside
        ``TO_UTC_TIMESTAMP`` — so the analyzer would judge SQLGlot's SQL and
        never bloomery's, which is the one thing this lane exists to do. The
        parse below finds *which* names to move and nothing else.
        """
        moved: list[str] = []
        end_of_last = 0
        for start, end, namespace, name in _relation_spans(sql, _referenced(sql)):
            moved.append(sql[end_of_last:start])
            moved.append(self.relation(namespace, name))
            end_of_last = end + 1
        moved.append(sql[end_of_last:])
        return "".join(moved)

    def create(self, kind: str, relation: str, body: str) -> None:
        self.created.append((kind, relation))
        self.warehouse.execute(f"CREATE OR REPLACE {kind} {relation} {body}")

    def create_table(self, relation: str, columns: str) -> None:
        self.created.append(("TABLE", relation))
        self.warehouse.execute(f"CREATE TABLE IF NOT EXISTS {relation} ({columns})")

    def drop(self) -> None:
        # Reverse order: a view over a table cannot outlive it, and a drop that
        # fails must not stop the ones after it — an undropped relation on a
        # shared warehouse is the next run's confusing neighbour.
        for kind, relation in reversed(self.created):
            try:
                self.warehouse.execute(f"DROP {kind} IF EXISTS {relation}")
            except (live.EngineError, TimeoutError, OSError):  # pragma: no cover
                pass


@pytest.fixture
def scratch() -> Iterator[Scratch]:
    assert CREDENTIALS is not None  # the skipif above
    own = Scratch(live.Warehouse(CREDENTIALS), f"t{uuid.uuid4().hex[:8]}__")
    yield own
    own.drop()


# ....................... #
# The corpus, read off the emitted artifacts


def _models(fixture_name: str) -> tuple[tuple[str, str, str], ...]:
    """``(namespace, relation, select)`` per model, in dependency order.

    The order is computed from what each SELECT reads, the way
    :func:`support.execution.materialize` does it for DuckDB — the engine's
    scheduler stood in for. ``.sql`` only: a Python model is platform code this
    lane never runs.
    """
    selects = {}
    for artifact in compile_fixture(fixture_name, dialect="databricks"):
        if artifact.kind is not ArtifactKind.MODEL or not artifact.path.endswith(".sql"):
            continue
        path = PurePosixPath(artifact.path)
        selects[f"{path.parent.name}.{path.stem}"] = extract_select(artifact.content)

    pending = {
        name: (_referenced(select) & selects.keys()) - {name} for name, select in selects.items()
    }
    ordered: list[tuple[str, str, str]] = []
    built: set[str] = set()
    while pending:
        ready = sorted(name for name, deps in pending.items() if deps <= built)
        assert ready, f"cyclic model dependencies among {sorted(pending)}"
        for name in ready:
            namespace, _, relation = name.partition(".")
            ordered.append((namespace, relation, selects[name]))
            built.add(name)
            del pending[name]
    return tuple(ordered)


def _referenced(select: str) -> frozenset[str]:
    """Every two-part relation the SELECT reads, as ``namespace.relation``."""
    tree = sqlglot.parse_one(select, dialect="databricks")
    return frozenset(
        f"{table.args['db'].name}.{table.this.name}"
        for table in tree.find_all(exp.Table)
        if table.args.get("db") is not None and isinstance(table.this, exp.Identifier)
    )


def _relation_spans(sql: str, names: frozenset[str]) -> tuple[tuple[int, int, str, str], ...]:
    """``(start, end, namespace, relation)`` per two-part reference in the text.

    The tokenizer rather than the parse tree, because the span has to be a range
    of the *emitted* characters: a rewrite that goes through the generator is a
    rewrite of the SQL under test (see :meth:`Scratch.rewrite`). ``names`` keeps
    a qualified column (``_extract.line_no``) from being read as a relation —
    only a pair the parse called a table is spliced.
    """
    tokens = sqlglot.tokenize(sql, dialect="databricks")
    spans: list[tuple[int, int, str, str]] = []
    for index, namespace in enumerate(tokens[:-2]):
        dot, name = tokens[index + 1], tokens[index + 2]
        if dot.token_type is not TokenType.DOT:
            continue
        if f"{namespace.text}.{name.text}" not in names:
            continue
        if spans and namespace.start <= spans[-1][1]:  # pragma: no cover — a 3-part name
            continue
        spans.append((namespace.start, name.end, namespace.text, name.text))
    return tuple(spans)


def _source_columns(models: tuple[tuple[str, str, str], ...]) -> dict[str, frozenset[str]]:
    """``namespace.relation -> columns`` for the relations nothing here builds.

    Resolved through SQLGlot's scopes rather than by collecting every column
    name in the tree: an unqualified column is attributed to its scope's table
    only when that scope has exactly one, so the outer ``QUALIFY``'s
    ``PARTITION BY order_id`` — a column of a derived table, not of bronze —
    does not invent a bronze column.
    """
    built = {f"{namespace}.{relation}" for namespace, relation, _ in models}
    columns: dict[str, set[str]] = {}

    for _namespace, _relation, select in models:
        root = build_scope(sqlglot.parse_one(select, dialect="databricks"))
        assert root is not None
        for scope in root.traverse():
            # Two-part references only. The calendar's ``EXPLODE(SEQUENCE(…))``
            # is an :class:`exp.Table` too — a table *function*, with no
            # namespace and nothing to create.
            tables = {
                alias: source
                for alias, source in scope.sources.items()
                if isinstance(source, exp.Table)
                and source.args.get("db") is not None
                and _name_of(source) not in built
            }
            for column in scope.columns:
                source = tables.get(column.table) if column.table else _sole(tables, scope)
                if source is not None:
                    columns.setdefault(_name_of(source), set()).add(column.name)

    return {relation: frozenset(names) for relation, names in columns.items()}


def _sole(tables: dict[str, exp.Table], scope: object) -> exp.Table | None:
    """The scope's only table, when it has exactly one source and it is a table.

    A scope reading a derived table has no table of its own, so an unqualified
    column there belongs to the subquery's projection and not to a relation
    this lane would have to create.
    """
    sources = getattr(scope, "sources", {})
    if len(sources) == 1 and len(tables) == 1:
        return next(iter(tables.values()))
    return None


def _name_of(table: exp.Table) -> str:
    return f"{table.args['db'].name}.{table.this.name}" if table.args.get("db") else table.name


def _create_sources(own: Scratch, models: tuple[tuple[str, str, str], ...]) -> None:
    for relation, names in sorted(_source_columns(models).items()):
        namespace, _, name = relation.partition(".")
        columns = ", ".join(f"`{column}` STRING" for column in sorted(names))
        own.create_table(own.relation(namespace, name), columns)


def _declared_types(fixture_name: str) -> dict[str, dict[str, str]]:
    """``entity -> field -> physical type`` as the compiler declares it.

    The entity model is the declaration; the port spells it. Read from the spec
    rather than from the emitted casts, so the check has a side the engine had
    no hand in.
    """
    project, _catalog = load_fixture(fixture_name)
    return {
        name: {
            field_name: canonical(
                PORT.physical_type(parse_type(spec.type, source_path=f"{name}.{field_name}")),
                dialect=PORT.name,
            )
            for field_name, spec in entity.fields.items()
        }
        for name, entity in project.entity_model.entities.items()
    }


# ....................... #
# The authoritative lane: EXPLAIN EXTENDED + DESCRIBE QUERY


@needs_warehouse
@pytest.mark.parametrize("fixture_name", live.CORPUS)
def test_compile_corpus_is_accepted_and_typed(scratch: Scratch, fixture_name: str) -> None:
    """Every emitted model is accepted by the analyzer, and the types it
    produces are the types the compiler declared."""
    models = _models(fixture_name)
    assert models, f"{fixture_name} emitted no SQL models"
    _create_sources(scratch, models)
    declared = _declared_types(fixture_name)

    for namespace, relation, select in models:
        statement = scratch.rewrite(select)
        scratch.warehouse.explain(statement)
        produced = scratch.warehouse.describe(statement)

        # Only the entity's own fields: a mart's columns are derived, and the
        # `_quality_*` metadata columns are the lowering's, not a declaration.
        expected = declared.get(relation, {})
        disagreed = {
            column: (spelling, produced.get(column))
            for column, spelling in expected.items()
            if column in produced
            and canonical(produced[column], dialect=PORT.name) != spelling
        }
        assert not disagreed, (
            f"{fixture_name} {namespace}.{relation}: the warehouse produces types the "
            f"compiler did not declare — column: (declared, produced) {disagreed}"
        )

        # The next model reads this one; a view scans nothing.
        scratch.create("VIEW", scratch.relation(namespace, relation), f"AS {statement}")


# ....................... #
# The runtime lane: the small corpus over tiny tables


@pytest.fixture
def probe(scratch: Scratch) -> str:
    """One row, one column per transform case — the type battery's probe table
    (:mod:`support.type_conformance`), on a real warehouse.

    A real column rather than a folded constant, for the reason that corpus
    gives: an engine may evaluate a constant at plan time and answer a
    different question than the one asked.
    """
    relation = scratch.relation("runtime", "probe")
    columns = ", ".join(
        f"CAST({_literal(value)} AS {physical}) AS `{name}`"
        for name, physical, value in source_columns(PORT)
    )
    scratch.create("TABLE", relation, f"AS SELECT {columns}")
    return relation


def _literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _probe(scratch: Scratch, probe_relation: str, case_id: str) -> str | None:
    return scratch.warehouse.scalar(
        probe_sql(_CASES[case_id], PORT, relation=probe_relation),
    )


@needs_warehouse
def test_runtime_instant_lands_on_the_utc_wall_clock(scratch: Scratch, probe: str) -> None:
    """``to_utc`` shifts by the zone's real offset, and ``utc_now`` is UTC.

    The port renders ``to_utc`` as ``TO_UTC_TIMESTAMP`` because SQLGlot's
    databricks generator lowers the neutral node to ``FROM_UTC_TIMESTAMP`` —
    the opposite direction, wrong by twice the offset and silent about it. Only
    a warehouse can say which way the value actually moved.
    """
    # 2026-01-06 23:30:00 in Europe/Berlin (CET, +01:00) is 22:30:00 UTC.
    shifted = _probe(scratch, probe, "to_utc-timestamp")
    assert shifted is not None and shifted.startswith("2026-01-06 22:30:00"), shifted

    now = scratch.warehouse.scalar(PORT.render(exp.select(exp.alias_(PORT.utc_now(), "probe"))))
    assert now is not None
    observed = datetime.datetime.fromisoformat(now).replace(tzinfo=datetime.UTC)
    # Generous: a cold warehouse takes a while to answer, and the failure this
    # catches is an hour wide, not a second wide.
    assert abs(observed - datetime.datetime.now(datetime.UTC)) < datetime.timedelta(minutes=30), (
        f"utc_now() is not the UTC wall clock: {now}"
    )


@needs_warehouse
def test_runtime_decimal_keeps_its_declared_scale(scratch: Scratch, probe: str) -> None:
    """``to_decimal`` produces four fractional digits, not a rounded float."""
    assert _probe(scratch, probe, "to_decimal-string") == "3.5000"


@needs_warehouse
def test_runtime_regex_extract_returns_the_capture_group(scratch: Scratch, probe: str) -> None:
    """Group 1, not group 0: SQLGlot drops the capture index on this dialect
    and the port restates it, where the engine's own default is 1 rather than
    the 0 the other ports carry. A compile cannot tell the two apart."""
    assert _probe(scratch, probe, "regex_extract-string") == "42"


@needs_warehouse
def test_runtime_digest_is_lowercase_hex(scratch: Scratch) -> None:
    """``reject_id`` is a hex digest that must agree across every port, and
    ``SHA2`` is the one construction whose casing the engine decides."""
    statement = PORT.render(
        exp.select(exp.alias_(PORT.text_sha256(exp.Literal.string("bloomery")), "digest"))
    )
    assert scratch.warehouse.scalar(statement) == hashlib.sha256(b"bloomery").hexdigest()


@needs_warehouse
def test_runtime_failing_row_is_quarantined(scratch: Scratch) -> None:
    """The row whose ``quantity`` will not cast leaves silver and lands in the
    reject table, and the clean row does not.

    The one check here that needs rows at all: every branch of the disposition
    model renders as a predicate, and whether the predicate *diverts* the row
    is a question about evaluation.
    """
    models = _models(QUALITY_FIXTURE)
    _create_sources(scratch, models)
    _seed_quality_rows(scratch)

    for namespace, relation, select in models:
        statement = scratch.rewrite(select)
        scratch.create("TABLE", scratch.relation(namespace, relation), f"AS {statement}")

    silver = scratch.relation("silver", "order_line")
    kept = scratch.warehouse.rows(f"SELECT quantity, _quality_ok FROM {silver}")
    assert kept == (("2", "true"),), kept

    reject = scratch.relation("silver", "order_line__reject")
    quarantined = scratch.warehouse.rows(
        f"SELECT source_relation, failed_rules FROM {reject}",
    )
    assert len(quarantined) == 1, quarantined
    source_relation, failed_rules = quarantined[0]
    assert source_relation == "shopify__order_lines"
    assert failed_rules is not None and "quantity_coercible" in failed_rules


#: The clean row and the one the coercible rule quarantines — identical but for
#: ``quantity``, so the reject row can only be explained by the rule under test.
#: Columns the emitted SQL reads but nothing here names stay NULL.
_SEED = (
    {
        "order": '{"id": "o1"}',
        "position": "1",
        "quantity": "2",
        "variant": '{"sku": "sku-1"}',
        "properties": '{"gift_note": "keep"}',
        "financial_status": "paid",
        "created_at": "2024-01-02T03:04:05",
        "_source_row_id": "r1",
        "_load_id": "l1",
        "_ingested_at": "2024-01-03 00:00:00",
    },
    {
        "order": '{"id": "o2"}',
        "position": "1",
        "quantity": "not-a-number",
        "variant": '{"sku": "sku-2"}',
        "properties": '{"gift_note": "divert"}',
        "financial_status": "paid",
        "created_at": "2024-01-02T04:00:00",
        "_source_row_id": "r2",
        "_load_id": "l1",
        "_ingested_at": "2024-01-03 00:00:00",
    },
)


def _seed_quality_rows(own: Scratch) -> None:
    """Two rows into the shopify branch; the woo branch stays empty (a
    ``UNION ALL`` over no rows is still the union the port renders)."""
    relation = own.relation("bronze", "shopify__order_lines")
    columns = ", ".join(f"`{column}`" for column in _SEED[0])
    values = ", ".join(
        "(" + ", ".join(_literal(row[column]) for column in _SEED[0]) + ")" for row in _SEED
    )
    own.warehouse.execute(f"INSERT INTO {relation} ({columns}) VALUES {values}")


# ....................... #
# The one check a machine with no credentials can still make


@pytest.mark.parametrize("fixture_name", live.CORPUS)
def test_corpus_derivation_is_warehouse_independent(fixture_name: str) -> None:
    """The corpus, its order, its sources and the scratch rewrite — all of it
    computed from the emitted SQL, so all of it checkable without a workspace.

    Here rather than left to the live lane because a derivation bug and a
    warehouse outage look identical from a CI log, and only one of the two is
    this repository's fault. Everything the live tests do *before* they open a
    connection runs here on every nightly engine lane.
    """
    models = _models(fixture_name)
    assert models

    built: set[str] = set()
    for namespace, relation, select in models:
        name = f"{namespace}.{relation}"
        assert (_referenced(select) & {n for n, _, _ in ((f"{ns}.{rel}", 0, 0) for ns, rel, _ in models)}) - {
            name
        } <= built, f"{name} is ordered before something it reads"
        built.add(name)

    sources = _source_columns(models)
    assert sources, f"{fixture_name} reads no source relation"
    # Nothing the corpus builds is also created as a source: a model created as
    # an empty STRING table would shadow the view the lane means to check.
    assert not sources.keys() & built
    for relation, columns in sources.items():
        assert relation.startswith("bronze."), relation
        assert columns, f"{relation} would be created with no columns"

    own = Scratch(
        live.Warehouse(
            live.Credentials(host="", token="", warehouse_id="", catalog="cat", schema="sch")
        ),
        "t0__",
    )
    for _namespace, _relation, select in models:
        moved = own.rewrite(select)
        for table in sqlglot.parse_one(moved, dialect="databricks").find_all(exp.Table):
            if table.args.get("db") is None:
                continue  # the calendar's table function, which reads nothing
            assert (table.catalog, table.db) == ("cat", "sch"), moved
            assert table.name.startswith("t0__"), moved

        # Nothing but the relation names moved. Put each original name back and
        # the emitted SQL has to return character for character — the check that
        # fails the moment the rewrite goes through SQLGlot's generator again,
        # which rewrites the very constructs these fixtures are here for.
        restored = moved
        for start, end, namespace, relation in _relation_spans(select, _referenced(select)):
            scratch_name = own.relation(namespace, relation)
            restored = restored.replace(scratch_name, select[start : end + 1], 1)
        assert restored == select
