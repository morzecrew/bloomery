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

* Eleven fixtures carry marts with measures. Requests are generated per mart —
  each measure alone, each measure by each dimension, three two-dimension
  pairs, and each measure by every dimension *another* mart of the same project
  flattens — which is 700 requests.
* 448 are accepted and 252 refused across five classes, so both sides are real.
* **76 of the refusals are one fixture**, `multi_source_quality`, whose catalog
  declares no `date_dimension` — MetricFlow refuses the whole project, so those
  requests fail identically and test one fact repeatedly rather than 76.

**The cross-mart requests were added by RFC 0040 P2's self-audit**
(logs/T-0022.md, finding 1). Without them this suite could not observe the only
behaviour that phase changed: it converts a dimension refusal from
`UnknownMember` to `UnreachableAtGrain`, and every request the generator asked
for named a dimension of the mart serving it, so not one could reach the
conversion. A load-bearing parity suite blind to the phase it is guarding is
worth more as a finding than as a pass.

Two things about the baseline follow:

* The 129 conversions are **licensed and visible** — generated on the merge
  base, where those requests refuse as `UnknownMember`, so the change is a diff
  a reviewer reads rather than a number that moved.
  `test_only_the_licensed_conversion_moved` makes it a rule instead of a list:
  any *other* movement fails, a newly accepted request included.
* The 40 rows for `unflattened_hop` record a **first** value, not a preserved
  one — that fixture does not exist at the merge base (D-136), so there is
  nothing they could have moved from.

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
        # Columns another mart of this project flattens and this one does not.
        # `ref.dimension` above is the requestable name; a foreign column is
        # asked for by the name it is flattened under, which is what a caller
        # reading the other mart would type.
        foreign = sorted(
            {dimension.column for other in ir.marts for dimension in other.dimensions}
            - {dimension.column for dimension in mart.dimensions}
        )
        for measure in sorted(mart.measures):
            shapes.append((mart.name, measure, ()))
            shapes.extend((mart.name, measure, (dimension,)) for dimension in dimensions)
            shapes.extend(
                (mart.name, measure, pair)
                for pair in itertools.islice(itertools.combinations(dimensions, 2), _PAIRS)
            )
            shapes.extend((mart.name, measure, (dimension,)) for dimension in foreign)

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
#: D-126). A phase that converts a class regenerates this file **on the merge
#: base** and the diff names every request it moved — which is what RFC 0040
#: D11 asks for, and what this file records for P2.
#:
#: Regenerate with:
#:     uv run python -c "import sys; sys.path.insert(0, 'tests'); \
#:         from unit.test_planner.test_parity import write_baseline; write_baseline()"
#: in a worktree of the merge base, never on the branch under test.
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
    assert len(outcomes) == 700


#: The one conversion RFC 0040 P2 licenses: a request naming a dimension another
#: mart carries stops being reported as a name that does not exist. A pair
#: rather than a list of the 129 keys, because the rule is what the phase
#: claims — a list would also pass for a phase that converted some other
#: request and un-converted one of these.
CONVERSION = ("UnknownMember", "UnreachableAtGrain")

#: How many requests it moved. Pinned because "no unlicensed change" is equally
#: true of a phase that converts nothing at all.
CONVERTED = 129


def _unlicensed(
    outcomes: dict[str, str], baseline: dict[str, str]
) -> dict[str, tuple[str, str]]:
    """Every request whose outcome moved in a way this phase does not license.

    Extracted from the test below rather than inlined, so the rule can be shown
    to reject something. Inline, nothing created a violating move, and replacing
    the whole computation with `{}` left the suite green — the assertion that
    carries the guarantee was the one thing unexercised (logs/T-0022.md,
    finding 2).
    """
    return {
        key: move
        for key, outcome in outcomes.items()
        if key in baseline
        and (move := (baseline[key], outcome))[0] != move[1]
        and move != CONVERSION
    }


def test_the_conversion_rule_rejects_any_other_move() -> None:
    """The rule, against moves the corpus does not contain: a refusal becoming
    an acceptance, a different pair of classes, and the licensed pair *run
    backwards*. Green on any of them would mean the check below asserts less
    than it says.

    The reverse move earns its line: comparing the pair as a set instead of in
    order licenses a phase that starts reporting a dimension another mart
    carries as a name that does not exist, which is this change undone.
    """
    baseline = {
        "a": "UnknownMember",
        "b": "InvalidRequest",
        "c": "UnknownMember",
        "d": "UnreachableAtGrain",
    }
    outcomes = {
        "a": "UnreachableAtGrain",
        "b": "accepted",
        "c": "AmbiguousDimension",
        "d": "UnknownMember",
    }

    assert _unlicensed(outcomes, baseline) == {
        "b": ("InvalidRequest", "accepted"),
        "c": ("UnknownMember", "AmbiguousDimension"),
        "d": ("UnreachableAtGrain", "UnknownMember"),
    }


def test_only_the_licensed_conversion_moved() -> None:
    """RFC 0040 §8, and D11: a phase preserves prior refusals except where a
    named proof rule deliberately converts a class, and a conversion — of
    outcome *or* of exception class — edits this baseline and says which rule
    did it.

    Per request, not per class. Comparing `Counter`s over the outcomes lets a
    phase refuse one request and start accepting another with every total
    preserved — a parity suite that reports green on a swapped pair is
    measuring arithmetic, not parity.
    """
    outcomes = _outcomes()
    baseline = _baseline()
    changed = {
        key: (baseline[key], outcome)
        for key, outcome in outcomes.items()
        if key in baseline and baseline[key] != outcome
    }
    unlicensed = _unlicensed(outcomes, baseline)
    dropped = sorted(set(baseline) - set(outcomes))

    assert unlicensed == {}, f"unlicensed outcome change(s): {unlicensed}"
    assert len(changed) == CONVERTED, f"{len(changed)} converted, expected {CONVERTED}"
    assert dropped == [], f"request(s) no longer in the corpus: {dropped}"


def test_nothing_the_planner_refused_became_answerable() -> None:
    """The half of §8 a licensed conversion must not quietly carry with it. P2
    adds no capability (D9), so a request refused before is refused after — the
    class it is refused with is the only thing that moved.
    """
    outcomes = _outcomes()
    baseline = _baseline()
    widened = sorted(
        key
        for key, outcome in outcomes.items()
        if key in baseline and baseline[key] != "accepted" and outcome == "accepted"
    )

    assert widened == [], f"request(s) newly accepted: {widened}"


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
