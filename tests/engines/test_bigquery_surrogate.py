"""Rung 4 on BigQuery (S-0012/the-ladder): the surrogate lane.

`goccy/bigquery-emulator` is a GoogleSQL analyzer over an embedded SQLite, and
what a green run here proves is that *the emulator* accepted and executed what
the port rendered. It is evidence and never the oracle (S-0012/D-1): the
authoritative rung is the dry run in :mod:`tests.engines.test_bigquery_live`,
where BigQuery's own compiler answers. So the claim is kept out of this module's
name and out of its marker — ``surrogate("bigquery_emulator")``, never
``engine("bigquery")`` (S-0012/D-2, S-0014/D-3) — because a CI log six months
from now is read at the level of a test name and, usually, nothing below it.

Pinned to an exact tag and never `latest` (S-0014/D-3): a lane whose engine
version can change under it cannot tell a regression from an upgrade.

**Nothing is provisioned.** Every statement runs over inline literal CTEs
(:func:`support.bigquery.inlined`), the mechanism the live execution lane uses
because its identity may not create tables — here it means the lane is a
container and one POST per query, with no dataset to seed, no DDL and no build
order. The request bodies are the live lane's own :func:`support.bigquery.execute`
with the endpoint repointed, so two lanes disagreeing means the two *engines*
disagree rather than the two harnesses.

What runs: the dirty corpus's generated SELECTs and its reject tables — the
quarantine queries, the `regexp` rules, `SAFE_CAST`, the array-valued flags —
and `ecom_basic`'s silver models and gold mart, which is where the JSON
extraction, the mart join, the date roles and the generated calendar are.

Needs Docker, which a sandbox does not have, so its acceptance is collection and
the lane itself is proven where Docker exists. **It had not run against a daemon
when it was written** (T-0093): the tag, the flags and the endpoint are read from
v0.8.1's own source rather than observed, so the first run on a Docker host is
this lane's bring-up, and a refusal there is as likely to be the harness as the
port.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import PurePosixPath

import pytest
from sqlglot import exp
from testcontainers.core.container import DockerContainer

from bloomery.dialects import get_dialect
from bloomery.emit import ArtifactKind
from bloomery.ir.lower import canon as lower_canon
from bloomery.transforms import DEFAULT_REGISTRY
from engines.test_bigquery_live import DIRTY_ENTITIES, DIRTY_SEEDS, dirty_sources, dispositions
from support.bigquery import LiveDataset, execute, inlined
from support.compiling import compile_fixture, extract_select
from support.dirty import (
    DIALECT_DIVERGENT,
    FLAGGED,
    KEPT,
    QUARANTINED,
    cases,
    corpus,
    expected,
)

pytestmark = pytest.mark.surrogate("bigquery_emulator")

#: Exact, and never a moving alias (S-0014/D-3). `0.8` and `latest` are both
#: published for this image and neither is a lane: a tier whose engine version
#: changes under it reports an upgrade as a regression, or worse, the reverse.
IMAGE = "ghcr.io/goccy/bigquery-emulator:0.8.1"

#: The emulator creates exactly the project and dataset it is told to on start,
#: and `support.bigquery` sends `defaultDataset` on every query — so the dataset
#: has to exist even though every statement here reads CTEs and resolves no name
#: in it.
PROJECT = "bloomery-surrogate"
DATASET = "surrogate"
HTTP_PORT = 9050

#: Container start plus the first GoogleSQL analysis, which is the slow one.
READY_TIMEOUT_SECONDS = 60.0

#: `ecom_basic`'s bronze, as the two inline relations its silver models read.
#: The rows are `tests/engines/test_trino_execution.py:43` verbatim, so a
#: disagreement between this rung and the engine matrix is legible as a diff
#: rather than as two lanes seeded differently.
#:
#: Typed, unlike the dirty corpus's all-varchar bronze: `order_item` renders
#: `CAST(total / qty AS NUMERIC)`, an arithmetic on the column rather than on a
#: cast of it, so a STRING source would fail analysis for a reason that is this
#: harness's and would read as the port's.
ECOM_FIXTURE = "ecom_basic"
ECOM_BRONZE = {
    "bronze.shopify__order_lines": """
        SELECT 'o1' AS order_id, 1 AS index, NUMERIC '100.000' AS total, 10 AS qty,
               '2024-01-02T03:04:05' AS created_at
        UNION ALL SELECT 'o1', 2, NUMERIC '59.976', 3, '2024-01-02T04:00:00'
        UNION ALL SELECT 'o2', 1, NUMERIC '20.000', 2, '2024-02-05T10:00:00'
    """,
    "bronze.shopify__orders": """
        SELECT 'o1' AS id, '{"id": "c1"}' AS customer
        UNION ALL SELECT 'o2', '{"id": "c2"}'
    """,
}


def ecom_sources() -> dict[str, str]:
    """``namespace.relation`` → the SELECT that stands for it, for :func:`inlined`.

    The bronze relations are :data:`ECOM_BRONZE`; the silver and gold ones are
    the emitted model bodies, unedited — which is what makes the mart cases below
    assertions about what the port rendered rather than about SQL written here.
    """
    sources = dict(ECOM_BRONZE)
    for artifact in compile_fixture(ECOM_FIXTURE, dialect="bigquery"):
        if artifact.kind is not ArtifactKind.MODEL or not artifact.path.endswith(".sql"):
            continue
        path = PurePosixPath(artifact.path)
        sources[f"{path.parent.name}.{path.stem}"] = extract_select(artifact.content)
    return sources


def _ready(dataset: LiveDataset) -> LiveDataset:
    """Block until the emulator answers a query, or fail saying it never did.

    A log line would be the cheaper wait and a weaker one. This asks the question
    the rest of the module rests on — that the harness's own request reaches this
    backend and comes back decoded — so a wrong endpoint, flag or tag fails here
    once, with the emulator's own words, instead of as every case below.
    """
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while True:
        try:
            assert execute(dataset, "SELECT 1") == [(1,)]
            return dataset
        except (OSError, AssertionError) as refusal:
            if time.monotonic() > deadline:
                raise AssertionError(
                    f"{IMAGE} did not answer a query within {READY_TIMEOUT_SECONDS:.0f}s, "
                    f"so nothing below it would be testing the port: {refusal}"
                ) from refusal
            time.sleep(0.5)


@pytest.fixture(scope="module")
def emulator() -> Iterator[LiveDataset]:
    """The pinned emulator, with the live harness pointed at it.

    The endpoint is patched rather than passed, because what this lane must send
    is the live lane's request and not a second rendering of it: one
    `maximumBytesBilled`, one `useQueryCache`, one typed row decoder. The token
    is empty — the emulator ignores `Authorization`, which is the property that
    makes this the only BigQuery lane a fork's pull request could run.
    """
    container = (
        DockerContainer(IMAGE)
        .with_exposed_ports(HTTP_PORT)
        .with_command(f"--project={PROJECT} --dataset={DATASET} --port={HTTP_PORT}")
    )
    with container, pytest.MonkeyPatch.context() as patch:
        host = container.get_container_host_ip()
        endpoint = f"http://{host}:{container.get_exposed_port(HTTP_PORT)}"
        # v0.8.1 routes every handler at both its bare path and under
        # `/bigquery/v2` (server/server.go:87-89); the prefixed one is what the
        # REST API documents and what the live harness builds its URLs from.
        patch.setattr("support.bigquery.API", f"{endpoint}/bigquery/v2")
        yield _ready(LiveDataset(project=PROJECT, dataset=DATASET, token=""))


@pytest.fixture(scope="module")
def dirty_run(emulator: LiveDataset) -> Callable[[str], list[tuple[object, ...]]]:
    """Query the dirty corpus's own models over the dirty corpus's own rows."""
    sources = dirty_sources()

    def query(sql: str) -> list[tuple[object, ...]]:
        return execute(emulator, inlined(sql, sources))

    return query


@pytest.fixture(scope="module")
def ecom_run(emulator: LiveDataset) -> Callable[[str], list[tuple[object, ...]]]:
    """Query `ecom_basic`'s models over :data:`ECOM_BRONZE`.

    A prelude of its own rather than one merged with the dirty corpus's: every
    query carries the whole prelude it is given, and a fixture's cases have no
    business analysing thirty relations belonging to the other one.
    """
    sources = ecom_sources()

    def query(sql: str) -> list[tuple[object, ...]]:
        return execute(emulator, inlined(sql, sources))

    return query


@pytest.fixture(scope="module")
def landed(
    dirty_run: Callable[[str], list[tuple[object, ...]]],
) -> dict[str, dict[str, tuple[str, tuple[str, ...]]]]:
    """``{corpus file: {_source_row_id: (disposition, rules)}}``, read once.

    Module-scoped for the reason the live lane gives: it is six queries, and
    every disposition case is an assertion about the same six answers.
    """
    return {name: dispositions(dirty_run, DIRTY_ENTITIES[name]) for name in DIRTY_SEEDS}


def test_this_lane_never_claims_the_engine() -> None:
    """S-0014/D-3 and S-0012/D-2 as a check rather than as a convention.

    Both halves of the row are one edit away from being lost quietly — a marker
    changed to `engine("bigquery")` to make a selector match, a tag floated to
    `0.8` to stop chasing patches — and neither edit fails anything else here.
    The claim a green run may make lives in the marker and in the tag, so this is
    where it is held.
    """
    assert pytestmark.name == "surrogate", (
        f"this lane selects as {pytestmark.name!r}: an emulator-backed lane that reports as the "
        f"engine matrix does says BigQuery passed, which is not what it checked (S-0012/D-2)"
    )
    assert pytestmark.args == ("bigquery_emulator",)
    assert re.fullmatch(r"\S+:\d+\.\d+\.\d+", IMAGE), (
        f"{IMAGE} is not an exact tag; a tier whose engine version can change under it cannot "
        f"tell a regression from an upgrade (S-0014/D-3)"
    )


@pytest.mark.parametrize("name", sorted(DIRTY_SEEDS))
def test_every_corpus_row_lands_on_the_side_the_corpus_says(
    landed: dict[str, dict[str, tuple[str, tuple[str, ...]]]], name: str
) -> None:
    """The generated SELECTs and their reject tables, executed: every specimen's
    disposition against the corpus's own ``_expected`` column.

    The same claim the live execution lane makes and the same one DuckDB answers
    at tier 4, on a third backend — which is what makes a divergence legible as
    one file's one specimen (S-0012/D-6) instead of as a lane that is red.
    """
    case_of = cases(name)
    observed = {
        case_of[row_id]: disposition for row_id, (disposition, _rules) in landed[name].items()
    }
    declared = expected(name)
    # A `dialect_divergent` row's disposition is a property of the engine rather
    # than of the data, and this engine is a surrogate — so the claim over those
    # rows is consistency, never an answer.
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
    dirty_run: Callable[[str], list[tuple[object, ...]]],
) -> None:
    """The quarantine queries, and the conservation law over them: `unicode.csv`'s
    lone-surrogate escape is in the reject table, out of the entity, and counted
    once. A survivors-only assertion cannot tell a quarantine from a row the
    engine dropped on the floor (S-0033 §6).

    The fired rule is asserted too, as an array read back through the REPEATED
    decoding: a row diverted by some *other* rule is a different defect wearing
    the same count.
    """
    quarantined = {
        row_id for row_id, (side, _rules) in landed["unicode.csv"].items() if side == QUARANTINED
    }
    case_of = cases("unicode.csv")
    assert {case_of[row_id] for row_id in quarantined} == {"lone_surrogate_escape"}
    kept = dirty_run("SELECT COUNT(*) FROM silver.dirty_name")[0][0]
    assert kept + len(quarantined) == len(corpus("unicode.csv"))
    assert landed["unicode.csv"][next(iter(quarantined))][1] == ("name_pattern",)


def test_the_reject_payload_is_readable_back_as_json(
    dirty_run: Callable[[str], list[tuple[object, ...]]],
) -> None:
    """``raw`` is what replay re-runs the mapping against and ``key_values`` is
    what a human greps for. Both are JSON the port constructed, and reading them
    back is the only check that it is JSON rather than a string that looks like
    some.
    """
    assert dirty_run(
        "SELECT JSON_EXTRACT_SCALAR(raw, '$.raw_amount'), "
        "JSON_EXTRACT_SCALAR(key_values, '$.case_name') "
        "FROM silver.dirty_number__reject WHERE _source_row_id = 'num_002'"
    ) == [("12,50", "comma_decimal")]


def test_the_silver_model_extracts_its_json_customer(
    ecom_run: Callable[[str], list[tuple[object, ...]]],
) -> None:
    """`ecom_basic`'s `order` model reads its key out of a JSON payload —
    `JSON_EXTRACT_SCALAR(customer, '$.id')` — because that is how bronze arrives.
    The Trino mirror asserts the same two rows
    (`tests/engines/test_trino_execution.py:123`).
    """
    assert ecom_run("SELECT order_id, customer_id FROM silver.`order` ORDER BY order_id") == [
        ("o1", "c1"),
        ("o2", "c2"),
    ]


def test_the_mart_join_and_the_date_roles_run(
    ecom_run: Callable[[str], list[tuple[object, ...]]],
) -> None:
    """The fixture mart: a LEFT JOIN onto a reserved-word relation, and the date
    roles `DATE_TRUNC` renders over a `DATETIME`.

    `order_date` is a bloomery `timestamp`, which this port renders as a
    `DATETIME` and not a `TIMESTAMP` (S-0014/D-1), so truncating it is a wall
    clock operation and the day it lands on is the one the engine matrix already
    asserts (`tests/engines/test_trino_execution.py:128`).
    """
    jan2, jan1 = date(2024, 1, 2), date(2024, 1, 1)
    feb5, feb1 = date(2024, 2, 5), date(2024, 2, 1)
    assert ecom_run(
        "SELECT order_id, line_no, order_customer_id, ordered_day, ordered_month "
        "FROM gold.mart_order_items ORDER BY order_id, line_no"
    ) == [
        ("o1", 1, "c1", jan2, jan1),
        ("o1", 2, "c1", jan2, jan1),
        ("o2", 1, "c2", feb5, feb1),
    ]


def test_the_mart_aggregates_its_decimals(
    ecom_run: Callable[[str], list[tuple[object, ...]]],
) -> None:
    """`unit_price` is `CAST(total / qty AS NUMERIC)` — a declared decimal, which
    S-0014/D-7 is open on — and the sum is where a float would show up as a tail
    of digits nobody declared.
    """
    total = ecom_run("SELECT SUM(unit_price * quantity) FROM gold.mart_order_items")[0][0]
    assert isinstance(total, Decimal), f"{total!r} came back as {type(total).__name__}"
    # 10×10 + 19.992×3 + 10×2 = 179.976, exactly (S-0020 forbids a float here).
    assert total == Decimal("179.976")


def test_the_generated_calendar_runs(ecom_run: Callable[[str], list[tuple[object, ...]]]) -> None:
    """`dim_date` is the array case the corpus already carries: this dialect
    renders its calendar as ``UNNEST(GENERATE_DATE_ARRAY(...))``, a construction
    no offline rung executes and no other engine spells the same way.
    """
    count, first, last = ecom_run(
        "SELECT COUNT(*), MIN(date_day), MAX(date_day) FROM gold.dim_date"
    )[0]
    assert count == 4018  # 2020-01-01 .. 2030-12-31, three leap years
    assert (first, last) == (date(2020, 1, 1), date(2030, 12, 31))


def test_a_rendered_regexp_capture_returns_its_group(emulator: LiveDataset) -> None:
    """`regex_extract`'s capture group, executed over two literals.

    No fixture declares the transform, so the shared corpus has no capture
    specimen and the port's own rendering is executed instead — with the
    non-matching row beside the matching one, because a capture that came back as
    the whole subject, or as an empty string where the pattern does not match, are
    the two ways this goes wrong quietly. The corpus's other regexp surface, the
    `pattern` rule, runs above as `name_pattern`.
    """
    rendered = get_dialect("bigquery").render(
        lower_canon(
            DEFAULT_REGISTRY["regex_extract"].builder(exp.column("raw"), r"^ORD-([0-9]+)$", 1)
        ).ast()
    )
    assert execute(
        emulator,
        f"SELECT raw, {rendered} FROM (SELECT 'ORD-42' AS raw UNION ALL SELECT 'nope') "
        f"ORDER BY raw",
    ) == [("ORD-42", "42"), ("nope", None)]


def test_the_dirty_wall_clock_lands_on_the_exact_instant(
    dirty_run: Callable[[str], list[tuple[object, ...]]],
) -> None:
    """The date and time case the mart cannot make: a parsed wall clock, to the
    second, on both spellings the corpus carries.

    A `timestamp` is zoneless UTC (S-0021) rendered here as a `DATETIME`
    (S-0014/D-1), so `utc_control`'s trailing ``Z`` names the zone the type is
    already in and truncating it loses nothing (S-0052/D-4) — a claim about a
    value, and therefore unmakeable on any rung that does not execute.
    """
    rows = dirty_run(
        "SELECT case_name, observed_at FROM silver.dirty_date "
        "WHERE case_name IN ('iso_control', 'utc_control')"
    )
    assert {str(case): instant for case, instant in rows} == {
        "iso_control": datetime(2025, 12, 31, 0, 0),
        "utc_control": datetime(2025, 12, 30, 21, 0),
    }
