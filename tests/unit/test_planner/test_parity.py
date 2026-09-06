"""The parity suite RFC 0040 §8 calls load-bearing.

Every phase of RFC 0040 re-expresses or extends planning, and the one property
that must survive each is that **a request refused before is refused after**,
except where a named proof rule deliberately converts a class. P1 goes further
and changes nothing at all: D5 makes it a re-expression with no capability
change, precisely so that this suite has a fixed reference point to measure the
later phases against.

What it pins is the **outcome and the exception class, never the wording**
(D8, see logs/T-0021.md D-119). §8 asks that a request "is still refused", which
is a claim about outcome; freezing text as well would pin `UnreachableAtGrain`'s
message, which §9 already calls worse than a refutation — and a suite that goes
red when a message improves is one people learn to update without reading.

**What the corpus actually covers**, since a parity run reports green either way
and the number of requests is not the same as the number of shapes:

* Ten fixtures carry marts with measures. Requests are generated per mart —
  each measure alone, each measure by each dimension, and three two-dimension
  pairs — which is 531 requests.
* 423 are accepted and 108 refused across four classes, so both sides are real.
* **76 of the 108 are one fixture**, `multi_source_quality`, whose catalog
  declares no `date_dimension` — MetricFlow refuses the whole project, so those
  requests fail identically and test one fact repeatedly rather than 76. The
  refusals that vary by request shape are the other 32: `InvalidRequest` (22),
  `AmbiguousDimension` (7) and `UnknownMember` (3).

That last bullet is the honest limit of this suite and the reason it is written
down here: it is a strong guard against a phase that changes an *outcome*, and
a weak one against a phase that changes only refusal *reasons*, which no
current fixture varies enough to catch.

`parity_baseline.tsv` beside this file is the reference, generated on the
merge base rather than on this branch — a baseline recomputed from the tree it
is asserting about compares a run with itself and passes whatever that tree
does.
"""

from __future__ import annotations

import itertools
import pathlib
from collections import Counter

import pytest
from bloomery import MetricRequest
from bloomery.ir import ProjectIR
from support.compiling import spec_fixture_names
from support.planning import fixture_ir, make_planner

pytestmark = pytest.mark.unit

#: Fixtures whose IR does not build, named rather than skipped by catching.
#: A broad `except: continue` around the build would turn a resolver regression
#: into a smaller corpus that still reports green — and a floor like "at least
#: 500 requests" cannot tell 531 from 455. Two refuse on purpose (they exist to
#: be refused) and two need a step registry this suite does not wire.
UNBUILDABLE = frozenset(
    {
        "fanout_trap",  # GuardrailError, deliberately — it is the fan-out trap
        "scd2_mart_refusal",  # GuardrailError, deliberately
        "identity_resolution",  # UnknownStep: needs `registry_for`
        "step_resolution",  # UnknownStep: needs `registry_for`
    }
)

#: How many two-dimension pairs to take per measure. Two dimensions is where a
#: grouping can start to disagree with a measure's grain; three pairs is enough
#: to reach that shape without making the suite quadratic in a mart's width.
_PAIRS = 3


def _requests(ir: ProjectIR) -> list[tuple[str, str, tuple[str, ...]]]:
    """Every request shape this corpus asks, in a deterministic order, each
    carrying the mart it was generated from.

    Sorted throughout rather than taken in IR order: the suite compares two
    runs, and a corpus whose membership depended on iteration order would
    report a difference that was its own.
    """
    shapes: list[tuple[str, str, tuple[str, ...]]] = []

    for mart in sorted(ir.marts, key=lambda m: m.name):
        dimensions = sorted({dimension.ref.dimension for dimension in mart.dimensions})
        for measure in sorted(mart.measures):
            shapes.append((mart.name, measure, ()))
            shapes.extend((mart.name, measure, (dimension,)) for dimension in dimensions)
            shapes.extend(
                (mart.name, measure, pair)
                for pair in itertools.islice(itertools.combinations(dimensions, 2), _PAIRS)
            )

    return shapes


def _outcomes() -> dict[str, str]:
    """Each request's outcome: ``accepted``, or the refusal's class name.

    The class and not the message (D8). Planning is pure and costs single-digit
    milliseconds, so the whole corpus runs end to end through `plan` rather
    than against the coverage precheck alone — a parity suite that stopped at
    the precheck would not see a phase that moved a refusal past it.

    The key names the mart. A measure may be embedded in two marts, and a key
    without it would let one request overwrite the other — quietly, since the
    corpus is the thing being counted (logs/T-0021.md, D-126).
    """
    planner = make_planner()
    results: dict[str, str] = {}

    for name in sorted(spec_fixture_names()):
        if name in UNBUILDABLE:
            continue

        ir = fixture_ir(name)
        if not any(mart.measures for mart in ir.marts):
            continue

        for mart, measure, dimensions in _requests(ir):
            request = MetricRequest(metrics=(measure,), dimensions=dimensions)
            try:
                planner.plan(ir, request, dialect="duckdb")
                outcome = "accepted"
            except Exception as error:  # noqa: BLE001 — the class *is* the assertion
                outcome = type(error).__name__

            results[f"{name}|{mart}|{measure}|{','.join(dimensions)}"] = outcome

    return results


#: The outcome of every request in the corpus, one `key<TAB>outcome` line per
#: request, sorted. Checked in rather than recomputed: totals alone cannot see
#: a phase that refuses one request and starts accepting another, and that
#: trade is exactly the shape a rollup rule change makes (logs/T-0021.md,
#: D-126). A later phase that converts a class regenerates this file, and the
#: diff names every request it moved.
#:
#: Regenerate with:
#:     uv run python -c "import sys; sys.path.insert(0, 'tests'); \
#:         from unit.test_planner.test_parity import write_baseline; write_baseline()"
BASELINE_PATH = pathlib.Path(__file__).with_name("parity_baseline.tsv")


def _baseline() -> dict[str, str]:
    return dict(
        line.split("\t", 1)
        for line in BASELINE_PATH.read_text(encoding="utf-8").splitlines()
        if line
    )


def write_baseline() -> None:  # pragma: no cover — the regeneration entry point
    outcomes = _outcomes()
    BASELINE_PATH.write_text(
        "".join(f"{key}\t{outcome}\n" for key, outcome in sorted(outcomes.items())),
        encoding="utf-8",
    )


def test_the_corpus_is_the_size_it_claims_to_be() -> None:
    """A parity run is green whether it replayed 531 requests or none, so the
    size is asserted rather than reported. Found worth pinning because the
    generator reads fixtures: one that stops carrying marts shrinks the corpus
    silently, and the suite keeps passing on what is left."""
    outcomes = _outcomes()

    assert len(outcomes) == len(_baseline())
    assert len(outcomes) == 531


def test_no_request_changes_outcome() -> None:
    """RFC 0040 §8, and D5's whole reason for existing: P1 re-expresses today's
    planning as a `SemanticPlan` and every request keeps the answer it had.

    Per request, not per class. Comparing `Counter`s over the outcomes lets a
    phase refuse one request and start accepting another with every total
    preserved — a parity suite that reports green on a swapped pair is
    measuring arithmetic, not parity.
    """
    outcomes = _outcomes()
    baseline = _baseline()
    changed = {
        key: (baseline.get(key), outcome)
        for key, outcome in outcomes.items()
        if baseline.get(key) != outcome
    }
    dropped = sorted(set(baseline) - set(outcomes))

    assert changed == {}, f"outcome changed for {len(changed)} request(s): {changed}"
    assert dropped == [], f"request(s) no longer in the corpus: {dropped}"


def test_both_sides_of_the_boundary_are_exercised() -> None:
    """The guard against a corpus that drifted to all-accepted or all-refused.

    Either would keep both tests above green while measuring one half of the
    behaviour — and a parity suite that only ever sees acceptances cannot fail
    when a phase starts refusing things it should not.
    """
    outcomes = _outcomes()
    counts = Counter(outcomes.values())

    assert counts["accepted"] > 100
    assert sum(count for name, count in counts.items() if name != "accepted") > 100
    # More than one *kind* of refusal, since 76 of them are one fixture's whole
    # project failing for a reason that has nothing to do with request shape.
    assert len([name for name in counts if name != "accepted"]) >= 4
