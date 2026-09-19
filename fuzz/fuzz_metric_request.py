"""The planner target: a fuzzed `MetricRequest` against one fixed, valid IR
(S-0008, phase 5).

Every other target in the lane fuzzes a *spec* and watches the compile
boundary. This one holds the spec still — the fixture set, loaded and built
once at startup — and fuzzes the **request**, which is the other half of what
bloomery accepts from outside and the half a Query Agent emits thousands of
times a second (S-0028/D-1).

A request made of random words reaches "unknown metric" and stops there, so
names are drawn **half from a known-good pool** taken from the IR itself: a
mask bit per name position decides between the word the input spells and the
metric or dimension at that position in the pool. Both halves matter — the
fuzzed half is the refusal surface, the pooled half is what gets past coverage
into naming, filters, MetricFlow delegation and the explanation.

The oracle is two claims. The first is the lane's: nothing outside
`_harness.EXPECTED` crosses the planner, and a refusal is named (never the bare
`BloomeryError`, which tells a caller nothing to fix) and renders. The second
is this target's own: **a plan that rendered SQL and carries an empty or
crashing `Explanation` is a defect**, not a degraded answer. The explanation is
user-facing and generated deterministically from the plan rather than by an LLM
(S-0028/D-8), so there is no input for which "SQL, but nothing to say about it"
is the correct output — `render()` is called on every plan, and a plan whose
measures are empty or whose rendering is blank is reported.

The dialect is fixed to duckdb: dialect breadth is `fuzz_cross_dialect.py`'s,
and repeating it here would multiply executions without adding a door.

Input layout — five NUL-separated words from the front, six control bytes from
the back (``ConsumeIntInRange`` reads from the back, so the control bytes are
consumed first and a seed carries them as its tail: one byte of time grain,
two of limit, two of name mask, one of row policy)::

    metrics \0 dimensions \0 filters \0 sort \0 policy-value

``metrics`` and ``dimensions`` are comma-separated names. ``filters`` is
comma-separated ``dimension:$op:value`` terms, where a value containing ``|``
is the list the multi-value operators take; the terms become one filter
document through the public `parse_filter_json` door rather than through
constructed `Predicate` objects, since the lane stays the text layer
(S-0008/D-5). ``sort`` is comma-separated ``field:direction``. A tail of NULs
means: no time grain, every name as the input spells it, no row policy.

Run it through the lane rather than directly::

    just fuzz metric_request 60

**Its own known-catchable defect** — for the sabotage check the lane owes every
target (S-0008/D-9) — is injected, because the oracle is about an output this
planner has never been observed to get wrong. Drop the measures from the
explanation `src/bloomery/planner/explain.py` builds::

    # in build(), the returned Explanation
    measures=(),

and replay any seed that plans::

    just fuzz-repro metric_request fuzz/fuzz_metric_request_seed_corpus/two-metrics-by-month

The SQL still renders and the fingerprint is unchanged — which is the point:
the sabotage is invisible to every other target in the lane, and this one
reports it as "SQL with an explanation describing no measure". A confirmed
finding from a real run becomes a checked-in test under
`tests/unit/test_planner/` rather than a corpus entry (S-0008/D-4).
"""

from __future__ import annotations

import sys

import atheris

with atheris.instrument_imports():
    import _harness

    from bloomery import (
        MetricFlowPlanner,
        MetricRequest,
        Op,
        RowPolicy,
        TimeGrain,
        build_project_ir,
        load_catalog,
        load_project,
    )
    from bloomery.errors import BloomeryError
    from bloomery.naming import DefaultNaming
    from bloomery.planner import parse_filter_json, parse_sort_json
    from bloomery.runtime import LruManifestHydrator

#: The spec, held still. Built once: it is the same project for every
#: execution, and rebuilding it per input would spend the whole time budget in
#: the loader this target is not about.
IR = build_project_ir(load_project(_harness.documents()), load_catalog(_harness.catalog_text()))

#: The known-good pools, read from the IR rather than written out, so a fixture
#: that grows a metric or a date role widens what the mask can draw without an
#: edit here — and a fixture that loses one cannot leave the pool naming
#: something the planner refuses on every execution.
METRICS: tuple[str, ...] = tuple(sorted(metric.name for metric in IR.metrics))
DIMENSIONS: tuple[str, ...] = tuple(
    sorted({dimension.column for mart in IR.marts for dimension in mart.dimensions})
)

#: One planner over one hydrator, shared: `plan` holds no state between calls
#: (S-0028/D-1), and a fresh hydrator per execution would re-hydrate the
#: manifest — ~10 ms, against a target that wants thousands of executions.
PLANNER = MetricFlowPlanner(LruManifestHydrator(DefaultNaming()))

#: Fixed — see the module docstring.
DIALECT = "duckdb"

#: `None` first, so a zero control byte means "no grain asked for".
GRAINS: tuple[TimeGrain | None, ...] = (None, *TimeGrain)

#: Above the planner's default `max_limit` of 50_000, so the clamping warning
#: is reachable; `-1` is the request's `None`, and `0` is its refusal.
MAX_LIMIT = 60_000

SEPARATOR = "\x00"

#: metrics, dimensions, filters, sort, policy value.
WORDS = 5

#: Where each name list reads its mask bits from. Sixteen bits over four
#: lists: past the fourth name of a list the bits repeat, which costs a long
#: request some of the pool and nothing else.
METRIC_BITS, DIMENSION_BITS, FILTER_BITS, SORT_BITS = 0, 4, 8, 12


def _pooled(word: str, pool: tuple[str, ...], index: int, mask: int, shift: int) -> str:
    """The word as spelled, or the pool name at that position when the mask
    bit for it is set — the half-and-half that gets past "no such metric"."""
    return pool[index % len(pool)] if (mask >> (shift + index)) & 1 else word


def _names(field: str, pool: tuple[str, ...], mask: int, shift: int) -> tuple[str, ...]:
    """One comma-separated name list, each name pooled or not."""
    return tuple(
        _pooled(word, pool, index, mask, shift)
        for index, word in enumerate(word for word in field.split(",") if word)
    )


def _filter_document(field: str, mask: int) -> dict[str, object]:
    """The filter terms as one Mongo-flavoured document for `parse_filter_json`.

    A term the input does not spell as `dimension:$op:value` is dropped rather
    than passed on: the malformed-document arm belongs to the CLI target, which
    fuzzes `--where` as text, and what this one wants from its bytes is a
    document that reaches the typed filter path.
    """
    document: dict[str, object] = {}

    for index, term in enumerate(field.split(",")):
        dimension, _, rest = term.partition(":")
        op, _, value = rest.partition(":")
        if not dimension or not op:
            continue
        document[_pooled(dimension, DIMENSIONS, index, mask, FILTER_BITS)] = {
            op: value.split("|") if "|" in value else value
        }

    return document


def _sort_document(field: str, pool: tuple[str, ...], mask: int) -> dict[str, object]:
    """The sort terms as one document for `parse_sort_json`.

    The pool here is the request's own members, because that is what an order
    term is allowed to name (S-0028/D-4) — pooling against the IR instead would
    spend most executions on the same `InvalidRequest`.
    """
    document: dict[str, object] = {}

    for index, term in enumerate(field.split(",")):
        name, _, direction = term.partition(":")
        if not name:
            continue
        document[_pooled(name, pool, index, mask, SORT_BITS)] = direction or "asc"

    return document


def _words(fdp: atheris.FuzzedDataProvider) -> list[str]:
    """The buffer's front as :data:`WORDS` words, short input padded.

    Padded rather than indexed defensively at each use: a truncating mutation
    is the common case, and a target that returned early on one would stop
    fuzzing the slots behind it.
    """
    raw = fdp.ConsumeBytes(fdp.remaining_bytes()).decode("utf-8", "replace")
    words = raw.split(SEPARATOR)

    return [*words, *[""] * (WORDS - len(words))]


def build_request(
    words: list[str], *, grain: TimeGrain | None, limit: int, mask: int
) -> MetricRequest:
    """The fuzzed request. Raises the refusals `MetricRequest` and the parse
    doors raise — every one of them a `BloomeryError`."""
    # An empty metric list is `InvalidRequest` on every execution that spells
    # no name, and `tests/unit/test_planner/test_request.py` already holds that
    # boundary — one pool metric keeps those executions reaching the planner.
    metrics = _names(words[0], METRICS, mask, METRIC_BITS) or (METRICS[0],)
    dimensions = _names(words[1], DIMENSIONS, mask, DIMENSION_BITS)
    # An empty document is itself `InvalidRequest` at both doors, so passing
    # one would make "this input spells no filter" indistinguishable from a
    # filter the parser refused — and no execution would reach the planner.
    filters = _filter_document(words[2], mask)
    sort = _sort_document(words[3], (*metrics, *dimensions), mask)

    return MetricRequest(
        metrics=metrics,
        dimensions=dimensions,
        filters=parse_filter_json(filters) if filters else (),
        time_grain=grain,
        order_by=parse_sort_json(sort) if sort else (),
        limit=None if limit < 0 else limit,
    )


def plan_or_refuse(request: MetricRequest, policy: RowPolicy | None) -> None:
    """Plan one request, and read the plan.

    The oracle is implemented by *not catching* the wrong things — atheris
    reports an uncaught exception by itself — plus the assertions about what a
    plan that did come back carries.
    """
    try:
        plan = PLANNER.plan(IR, request, dialect=DIALECT, policy=policy)
    except _harness.EXPECTED as exc:
        _harness.check_refusal(exc)
        # `BloomeryError` itself names no reason: a caller can tell that the
        # request was refused and nothing about what to change, and every
        # planner refusal has a class of its own
        # (`pages/docs/reference/errors.md`).
        assert type(exc) is not BloomeryError, f"refused with no named reason: {exc}"
        return

    # Called before the assertions rather than inside one: a `render()` that
    # raises is the "crashing explanation" half of the claim, and it escapes.
    rendered = plan.explanation.render()

    assert plan.sql.strip(), f"a plan carrying no SQL: {request}"
    assert plan.explanation.measures, f"SQL with an explanation describing no measure: {request}"
    assert rendered.strip(), f"SQL with an explanation that renders empty: {request}"


def one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    grain = GRAINS[fdp.ConsumeIntInRange(0, len(GRAINS) - 1)]
    limit = fdp.ConsumeIntInRange(-1, MAX_LIMIT)
    mask = fdp.ConsumeIntInRange(0, 2**16 - 1)
    with_policy = fdp.ConsumeIntInRange(0, 1)
    words = _words(fdp)

    try:
        request = build_request(words, grain=grain, limit=limit, mask=mask)
        policy = (
            RowPolicy(
                dimension=request.dimensions[0] if request.dimensions else DIMENSIONS[0],
                op=Op.EQ,
                value=words[4],
            )
            if with_policy
            else None
        )
    except _harness.EXPECTED as exc:
        _harness.check_refusal(exc)
        return

    plan_or_refuse(request, policy)


def _check_pool() -> None:
    """The pooled halves, on their own, plan.

    A pool that stopped planning — a fixture whose marts no longer serve its
    metrics, a date role renamed — makes every execution refuse at coverage, so
    the target would fuzz the request validator, reach no explanation, and stay
    green forever: the dominant failure mode of a fuzzing setup. A drifted
    fixture is a loud failure here rather than a quiet one out there.
    """
    if not METRICS or not DIMENSIONS:
        raise SystemExit("fuzz/fixtures names no metric or no dimension: this target fuzzes nothing")

    request = MetricRequest(metrics=METRICS, dimensions=(DIMENSIONS[0],))
    plan = PLANNER.plan(IR, request, dialect=DIALECT)

    # Reach only. What the plan *carries* is the oracle's to judge, and a
    # startup check that judged it too would answer a finding with a
    # `SystemExit` naming the fixtures instead of the assertion naming the
    # request.
    if not plan.sql.strip():
        msg = f"the pooled request {request} does not plan: this target fuzzes nothing"
        raise SystemExit(msg)


if __name__ == "__main__":
    _check_pool()
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()
