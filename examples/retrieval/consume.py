"""A runtime consuming the manifest — a demonstration, not a test.

`run.py` emits `out/retrieval_manifest.json`. This reads it back the way a
retrieval service would: it takes one profile, builds the SQL that serves a
top-k query from the declared relation, space, filters and projection, and — if
duckdb happens to be installed — creates the corpus table from the manifest's own
dimensions and scalar and asks duckdb to prepare the query, which proves the
manifest carries enough to form a valid one.

**This is not part of the test suite and nothing here is a claim bloomery makes.**
Where to put the vectors, which index to build, how to combine a rank list: all of
that is the runtime's, and the manifest is deliberately silent about it. What is
shown here is one plausible reading of the contract, in one engine's SQL.

The duckdb import is optional and local to the function that needs it — the
example prints the SQL and says so if it is missing.

Run from the repository root, after `run.py`:

    uv run python examples/retrieval/consume.py
"""

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
MANIFEST = HERE / "out" / "retrieval_manifest.json"

#: duckdb's spelling of the scalars a space may declare. The manifest gives a
#: logical scalar and a length; mapping them onto an engine's array type is the
#: runtime's job, which is why this table lives here and not in bloomery.
DUCKDB_SCALARS = {"float16": "FLOAT", "float32": "FLOAT", "float64": "DOUBLE"}

#: Likewise the distance: `cosine` names the metric, and which function computes
#: it is per engine.
DUCKDB_DISTANCE = {
    "cosine": "array_cosine_distance",
    "l2": "array_distance",
    "dot": "array_negative_inner_product",
}


def query_sql(profile: dict[str, Any], *, limit: int = 10) -> str:
    """The top-k query one profile describes, as duckdb SQL.

    Dense side only. A hybrid profile also declares a lexical side and a fusion
    method, and merging the two rank lists is the runtime's business — RRF is a
    handful of lines over two `row_number()` windows, and the manifest names the
    method precisely so that the runtime does not have to guess it.
    """
    relation, vector = profile["relation"], profile["vector"]
    space = vector["space"]
    distance = DUCKDB_DISTANCE[space["distance"]]
    scalar = DUCKDB_SCALARS[space["scalar"]]
    projection = ", ".join(profile["return"])
    filters = "".join(f"\n  -- filterable: {column}" for column in profile["filterable"])
    return (
        f"SELECT {projection},\n"
        f"       {distance}({vector['field']}, "
        f"?::{scalar}[{space['dimensions']}]) AS distance\n"
        f"FROM {relation['namespace']}.{relation['table']}{filters}\n"
        f"ORDER BY distance\n"
        f"LIMIT {limit}"
    )


def prepare(profile: dict[str, Any], sql: str) -> str:
    """Ask duckdb to prepare the query against a table shaped like the corpus.

    Prepared, never executed: there is no corpus here and no query vector, and
    inventing either would make this a benchmark of made-up numbers. Preparing is
    what answers the only question this script asks — is the manifest enough to
    build a query an engine accepts?
    """
    try:
        import duckdb
    except ImportError:  # pragma: no cover — a demonstration, not a test
        return "duckdb is not installed; skipping the prepare step"

    relation, vector = profile["relation"], profile["vector"]
    space = vector["space"]
    columns = ", ".join(f"{name} VARCHAR" for name in profile["return"] if name)
    array = f"{DUCKDB_SCALARS[space['scalar']]}[{space['dimensions']}]"

    connection = duckdb.connect()
    connection.execute(f"CREATE SCHEMA {relation['namespace']}")
    connection.execute(
        f"CREATE TABLE {relation['namespace']}.{relation['table']} "
        f"({columns}, {vector['field']} {array})"
    )
    connection.execute(f"PREPARE q AS {sql}")
    return f"duckdb prepared the query against a {array} column"


def main() -> None:
    if not MANIFEST.exists():
        raise SystemExit("run examples/retrieval/run.py first — no manifest to consume")

    manifest = json.loads(MANIFEST.read_text())
    print(f"manifest version {manifest['retrieval_manifest_version']}")

    for name, profile in sorted(manifest["profiles"].items()):
        sql = query_sql(profile)
        print(f"\n-- {name} --")
        print(sql)
        print(f"-- {prepare(profile, sql)}")


if __name__ == "__main__":
    main()
