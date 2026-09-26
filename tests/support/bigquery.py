"""Live BigQuery harness for the authoritative compile rung (S-0012/D-3): the
service's own parser, binder and type resolution answering over HTTP, with
nothing executed and nothing scanned.

**No cloud SDK, here or anywhere** (S-0012/D-4). A dry run is one POST to
``jobs.query`` with ``dryRun: true`` and a bearer token, and the table listing
is one GET — so this harness is `urllib` and nothing else. The driver a
dependency group would carry (`google-cloud-bigquery`, and the six packages
under it) would have to be resolved into `uv.lock` by every contributor on
every sync to save two request bodies.

**The dataset is provisioned out of band, and exists before this lane does**
(S-0014/D-5). The CI identity issues query jobs and dry runs and reads the test
dataset's metadata; it does not create tables. bloomery emits two-part names —
`bronze.raw__events` — where each namespace is a dataset of its own in a real
deployment; here every namespace is flattened into the one dedicated dataset,
`<project>.<dataset>.bronze__raw__events`, so the provisioned surface is a
single object with a single IAM grant. Whatever is missing from it is named in
the skip message, which is also the provisioning list.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import sqlglot
from sqlglot import exp

#: Read rather than invented: `google-github-actions/auth` with
#: `token_format: access_token` produces the token, and a developer's
#: `gcloud auth print-access-token` produces the same thing locally.
PROJECT_ENV = "BLOOMERY_BIGQUERY_PROJECT"
DATASET_ENV = "BLOOMERY_BIGQUERY_DATASET"
TOKEN_ENV = "BLOOMERY_BIGQUERY_TOKEN"
REQUIRED = (PROJECT_ENV, DATASET_ENV, TOKEN_ENV)

API = "https://bigquery.googleapis.com/bigquery/v2"
TIMEOUT_SECONDS = 60

DIALECT = "bigquery"

#: A SQLMesh macro left unexpanded, outside string literals — which is where an
#: `@` legitimately appears in emitted SQL and a macro never does. The engine
#: expands `@this_model` and `@execution_ds` at run time and there is no SQLMesh
#: in this lane, so one that survives to the request reaches BigQuery's parser
#: as a table name or a column: the 400 that comes back names the port, and the
#: fault is the harness's. Caught here rather than in the caller, because every
#: statement this lane submits is qualified first.
_MACRO = re.compile(r"@\w+")
_LITERAL = re.compile(r"'(?:[^']|'')*'")


class DryRunRejected(AssertionError):
    """The engine refused a statement. Carries BigQuery's own message: what a
    port is being validated against is the service's diagnostic, and a
    reworded one costs the reader the line and column."""


@dataclass(frozen=True)
class LiveDataset:
    """Where the lane resolves names, and what it authenticates with."""

    project: str
    dataset: str
    token: str

    def __str__(self) -> str:
        return f"{self.project}.{self.dataset}"

    def relation(self, namespace: str, name: str) -> str:
        """``bronze``, ``raw__events`` → the flattened table's local name."""
        return f"{namespace}__{name}"

    def path(self, relation: str) -> str:
        return f"`{self.project}.{self.dataset}.{relation}`"


def live_dataset() -> LiveDataset:
    """The configured dataset, or a skip naming what is unset.

    Skipping rather than failing is what keeps a fork's pull request green and
    what lets this lane's acceptance command run quiet in a sandbox with no
    credential at all (S-0012/credentials-and-ci).
    """
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        pytest.skip(f"live BigQuery credentials are not configured ({', '.join(missing)} unset)")
    return LiveDataset(
        project=os.environ[PROJECT_ENV],
        dataset=os.environ[DATASET_ENV],
        token=os.environ[TOKEN_ENV],
    )


def _call(dataset: LiveDataset, url: str, payload: dict[str, object] | None = None) -> dict:
    """One BigQuery REST call. A refusal arrives as HTTP 400 with the message
    in the body, so the body is read on the error path rather than discarded
    for a bare ``HTTP Error 400: Bad Request``."""
    request = urllib.request.Request(
        url,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {dataset.token}",
            "Content-Type": "application/json",
        },
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        try:
            detail = json.loads(detail)["error"]["message"]
        except (ValueError, KeyError):
            pass
        raise DryRunRejected(f"{error.code} from BigQuery: {detail}") from None


def provisioned_tables(dataset: LiveDataset) -> frozenset[str]:
    """Every table in the dedicated dataset — metadata, not data.

    Paginated: the corpus needs ninety-odd relations and the API returns fifty
    a page, so a single call would report two thirds of the dataset as
    unprovisioned and skip the fixtures that read the rest.
    """
    names: set[str] = set()
    url = f"{API}/projects/{dataset.project}/datasets/{dataset.dataset}/tables?maxResults=1000"
    while True:
        page = _call(dataset, url)
        for table in page.get("tables", ()):
            names.add(table["tableReference"]["tableId"])
        token = page.get("nextPageToken")
        if not token:
            return frozenset(names)
        url = (
            f"{API}/projects/{dataset.project}/datasets/{dataset.dataset}"
            f"/tables?maxResults=1000&pageToken={token}"
        )


def refuse_macros(sql: str) -> None:
    """Refuse an unexpanded SQLMesh macro rather than submitting it.

    It stands where a relation or a column goes, so BigQuery would reject it and
    the diagnostic would read as a port failure. Checked on every statement
    either lane sends, because both build theirs out of emitted artifacts.
    """
    unexpanded = _MACRO.findall(_LITERAL.sub("''", sql))
    assert not unexpanded, (
        f"unexpanded SQLMesh macro reached BigQuery: {', '.join(sorted(set(unexpanded)))}. "
        f"The engine expands these at run time and this lane has no engine — bind them before "
        f"submitting, or BigQuery's refusal reports the harness as a port defect."
    )


def _rebind(sql: str, replacement: Callable[[str, str], str | None], *, where: str) -> str:
    """Each two-part table reference rewritten once, textually.

    Textual over the table references SQLGlot *finds*, never a re-render of the
    parse: what these lanes submit has to be bloomery's own rendering, and a
    statement that went out through SQLGlot's generator would be validating the
    round trip instead of the port.

    A reference with no namespace is a CTE — bloomery emits no bare relation —
    so it is left alone, as is one *replacement* declines by returning ``None``.
    """
    seen: set[str] = set()
    for table in sqlglot.parse_one(sql, read=DIALECT).find_all(exp.Table):
        if not table.db or f"{table.db}.{table.name}" in seen:
            # `re.sub` rewrote every occurrence the first time round.
            continue
        target = replacement(table.db, table.name)
        if target is None:
            continue
        seen.add(f"{table.db}.{table.name}")
        # Rendered from the identifiers rather than from the node, which would
        # drag an alias along with it, and spelled through SQLGlot so that a
        # quoted `silver.`order`` is matched as the emitter wrote it.
        written = ".".join(
            part.sql(dialect=DIALECT) for part in (table.args.get("db"), table.this) if part
        )
        # Bounded rather than a bare `str.replace`: `silver.inventory_level` is a
        # prefix of `silver.inventory_level__reject`, and a plain substitution
        # rewrites the prefix inside the longer name and leaves the tail dangling
        # off the end of a backquoted path.
        occurrence = re.compile(rf"(?<![\w.`]){re.escape(written)}(?![\w`])")
        # A spelling this does not find is counted as rewritten and left
        # pointing at something that does not exist — a silent no-op whose
        # symptom arrives as BigQuery refusing a name the port never wrote.
        assert occurrence.search(sql), (
            f"{written} is not how this statement spells {table.db}.{table.name}, so the "
            f"rewrite to {where} would silently do nothing"
        )
        sql = occurrence.sub(lambda _match, bound=target: bound, sql)
    return sql


def qualify(sql: str, dataset: LiveDataset) -> tuple[str, frozenset[str]]:
    """The emitted SQL with its relations pointed at the dedicated dataset, and
    the flattened names it reads.
    """
    refuse_macros(sql)

    relations: set[str] = set()

    def target(namespace: str, name: str) -> str:
        relation = dataset.relation(namespace, name)
        relations.add(relation)
        return dataset.path(relation)

    return _rebind(sql, target, where=str(dataset)), frozenset(relations)


def as_written(relation: str) -> str:
    """A two-part relation spelled the way the port renders it in a FROM.

    `silver.order` is ``silver.`order``` on BigQuery, and :func:`qualify`
    matches the emitter's spelling — so a relation substituted into a statement
    by hand has to arrive in that spelling to be rewritten at all.
    """
    return exp.to_table(relation, dialect=DIALECT).sql(dialect=DIALECT)


def dry_run(dataset: LiveDataset, sql: str) -> dict:
    """Parse, bind and type-check one statement on the real service.

    ``dryRun`` means no job is inserted, nothing is executed and nothing is
    scanned; ``useQueryCache`` is off so that a second run of the lane asks the
    compiler again rather than a cache.
    """
    return _call(
        dataset,
        f"{API}/projects/{dataset.project}/queries",
        {
            "query": sql,
            "dryRun": True,
            "useQueryCache": False,
            "useLegacySql": False,
            "defaultDataset": {"projectId": dataset.project, "datasetId": dataset.dataset},
        },
    )


# ....................... #
# The execution lane

#: The execution lane's own switch. The dry-run job and the execution job are
#: separate jobs (S-0014/ci-identity), and this is the only lane here that can
#: bill a byte — so it runs where it is enabled and skips wherever it is not,
#: including in a dry-run job holding the same three credentials.
EXECUTE_ENV = "BLOOMERY_BIGQUERY_EXECUTE"

#: Declared on every executed job, one mebibyte. The corpus arrives inline, so a
#: statement that reads a *table* at all has gone wrong somewhere upstream, and
#: BigQuery refuses the job over the limit rather than billing it and telling
#: someone next month ("tiny tables, explicit byte limits").
MAX_BYTES_BILLED = 1 << 20

#: ``jobs.query`` returns rows inline when the job finishes inside ``timeoutMs``,
#: and a query over literals does. The bound exists so that a lane queued behind
#: a busy project fails saying so, rather than waiting out pytest's own timeout
#: with nothing to read.
POLL_ATTEMPTS = 3

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: What a BigQuery string literal may not carry raw. The corpus is full of
#: specimens that need every one of these: a JSON escape of a lone surrogate
#: (`\ud800`, six characters beginning with a backslash), a tab inside a field.
_ESCAPES = str.maketrans({"\\": "\\\\", "'": "\\'", "\n": "\\n", "\r": "\\r", "\t": "\\t"})


def executing_dataset() -> LiveDataset:
    """The dataset for the execution lane, or a skip naming what is unset.

    Two conditions, stated separately: the credentials :func:`live_dataset`
    wants, and this lane's own switch. A dry-run job carries the first and not
    the second, and the reason it skips has to say which.
    """
    if not os.environ.get(EXECUTE_ENV):
        pytest.skip(f"the BigQuery execution lane is not enabled ({EXECUTE_ENV} unset)")
    return live_dataset()


def _scalar(kind: str, raw: str) -> object:
    """One REST cell, typed by the schema field that describes it.

    Everything arrives as text over this API, so a lane that skipped this step
    would be comparing ``"12.500000000"`` against a number and an instant
    against a float of seconds — which is to say, asserting nothing about the
    two things this lane exists for.
    """
    if kind in {"INTEGER", "INT64"}:
        return int(raw)
    if kind in {"NUMERIC", "BIGNUMERIC"}:
        # A `Decimal` keeps the scale BigQuery sent, which `float` would not and
        # which is half of what a declared `decimal(p, s)` has to answer for.
        return Decimal(raw)
    if kind in {"FLOAT", "FLOAT64"}:
        return float(raw)
    if kind in {"BOOLEAN", "BOOL"}:
        return raw == "true"
    if kind == "DATE":
        return date.fromisoformat(raw)
    if kind == "DATETIME":
        # Naive, which is what a zoneless-UTC `timestamp` is (S-0021).
        return datetime.fromisoformat(raw)
    if kind == "TIMESTAMP":
        # Epoch seconds as text, read as a decimal rather than a float: the
        # subject here is the exact instant, and 1.7e9 seconds carrying
        # microseconds sits at the edge of what a float64 keeps.
        return _EPOCH + timedelta(microseconds=int(Decimal(raw) * 1_000_000))
    if kind == "BYTES":
        return base64.b64decode(raw)
    return raw


def _cell(field: dict, cell: dict) -> object:
    value = cell.get("v")
    if value is None:
        return None
    if field.get("mode") == "REPEATED":
        # `_quality_flags` and `failed_rules` are arrays wherever the dialect has
        # one (S-0033/D-23), and an empty array is not a NULL — the distinction
        # the whole disposition vocabulary rests on.
        return tuple(_cell({**field, "mode": "NULLABLE"}, item) for item in value)
    kind = str(field["type"])
    assert kind not in {"RECORD", "STRUCT"}, (
        f"{field['name']} is a struct, which this harness does not flatten — select its "
        f"fields, so that what a failure prints is the value that disagreed"
    )
    return _scalar(kind, str(value))


def _rows(response: dict) -> list[tuple[object, ...]]:
    fields = response.get("schema", {}).get("fields", ())
    # A truncated result is the one failure mode that presents as a *passing*
    # assertion about fewer rows, and the corpus is small enough that a second
    # page means something else changed.
    assert not response.get("pageToken"), (
        "the result spilled to a second page: this lane's corpus fits in one, so either the "
        "seed has grown or the query is reading something it should not"
    )
    return [
        tuple(_cell(field, cell) for field, cell in zip(fields, row["f"], strict=True))
        for row in response.get("rows", ())
    ]


def execute(dataset: LiveDataset, sql: str) -> list[tuple[object, ...]]:
    """Run one statement and return its rows, typed by the result schema.

    Unlike :func:`dry_run` this produces values, which is the only reason the
    lane exists: an instant, a decimal's scale, whether a row was in fact
    quarantined. ``useQueryCache`` is off for the reason it is off there — a
    second run must ask the engine again — and ``maximumBytesBilled`` is what
    keeps a mistake a refusal instead of an invoice.
    """
    refuse_macros(sql)
    response = _call(
        dataset,
        f"{API}/projects/{dataset.project}/queries",
        {
            "query": sql,
            "useQueryCache": False,
            "useLegacySql": False,
            "maximumBytesBilled": str(MAX_BYTES_BILLED),
            "timeoutMs": TIMEOUT_SECONDS * 1000,
            "defaultDataset": {"projectId": dataset.project, "datasetId": dataset.dataset},
        },
    )
    for _attempt in range(POLL_ATTEMPTS):
        if response.get("jobComplete"):
            return _rows(response)
        job = response["jobReference"]
        location = f"&location={job['location']}" if job.get("location") else ""
        response = _call(
            dataset,
            f"{API}/projects/{job['projectId']}/queries/{job['jobId']}"
            f"?timeoutMs={TIMEOUT_SECONDS * 1000}{location}",
        )
    raise AssertionError(
        f"{dataset}: the query did not complete within {POLL_ATTEMPTS} waits of "
        f"{TIMEOUT_SECONDS}s, which a query over inline literals has no business doing"
    )


def literal_table(rows: Sequence[Mapping[str, object]]) -> str:
    """Rows as an inline table: one ``SELECT`` of literals per row, unioned.

    Inline rather than seeded, because the CI identity issues jobs and reads the
    test dataset's metadata and does **not** create tables (S-0014/D-5) — and
    because a literal scans nothing, which is what leaves
    :data:`MAX_BYTES_BILLED` an assertion rather than a budget.

    Every value is a ``STRING`` or a typed NULL: a bronze relation in the dirty
    corpus is read all-varchar (`tests/support/dirty.py:71`), and what is under
    test is the mapping that types it. The two are a different value and the
    corpus is built around the difference, so the NULL keeps its own spelling.
    """
    assert rows, "an inline table with no rows has no column names to give BigQuery"
    columns = tuple(rows[0])
    literals = []
    for row in rows:
        assert tuple(row) == columns, f"{tuple(row)} does not carry the columns {columns}"
        literals.append(
            "SELECT "
            + ", ".join(
                f"CAST(NULL AS STRING) AS {name}"
                if value is None
                else f"'{str(value).translate(_ESCAPES)}' AS {name}"
                for name, value in row.items()
            )
        )
    return " UNION ALL ".join(literals)


def inlined(sql: str, sources: Mapping[str, str]) -> str:
    """``sql`` with every relation in *sources* bound to a CTE of its own rows.

    *sources* maps ``namespace.relation`` to the SELECT that stands for it: a
    :func:`literal_table` for a bronze relation, the emitted model body for a
    silver one. So the statement reads the fixture's own SQL over the fixture's
    own specimens, with nothing provisioned and nothing scanned — which is what
    lets the execution lane run the shared corpus (S-0012/D-6) under an identity
    that may only issue jobs.

    A source whose body reads a relation *sources* does not carry is left out,
    and so is everything depending on it: a CTE that cannot bind fails the whole
    statement, and the failure would name a relation no test asked about.
    """
    flattened = {relation: relation.replace(".", "__") for relation in sources}

    def reads(body: str) -> frozenset[str]:
        # Every two-part reference, not only the ones *sources* carries: a body
        # reading a relation nobody seeded is exactly what must not reach the
        # prelude, and intersecting here would let it in bound to nothing.
        return frozenset(
            f"{table.db}.{table.name}"
            for table in sqlglot.parse_one(body, read=DIALECT).find_all(exp.Table)
            if table.db
        )

    needs = {relation: reads(body) for relation, body in sources.items()}
    ordered: list[str] = []
    while True:
        # A CTE may only reference one declared before it, so the prelude is
        # assembled in waves: everything whose sources are already standing.
        ready = sorted(r for r in sources if r not in ordered and needs[r] <= set(ordered))
        if not ready:
            break
        ordered.extend(ready)

    def bind(statement: str) -> str:
        return _rebind(
            statement,
            lambda namespace, name: flattened.get(f"{namespace}.{name}"),
            where="an inline CTE",
        )

    prelude = ",\n".join(
        f"{flattened[relation]} AS (\n{bind(sources[relation])}\n)" for relation in ordered
    )
    body = bind(sql).lstrip()
    if body[:5].upper() == "WITH ":
        # A statement that opens its own `WITH` joins the prelude's list rather
        # than nesting under it: two `WITH` keywords in a row is a syntax error.
        return f"WITH {prelude},\n{body[5:]}"
    return f"WITH {prelude}\n{body}"
