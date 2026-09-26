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

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

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


def qualify(sql: str, dataset: LiveDataset) -> tuple[str, frozenset[str]]:
    """The emitted SQL with its relations pointed at the dedicated dataset, and
    the flattened names it reads.

    The rewrite is textual over the table references SQLGlot *finds*, never a
    re-render of the parse: what this lane submits has to be bloomery's own
    rendering, and a statement that went out through SQLGlot's generator would
    be validating the round trip instead of the port.

    A reference with no namespace is a CTE — bloomery emits no bare relation —
    so it is left alone.

    An unexpanded SQLMesh macro is refused rather than submitted: it stands
    where a relation goes, so BigQuery would reject it and the diagnostic would
    read as a port failure.
    """
    unexpanded = _MACRO.findall(_LITERAL.sub("''", sql))
    assert not unexpanded, (
        f"unexpanded SQLMesh macro reached the dry run: {', '.join(sorted(set(unexpanded)))}. "
        f"The engine expands these at run time and this lane has no engine — bind them before "
        f"submitting, or BigQuery's refusal reports the harness as a port defect."
    )

    relations: set[str] = set()
    for table in sqlglot.parse_one(sql, read=DIALECT).find_all(exp.Table):
        if not table.db:
            continue
        relation = dataset.relation(table.db, table.name)
        if relation in relations:
            # `str.replace` rewrote every occurrence the first time round.
            continue
        relations.add(relation)
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
        # A spelling this does not find is counted as read and left pointing at
        # a dataset that does not exist — a silent no-op whose symptom arrives
        # as BigQuery refusing a name the port never wrote.
        assert occurrence.search(sql), (
            f"{written} is not how this statement spells {table.db}.{table.name}, so the "
            f"rewrite to {dataset} would silently do nothing"
        )
        sql = occurrence.sub(lambda _match: dataset.path(relation), sql)
    return sql, frozenset(relations)


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
