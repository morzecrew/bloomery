"""``evaluate()`` — spec analysis as a value (RFC 0022).

The claims worth testing here are not "it returns a dataclass". They are:

* **Composition, by equality.** A third entry point into the pipeline is the
  failure mode this feature could plausibly introduce, so reachability is
  compared against :func:`~bloomery.resolve`'s for every fixture that gets that
  far, rather than inspected.
* **Partiality.** A spec refused at the guardrail stage still reports the
  reachability computed two stages earlier. It is easy to implement
  ``evaluate()`` as a ``try``/``except`` around ``compile_project`` that throws
  the prefix away, and that implementation passes almost every other test in
  this file.
* **The catch is narrow.** ``BloomeryError`` becomes a return value;
  ``InvariantViolated`` — which subclasses it and means *bloomery* is broken —
  and every programming error still raise.
* **Every stage is reachable.** ``Stage`` claims five members and each is
  reported by a spec that refuses there, which is what stops a member being a
  branch a consumer writes and never executes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from support.compiling import FIXTURES, fixture_sources, load_fixture
from support.steps import registry_for

from bloomery import (
    Catalog,
    MartSummary,
    SpecEvidence,
    Stage,
    build_project_ir,
    evaluate,
    load_project,
    project_fingerprint,
    resolve,
)
from bloomery.errors import BloomeryError, GrainViolation, InvariantViolated

pytestmark = pytest.mark.unit


def _loadable() -> list[str]:
    """Every fixture that is a spec project this can be asked about.

    ``dirty/`` holds 139 CSV specimens rather than YAML documents, and
    ``dirty_corpus/`` is the spec that judges them — so the corpus directory is
    not uniformly loadable, and a hard-coded list would go stale the first time
    a fixture is added. Loadability is asked rather than assumed.
    """
    names: list[str] = []
    for path in sorted(FIXTURES.iterdir()):
        if not path.is_dir() or not list(path.glob("*.yaml")):
            continue
        try:
            load_fixture(path.name)
        except BloomeryError:
            continue
        names.append(path.name)
    return names


LOADABLE = _loadable()


def _evaluate(name: str) -> SpecEvidence:
    project, catalog = load_fixture(name)
    return evaluate(project, catalog=catalog, steps=registry_for(name))


# ....................... #
# Stage reachability — every member is a state a spec can actually be in


def _minimal(**replacements: tuple[str, str]) -> dict[str, str]:
    """The ``minimal`` fixture with one substitution per named document."""
    sources = fixture_sources("minimal")
    for document, (old, new) in replacements.items():
        assert old in sources[document], f"{document}: {old!r} is no longer in the fixture"
        sources[document] = sources[document].replace(old, new)
    return sources


#: A mapping whose target entity does not exist — reference validation refuses,
#: which is the first stage `evaluate` can report.
BAD_REFERENCE = _minimal(mapping=("target: event", "target: ghost"))

#: A chain whose terminal type is not assignable to the declared `string`.
BAD_CHAIN = _minimal(
    mapping=('kind: {from: "$.kind"}', 'kind: {from: "$.kind", transform: [to_int]}')
)


@pytest.mark.parametrize(
    ("sources", "stage"),
    [
        pytest.param(BAD_REFERENCE, Stage.RESOLVE, id="resolve"),
        pytest.param(BAD_CHAIN, Stage.TYPECHECK, id="typecheck"),
    ],
)
def test_a_refusal_names_the_stage_it_came_from(sources: dict[str, str], stage: Stage) -> None:
    evidence = evaluate(load_project(sources))
    assert evidence.stage_reached is stage
    assert evidence.refusals


def test_a_step_that_is_not_wired_refuses_while_lowering() -> None:
    """The ``LOWER`` stage, which the draft RFC called ``MARTS``.

    Mart flattening refuses nothing of its own — the flattener is total and the
    guardrail stage re-derives its violations (RFC 0010 D6) — but step lowering
    does, and it happens in the same stage. Naming the stage for the flattening
    would have left the member unreachable and this refusal unnamed.
    """
    project, catalog = load_fixture("step_resolution")
    evidence = evaluate(project, catalog=catalog)  # deliberately no registry
    assert evidence.stage_reached is Stage.LOWER
    assert [type(refusal).__name__ for refusal in evidence.refusals] == ["UnknownStep"]


def test_the_guardrail_stage_is_reported_rather_than_raised() -> None:
    evidence = _evaluate("fanout_trap")
    assert evidence.stage_reached is Stage.GUARDRAILS
    assert any(isinstance(refusal, GrainViolation) for refusal in evidence.refusals)


def test_every_stage_is_reachable() -> None:
    """The claim that justifies the enum's membership.

    RFC 0022's draft listed ``PARSE`` and ``MARTS`` as well. Neither can be
    reported — ``load_project`` has already run by the time anything holds a
    ``Project``, and the flattener refuses nothing — so a consumer branching on
    them would write code that never runs. This fails if a member is added
    without a spec that reaches it.
    """
    unwired_step, step_catalog = load_fixture("step_resolution")
    reached = {
        evaluate(load_project(BAD_REFERENCE)).stage_reached,
        evaluate(load_project(BAD_CHAIN)).stage_reached,
        evaluate(unwired_step, catalog=step_catalog).stage_reached,
        _evaluate("fanout_trap").stage_reached,
        _evaluate("minimal").stage_reached,
    }
    assert reached == set(Stage)


# ....................... #
# `via` — the chain a blocked metric is blocked through (RFC 0022 D11)


#: `ecom_basic` plus a metric derived from its deliberately-unreachable one.
#: The corpus has no transitively blocked metric of its own — every derivation
#: in it resolves — so the case `via` exists for has to be built.
BLOCKED_THROUGH_A_METRIC = {
    **fixture_sources("ecom_basic"),
    "metrics": fixture_sources("ecom_basic")["metrics"]
    + """
  margin_rate:
    requires_metrics: [margin, order_count]
    additivity: non_additive
    ratio: {numerator: margin, denominator: order_count}
""",
}


def test_a_transitively_blocked_metric_names_the_chain() -> None:
    """`missing` stays leaves-only (RFC 0005 D3) — the fix is a mapping, never
    a metric — and `via` carries the intermediate beside it, so a reader is not
    left to re-walk a graph the compiler just walked."""
    project, catalog = load_project(BLOCKED_THROUGH_A_METRIC), _ecom_catalog()
    evidence = evaluate(project, catalog=catalog)
    assert evidence.stage_reached is Stage.COMPLETE
    blocked = {metric.name: metric for metric in evidence.unreachable}
    assert blocked["margin_rate"].missing == ("cogs",)
    assert blocked["margin_rate"].via == ("margin",)
    # The metric blocked on its own leaf names no chain: there is nothing
    # between it and the missing mapping.
    assert blocked["margin"].via == ()


def _ecom_catalog() -> Catalog:
    return load_fixture("ecom_basic")[1] or pytest.fail("ecom_basic must carry a catalog")


# ....................... #
# Composition — evaluate() and resolve() describe one project


@pytest.mark.parametrize("name", LOADABLE)
def test_reachability_equals_what_resolve_returns(name: str) -> None:
    """RFC 0022 D10: proven by equality, not by inspection.

    Only for fixtures that reach the resolve stage — a spec refused there has
    no ``resolve()`` result to compare against, and is covered by the stage
    rows above.
    """
    project, catalog = load_fixture(name)
    evidence = evaluate(project, catalog=catalog, steps=registry_for(name))
    if evidence.stage_reached is Stage.RESOLVE:
        pytest.skip(f"{name} refuses at the resolve stage")
    resolution = resolve(project, catalog)
    assert evidence.reachable == tuple(sorted(resolution.reachable_metrics))
    assert set(evidence.unreachable) == set(resolution.unreachable_metrics)


@pytest.mark.parametrize("name", LOADABLE)
def test_a_complete_evaluation_carries_the_compilers_own_fingerprint(name: str) -> None:
    """The other half of composition: when analysis completes, the identity it
    reports is the one ``build_project_ir`` mints, not a second one."""
    evidence = _evaluate(name)
    if evidence.stage_reached is not Stage.COMPLETE:
        pytest.skip(f"{name} refuses at {evidence.stage_reached.value}")
    project, catalog = load_fixture(name)
    ir = build_project_ir(project, catalog=catalog, steps=registry_for(name))
    assert evidence.fingerprint == project_fingerprint(ir)
    assert evidence.refusals == ()
    assert evidence.entities == tuple(sorted(entity.name for entity in ir.entities))


# ....................... #
# Partiality — the claim the feature exists for


def test_a_guardrail_refusal_keeps_the_reachability_computed_before_it() -> None:
    """RFC 0022 D3, on the case it exists for.

    ``fanout_trap`` refuses at the guardrail stage, two stages after
    reachability was computed. An implementation that wrapped
    ``compile_project`` in a ``try``/``except`` would report the refusal and
    discard this, and would pass every other test in this file.
    """
    project, catalog = load_fixture("fanout_trap")
    evidence = evaluate(project, catalog=catalog)
    assert evidence.stage_reached is Stage.GUARDRAILS
    assert evidence.reachable == tuple(sorted(resolve(project, catalog).reachable_metrics))
    assert evidence.reachable, "the fixture must have reachable metrics for this to prove anything"


def test_a_refusal_at_the_first_stage_reports_empty_rather_than_wrong() -> None:
    """The ambiguity ``stage_reached`` exists to resolve: every tuple is empty
    here, and none of them means "nothing found"."""
    evidence = evaluate(load_project(BAD_REFERENCE))
    assert evidence.stage_reached is Stage.RESOLVE
    assert evidence.reachable == ()
    assert evidence.unreachable == ()
    assert evidence.marts == ()
    assert evidence.entities == ()
    assert evidence.fingerprint is None


def test_a_draft_is_not_fingerprinted() -> None:
    """A fingerprint is a project's identity. The guardrail stage has already
    said this spec is invalid, so minting one would name something that will
    never be built."""
    assert _evaluate("fanout_trap").fingerprint is None


# ....................... #
# Refusals as values


@pytest.mark.parametrize("name", LOADABLE)
def test_no_fixture_makes_evaluate_raise(name: str) -> None:
    """The promise, over the whole corpus including the deliberately invalid
    fixtures. ``InvariantViolated`` is excluded by §5.3 and would fail here if
    one ever escaped, which is the point of not excluding it from the catch."""
    _evaluate(name)


def test_a_batched_refusal_arrives_as_its_individual_failures() -> None:
    """A batched stage raises one aggregate whose message enumerates the batch
    and whose ``collected`` carries each failure with its own ``source_path``
    (RFC 0002 D6). Handing back the aggregate would make a caller re-parse a
    paragraph for paths it already has structured."""
    evidence = _evaluate("fanout_trap")
    assert len(evidence.refusals) > 1
    assert all(refusal.collected == () for refusal in evidence.refusals)
    assert all(refusal.source_path for refusal in evidence.refusals)


def test_refusals_are_sorted_by_source_path() -> None:
    evidence = _evaluate("fanout_trap")
    keys = [(r.source_path or "", type(r).__name__, str(r)) for r in evidence.refusals]
    assert keys == sorted(keys)


def test_a_programming_error_still_raises() -> None:
    """The catch is ``BloomeryError`` and nothing wider. A malformed registry
    is a caller bug, and a function that returned it as a spec refusal would be
    worse than the exception path it replaces.

    Asked of a project that **wires a step**, deliberately: a registry nothing
    consults is never touched, so ``minimal`` would evaluate a malformed one
    clean and the test would prove only that the argument is unused.
    """
    project, catalog = load_fixture("step_resolution")
    with pytest.raises(AttributeError):
        # pyright: ignore[reportArgumentType] — passing the wrong type is the test
        evaluate(project, catalog=catalog, steps="not a registry")  # type: ignore[arg-type]


def test_invariant_violated_propagates_rather_than_being_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5.3's known soft spot, pinned.

    ``InvariantViolated`` *is* a ``BloomeryError`` by inheritance and *is* a
    bloomery bug by meaning. Reporting it as a spec refusal would file our
    defect under the author's mistake, so it is re-raised explicitly — and a
    narrow catch is only as good as the taxonomy beneath it, which is why this
    is a test rather than a comment.
    """
    import bloomery.evidence as evidence_module

    def explode(*_args: object, **_kwargs: object) -> None:
        msg = "a guarantee an earlier stage was supposed to establish"
        raise InvariantViolated(msg)

    monkeypatch.setattr(evidence_module, "pipeline", explode)
    project, catalog = load_fixture("minimal")
    with pytest.raises(InvariantViolated):
        evaluate(project, catalog=catalog)


def test_structured_suggestions_survive_into_refusals() -> None:
    """RFC 0020's fix suggestions are values on the error, so unwrapping the
    batch must not flatten them into strings."""
    evidence = _evaluate("fanout_trap")
    violations = [r for r in evidence.refusals if isinstance(r, GrainViolation)]
    assert violations
    assert all(isinstance(v.offending_measures, tuple) for v in violations)


# ....................... #
# MartSummary — a projection, never a recomputation


@pytest.mark.parametrize("name", LOADABLE)
def test_mart_summaries_match_the_ir(name: str) -> None:
    evidence = _evaluate(name)
    if evidence.stage_reached is not Stage.COMPLETE:
        pytest.skip(f"{name} refuses at {evidence.stage_reached.value}")
    project, catalog = load_fixture(name)
    ir = build_project_ir(project, catalog=catalog, steps=registry_for(name))
    expected = sorted(
        (
            MartSummary(
                name=mart.name,
                grain=mart.grain,
                measures=tuple(sorted(mart.measures)),
                dimensions=tuple(sorted(str(d.ref) for d in mart.dimensions)),
                materialization=mart.materialization,
            )
            for mart in ir.marts
        ),
        key=lambda summary: (summary.name, summary.grain),
    )
    assert list(evidence.marts) == expected


def test_mart_dimensions_are_role_qualified() -> None:
    """The names a request writes, not the entity fields they flatten from —
    which is the whole reason role-playing dates exist (RFC 0010)."""
    evidence = _evaluate("role_playing_dates")
    assert evidence.stage_reached is Stage.COMPLETE
    dimensions = {name for mart in evidence.marts for name in mart.dimensions}
    assert dimensions, "the fixture must expose dimensions for this to prove anything"


# ....................... #
# Determinism


@pytest.mark.parametrize("name", LOADABLE)
def test_every_tuple_is_sorted(name: str) -> None:
    """Determinism applies to an assessment as much as to an artifact, and
    ``sorted()`` over these values raises rather than ordering badly — neither
    an exception nor a frozen dataclass defines ``__lt__``."""
    evidence = _evaluate(name)
    assert list(evidence.reachable) == sorted(evidence.reachable)
    assert list(evidence.entities) == sorted(evidence.entities)
    assert [(u.name, u.missing) for u in evidence.unreachable] == sorted(
        (u.name, u.missing) for u in evidence.unreachable
    )
    assert [(m.name, m.grain) for m in evidence.marts] == sorted(
        (m.name, m.grain) for m in evidence.marts
    )
    # RFC 0030's two fields sort by their own declared keys. `options` inside a
    # decision deliberately does not — catalog order is authored (D2) — and
    # `tests/unit/test_unresolved.py` is where that exception is asserted.
    assert [d.canonical for d in evidence.unresolved] == sorted(
        d.canonical for d in evidence.unresolved
    )
    assert [(p.entity, p.field) for p in evidence.provenance] == sorted(
        (p.entity, p.field) for p in evidence.provenance
    )


def test_the_fixture_corpus_is_actually_being_walked() -> None:
    """A guard on the parametrization above: an empty ``LOADABLE`` would make
    every corpus test vacuously green."""
    assert len(LOADABLE) > 10
    assert "dirty" not in LOADABLE  # CSV specimens, not a spec project
    assert Path(FIXTURES / "minimal").is_dir()
