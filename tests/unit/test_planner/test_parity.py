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

* Twelve fixtures carry marts with measures. Requests are generated per mart —
  each measure alone, each measure by each dimension, three two-dimension
  pairs, and each measure by every dimension *another* mart of the same project
  flattens — plus, per pair of measure-carrying marts, one **cross-mart**
  request ungrouped, one by each dimension of the first mart, one **restricted**
  by each of those dimensions, and one per metric whose own components straddle
  the pair. That is 991 requests, 171 of them cross-mart.
* 527 are accepted and 464 refused across five classes, so both sides are real.
* **76 of the refusals are one fixture**, `multi_source_quality`, whose catalog
  declares no `date_dimension` — MetricFlow refuses the whole project, so those
  requests fail identically and test one fact repeatedly rather than 76.

**The generator has been widened three times, each time because it was blind
to the phase it was guarding.** RFC 0040 P2's self-audit added the cross-mart
*dimensions* (logs/T-0022.md, finding 1): every request named a dimension of
the mart serving it, so not one could reach that phase's conversion. RFC 0041
P1 added the cross-mart *requests* — its whole subject is a request whose
measures live on two marts, and the generator asked only single-metric ones
(D-128), so the corpus could not contain a single instance of the shape being
built. RFC 0041 P2 adds the two shapes *it* is about: a cross-mart request
carrying a restriction, and one whose metric is computed above the join. The
widening was written before the code this time rather than after an audit, on
the standing evidence that a suite which cannot reach a change abstained rather
than passed. A load-bearing parity suite blind to the phase it is guarding is
worth more as a finding than as a pass.

Two things about the baseline follow:

* The conversions are **licensed and visible** — the baseline is regenerated on
  the merge base, so a change is a diff a reviewer reads rather than a number
  that moved. `test_only_the_licensed_conversion_moved` makes it a rule instead
  of a list: any *other* movement fails.
* Rows for a fixture that does not exist at the merge base record a **first**
  value, not a preserved one (D-136), so there is nothing they could have moved
  from. Regenerating with the new fixture and the new generator present in a
  worktree of the merge base is what keeps that set as small as possible: it
  buys the *old planner's* answer for a new request, which is the only thing a
  conversion can be measured against.

The honest limit of this suite is written down here rather than discovered: it
is a strong guard against a phase that changes an *outcome*, and a weak one
against a phase that changes only refusal *reasons*, which no current fixture
varies enough to catch.

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
from bloomery import MetricRequest, Op, Predicate
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


def _requests(
    ir: ProjectIR,
) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[Predicate, ...]]]:
    """Every request shape this corpus asks, in a deterministic order, each
    carrying the mart it was generated from and the metrics it asks for.

    Sorted throughout rather than taken in IR order: the suite compares two
    runs, and a corpus whose membership depended on iteration order would
    report a difference that was its own.

    **Single-metric shapes keep their key**, so every row of the checked-in
    baseline still names the same request. The cross-mart pairs added for
    RFC 0041 P1 (D16) key on `a+b` in both the mart and the measure field,
    which no single-metric key can collide with.
    """
    shapes: list[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[Predicate, ...]]] = []

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
            shapes.append((mart.name, measure, (), (measure,), ()))
            shapes.extend(
                (mart.name, measure, (dimension,), (measure,), ()) for dimension in dimensions
            )
            shapes.extend(
                (mart.name, measure, pair, (measure,), ())
                for pair in itertools.islice(itertools.combinations(dimensions, 2), _PAIRS)
            )
            shapes.extend(
                (mart.name, measure, (dimension,), (measure,), ()) for dimension in foreign
            )

    shapes.extend(_cross_mart(ir))

    return shapes


def _leaves(ir: ProjectIR, name: str, seen: set[str] | None = None) -> tuple[str, ...]:
    """The measures a metric ultimately needs, following ratios and derived
    inputs.

    A local walk rather than the planner's, deliberately: this decides only
    **which requests to ask**, so disagreeing with the planner costs a row that
    records a refusal instead of an acceptance — never a wrong assertion. Wiring
    it to the planner's own walk would make the corpus a function of the code
    under test.
    """
    seen = set() if seen is None else seen

    if name in seen:
        return ()

    seen.add(name)
    metric = next((candidate for candidate in ir.metrics if candidate.name == name), None)

    if metric is None:
        return ()

    if metric.derived is not None:
        return tuple(
            leaf for input_ in metric.derived.inputs for leaf in _leaves(ir, input_.metric, seen)
        )

    if metric.ratio is not None:
        return (*_leaves(ir, metric.ratio.numerator, seen), *_leaves(ir, metric.ratio.denominator, seen))

    return (name,)


def _cross_mart(ir: ProjectIR) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[Predicate, ...]]]:
    """One request per pair of measure-carrying marts, ungrouped and then
    grouped by each dimension of the first of the pair.

    **The shape the generator was blind to.** RFC 0040 P2's own conversions
    were invisible until its self-audit added cross-mart *dimensions*; this is
    the same omission one level up, and it is the whole of what RFC 0041 P1
    changes — a request whose measures live on two marts. Without these rows
    the baseline cannot say what the phase converted, and a suite that cannot
    see the phase it guards reports green for it either way (D16).

    The first measure of each mart rather than every combination: what varies
    across a pair is whether the marts share a dimension by provenance, not
    which measure was picked, and the product over measures would grow the
    corpus without asking anything new.
    """
    carrying = [mart for mart in sorted(ir.marts, key=lambda m: m.name) if mart.measures]
    shapes: list[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[Predicate, ...]]] = []

    for left, right in itertools.combinations(carrying, 2):
        metrics = (sorted(left.measures)[0], sorted(right.measures)[0])
        mart = f"{left.name}+{right.name}"
        measure = "+".join(metrics)
        dimensions = sorted({dimension.ref.dimension for dimension in left.dimensions})
        shapes.append((mart, measure, (), metrics, ()))
        shapes.extend(
            (mart, measure, (dimension,), metrics, ()) for dimension in dimensions
        )
        # A **restricted** cross-mart request, which is the half of P2 the
        # generator was blind to for the same reason it was blind to cross-mart
        # requests at all (D16). `is_null` rather than a comparison: it needs no
        # literal, so one shape reaches every column type without the outcome
        # recording a type mismatch instead of a placement.
        shapes.extend(
            (
                mart,
                f"{measure}|not-null:{dimension}",
                (),
                metrics,
                (Predicate(dimension=dimension, op=Op.IS_NULL, values=(False,)),),
            )
            for dimension in dimensions
        )
        # And a metric whose own components straddle this pair — P2's other
        # half, computed above the join rather than by either branch (D3).
        pair = set(left.measures) | set(right.measures)
        shapes.extend(
            (mart, f"{measure}|computed:{metric.name}", (), (metric.name,), ())
            for metric in sorted(ir.metrics, key=lambda m: m.name)
            if (leaves := set(_leaves(ir, metric.name))) != {metric.name}
            if leaves <= pair
            if leaves & set(left.measures)
            if leaves & set(right.measures)
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

        for mart, measure, dimensions, metrics, filters in _requests(ir):
            request = MetricRequest(metrics=metrics, dimensions=dimensions, filters=filters)
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
    """A parity run is green whether it replayed 991 requests or none, so the
    size is asserted rather than reported. Found worth pinning because the
    generator reads fixtures: one that stops carrying marts shrinks the corpus
    silently, and the suite keeps passing on what is left."""
    outcomes = _outcomes()

    assert len(outcomes) == len(_baseline())
    assert len(outcomes) == 991


#: What RFC 0041 P2 licenses, as moves rather than as a list of keys: the rule
#: is what the phase claims, and a list would also pass for a phase that
#: converted some other request and un-converted one of these.
#:
#: Measured against the merge base, which already carries P1 — so P1's own
#: conversions are in the baseline and these are P2's alone. The first pair is
#: the phase: a cross-mart request carrying a **restriction** every branch can
#: evaluate, and one whose metric is **computed above the join**, are answered
#: instead of refused. The second is **not** a capability and is licensed
#: separately for that reason: one request names a column that is a mart
#: dimension to the coverage precheck and a join key to the manifest emitter,
#: so the branch reaches MetricFlow and is refused there. P1 licensed the same
#: move for the grouped form of that request; this is its filtered form, and
#: the underlying divergence is a defect of the mart-to-manifest lowering
#: (logs/T-0026.md, D-170).
CONVERSIONS = {
    ("UnreachableAtGrain", "accepted"): 15,
    ("UnreachableAtGrain", "UnknownMember"): 1,
}

#: How many requests moved in total. Pinned because "no unlicensed change" is
#: equally true of a phase that converts nothing at all.
#:
#: Thirteen of the fifteen are filtered cross-mart requests and two are the
#: computed metrics — a ratio and an authored expression whose components live
#: on different marts (logs/T-0027.md, D-179). Nothing single-mart moves: a
#: filter on one mart was always placeable, and P2 changes only where a
#: restriction has more than one branch to reach.
CONVERTED = 16


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
        and move not in CONVERSIONS
    }


def test_the_conversion_rule_rejects_any_other_move() -> None:
    """The rule, against moves the corpus does not contain: a refusal becoming
    an acceptance, a different pair of classes, and the licensed pair *run
    backwards*. Green on any of them would mean the check below asserts less
    than it says.

    The reverse move earns its line: comparing a pair as a set instead of in
    order licenses a phase that starts *refusing* what it now answers, which
    is this change undone.
    """
    baseline = {
        "a": "UnreachableAtGrain",
        "b": "InvalidRequest",
        "c": "UnknownMember",
        "d": "accepted",
    }
    outcomes = {
        "a": "accepted",
        "b": "accepted",
        "c": "AmbiguousDimension",
        "d": "UnreachableAtGrain",
    }

    assert _unlicensed(outcomes, baseline) == {
        "b": ("InvalidRequest", "accepted"),
        "c": ("UnknownMember", "AmbiguousDimension"),
        "d": ("accepted", "UnreachableAtGrain"),
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


def test_only_cross_mart_requests_became_answerable() -> None:
    """The half of §8 a licensed conversion must not quietly carry with it.

    RFC 0040 P2 added no capability, and this test asserted that nothing
    became answerable at all. RFC 0041 P1 **is** a capability, so the claim
    moves rather than disappearing: what may newly be accepted is a cross-mart
    request and nothing else. A single-mart request that starts being answered
    is a planner that stopped refusing something for a reason this phase never
    names, which is what the empty assertion used to catch and what this one
    catches now.

    Cross-mart requests are the keys the generator writes as `a+b`
    (:func:`_cross_mart`), so "which requests may move" is read off the corpus
    rather than off a list somebody keeps in step by hand.
    """
    outcomes = _outcomes()
    baseline = _baseline()
    widened = sorted(
        key
        for key, outcome in outcomes.items()
        if key in baseline and baseline[key] != "accepted" and outcome == "accepted"
    )
    single_mart = [key for key in widened if "+" not in key.split("|")[1]]

    assert single_mart == [], f"single-mart request(s) newly accepted: {single_mart}"
    assert widened, "no request became answerable — RFC 0041 P1 is a capability phase"


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
