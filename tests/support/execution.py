"""Shared execution-tier plumbing (RFC 0009 §5.1 ``tests/support/``): a fresh
in-process DuckDB warehouse, the CREATE-TABLE sweep that turns compiled model
artifacts into relations, and the audit-body extraction the RFC 0016 audits
need.

Promoted out of the individual tier-4 modules because M12 adds several more
suites that build the same warehouse the same way, and a second hand-rolled
sweep is exactly how a build-order bug (a mart materialized before the silver
relation it reads) ships unnoticed.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import duckdb
import sqlglot
from sqlglot import expressions as exp
from support.compiling import expand_engine_macros, extract_select

from bloomery.emit import ArtifactKind, EmittedArtifact
from bloomery.emit.lowering import THIS_MODEL

__all__ = [
    "DEFAULT_SCHEMAS",
    "audit_body",
    "materialize",
    "merge_assignments",
    "model_relations",
    "relation_of",
    "replay_statements",
    "snapshot",
    "warehouse",
]

#: The three layers every compiled project addresses (RFC 0008 §5.1).
DEFAULT_SCHEMAS = ("bronze", "silver", "gold")


def warehouse(*schemas: str, database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    """A fresh DuckDB connection with the layer schemas created and the session
    pinned to UTC — the timezone matters because ``timestamp`` is always-UTC in
    the type system (RFC 0004 §5.1)."""
    connection = duckdb.connect(database)
    connection.execute("SET TimeZone = 'UTC'")
    for schema in schemas or DEFAULT_SCHEMAS:
        connection.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    return connection


def relation_of(artifact: EmittedArtifact) -> tuple[str, str]:
    """``(namespace, relation)`` for a model artifact, read off its path."""
    path = PurePosixPath(artifact.path)
    return (path.parent.name, path.stem)


def _referenced(select: str, known: frozenset[str]) -> frozenset[str]:
    """The model relations one SELECT reads, as ``namespace.relation``.

    Read off the parsed AST rather than guessed from the path: the M12 graph is
    no longer layered-by-name — a ``referential`` rule LEFT JOINs a *sibling*
    silver entity (RFC 0016 §5.1), so ``dirty_ref`` must be built after
    ``dirty_ref_parent`` even though both are silver and the second sorts last.
    """
    tree = sqlglot.parse_one(select, dialect="duckdb")
    names = {
        f"{table.args['db'].name}.{table.this.name}"
        for table in tree.find_all(exp.Table)
        if table.args.get("db") is not None and isinstance(table.this, exp.Identifier)
    }
    return frozenset(names & known)


_UNIQUE_KEY = re.compile(r"kind INCREMENTAL_BY_UNIQUE_KEY \(unique_key \((?P<keys>[^)]*)\)")
_WHEN_MATCHED = re.compile(r"when_matched \(WHEN MATCHED THEN UPDATE SET (?P<clause>.*)\)\)")

#: SQLMesh's spelling of the two sides of a merge inside ``when_matched``.
_MERGE_TARGET = "target"
_MERGE_SOURCE = "source"
_INCOMING = "_incoming"


def merge_assignments(clause: str) -> str:
    """The rendered ``when_matched`` assignments, as a DuckDB ``SET`` list.

    Two things happen here and both are structural. DuckDB rejects a qualified
    assignment target, as every engine does — the left side of a MERGE ``SET``
    is a bare column of the target — so the ``target.`` qualification comes off
    the left side and stays on the right, where it names the incumbent row.

    **Parsed, not split.** The clause used to be taken apart on ``", "``, which
    also occurs inside ``COALESCE(target.first_seen, source.first_seen)``; the
    fragments were then prefix-stripped and rejoined, and came out right only
    because no assignment's value happened to *begin* with ``target.``. One that
    did would have had it eaten, and the harness would have quietly diverged
    from the artifact it exists to stand in for.
    """
    update = sqlglot.parse_one(f"UPDATE _t SET {clause}", dialect="duckdb")
    return ", ".join(
        f"{assignment.this.name} = {assignment.expression.sql(dialect='duckdb')}"
        for assignment in update.args["expressions"]
    )


def _upsert(
    conn: duckdb.DuckDBPyConnection, name: str, keys: list[str], clause: str | None
) -> None:
    """The ``INCREMENTAL_BY_UNIQUE_KEY`` branch, honouring ``when_matched``.

    The framework's job, stood in for — and it has to be stood in for
    *honestly*, because ``when_matched`` is where RFC 0016 §5.6 puts the rule
    that ``first_seen`` survives a re-delivery. A harness that always replaced
    the whole row would pass a test the real target fails, which is worse than
    no harness at all.

    With no clause the merge updates every column, which is SQLMesh's default.
    """
    predicate = " AND ".join(f"{_MERGE_TARGET}.{key} = {_MERGE_SOURCE}.{key}" for key in keys)
    update = "UPDATE SET *" if clause is None else f"UPDATE SET {merge_assignments(clause)}"
    conn.execute(
        f"MERGE INTO {name} AS {_MERGE_TARGET} USING {_INCOMING} AS {_MERGE_SOURCE} "
        f"ON {predicate} WHEN MATCHED THEN {update} WHEN NOT MATCHED THEN INSERT"
    )


def _apply(conn: duckdb.DuckDBPyConnection, artifact: EmittedArtifact, name: str) -> None:
    """Run one model the way its declared ``kind`` says to.

    The framework's job, stood in for — and it has to be stood in for honestly,
    because "full refresh ≡ incremental history" (§6's merge gate) is a
    statement *about* the difference between these two branches. A FULL model
    replaces its table; an ``INCREMENTAL_BY_UNIQUE_KEY`` one upserts by its
    declared key, which is what makes a re-delivered source row land on the
    **same** reject row rather than minting a new one (RFC 0016 D21).
    """
    namespace, relation = name.split(".", 1)
    select = extract_select(artifact.content)
    exists = conn.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
        [namespace, relation],
    ).fetchone()
    match = _UNIQUE_KEY.search(artifact.content)
    if not exists or not exists[0]:
        conn.execute(f"CREATE TABLE {name} AS {select}")
    elif match is None:
        conn.execute(f"CREATE OR REPLACE TABLE {name} AS {select}")
    else:
        when_matched = _WHEN_MATCHED.search(artifact.content)
        conn.execute(f"CREATE OR REPLACE TEMP TABLE {_INCOMING} AS {select}")
        _upsert(
            conn,
            name,
            [key.strip() for key in match.group("keys").split(",")],
            when_matched.group("clause") if when_matched else None,
        )
        conn.execute(f"DROP TABLE {_INCOMING}")


def materialize(conn: duckdb.DuckDBPyConnection, artifacts: tuple[EmittedArtifact, ...]) -> None:
    """Run every model artifact against ``conn``, in dependency order.

    The order is computed from what each SELECT actually reads, then broken by
    path so the sweep is deterministic — the engine's scheduler stood in for,
    the same way :func:`support.compiling.expand_engine_macros` stands in for
    its macros. Calling it a second time is a **re-run**, not a rebuild: see
    :func:`_apply`.
    """
    models = {a.path: a for a in artifacts if a.kind is ArtifactKind.MODEL}
    names = {path: ".".join(relation_of(a)) for path, a in models.items()}
    known = frozenset(names.values())
    pending = {
        path: _referenced(extract_select(a.content), known) - {names[path]}
        for path, a in models.items()
    }
    built: set[str] = set()
    while pending:
        ready = sorted(path for path, deps in pending.items() if deps <= built)
        if not ready:  # pragma: no cover — a cycle would be a compiler bug
            msg = f"cyclic model dependencies among {sorted(pending)}"
            raise AssertionError(msg)
        for path in ready:
            _apply(conn, models[path], names[path])
            built.add(names[path])
            del pending[path]


def snapshot(
    conn: duckdb.DuckDBPyConnection, relations: tuple[str, ...]
) -> dict[str, list[tuple[object, ...]]]:
    """Every row of every named relation, order-normalized.

    Sorted by the rendered row rather than by a key, because the point of a
    snapshot comparison is that *nothing* moved — including columns no key
    covers. Lists rather than sets, so a duplicated row is a visible diff.
    """
    return {
        relation: sorted(
            (tuple(row) for row in conn.execute(f"SELECT * FROM {relation}").fetchall()),
            key=repr,
        )
        for relation in relations
    }


def model_relations(artifacts: tuple[EmittedArtifact, ...]) -> tuple[str, ...]:
    """Every relation the artifacts build, sorted."""
    return tuple(
        sorted(".".join(relation_of(a)) for a in artifacts if a.kind is ArtifactKind.MODEL)
    )


def audit_body(artifact: EmittedArtifact, model_relation: str) -> str:
    """The runnable query inside an ``AUDIT (...)`` artifact.

    Audits are the one artifact kind the execution tier cannot run verbatim:
    their bodies address the audited model through the target's ``@this_model``
    macro, which only the framework expands. Substituting the physical relation
    here is the same stand-in as :func:`support.compiling.expand_engine_macros`
    — the engine's job, done by the harness, so tier 4 can assert on audit
    results without a framework in the loop. An audit passes when its query
    returns no rows.
    """
    _envelope, _sep, body = artifact.content.partition(");")
    return expand_engine_macros(body.strip()).replace(THIS_MODEL, model_relation)


def replay_statements(artifact: EmittedArtifact) -> tuple[str, ...]:
    """The runnable statements inside a replay artifact (RFC 0016 §5.6).

    The artifact is not a MODEL block — it is a script the *caller* runs, and
    §5.6 says to run its statements "as one unit of work". Leading ``--`` lines
    are the generated header; no statement body contains a ``;``.
    """
    body = "\n".join(line for line in artifact.content.splitlines() if not line.startswith("--"))
    return tuple(statement.strip() for statement in body.split(";") if statement.strip())
