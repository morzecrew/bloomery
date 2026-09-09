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

from bloomery.evidence import _conversions

from bloomery import (
    Catalog,
    CheckedSurfaces,
    MartSummary,
    Provenance,
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


def test_a_field_added_to_the_value_does_not_rebind_a_positional_caller() -> None:
    """Every field but the first has a default, so a **new** one inserted
    mid-list rebinds silently rather than raising.

    A caller written against the seven-field value —
    ``SpecEvidence(stage, reachable, unreachable, refusals, marts, entities,
    fingerprint)`` — would land its fingerprint in whatever now sits seventh and
    leave ``fingerprint`` at ``None``: an evidence value wrong in two places
    that refuses nothing and typechecks nowhere. Appending is what keeps an
    addition additive, and this is the test that fails if the next field is
    inserted instead.
    """
    evidence = SpecEvidence(
        Stage.COMPLETE, ("gross_revenue",), (), (), (), ("order_item",), "blm1:deadbeef"
    )
    assert evidence.fingerprint == "blm1:deadbeef"
    assert evidence.unresolved == ()
    assert evidence.provenance == ()
    assert evidence.checked is None


def test_a_merged_entitys_field_reports_one_entry_per_mapping() -> None:
    """Each mapping that builds a field says so in its own entry (RFC 0032).

    Two mappings building one entity may implement one field two ways. Until
    the record carried a mapping identity this collection keyed on
    ``(entity, field)`` and reported the last in document order, so the other
    mapping's answer was not representable at all — and the entry looked
    identical to a single-mapping one, which is what made it misleading rather
    than merely partial.

    The disagreement is constructed rather than taken from `multi_source`,
    which merges two mappings that happen to agree: a fixture where both
    mappings are `direct` would pass this whether the key were the pair or the
    triple. What is asserted is that the two entries differ, not merely that
    there are two.
    """
    sources = fixture_sources("ecom_basic")
    legacy = sources["mapping_order_items"].replace(
        "source: shopify__order_lines", "source: legacy__order_lines"
    )
    legacy = legacy.replace(
        'quantity: {from: "$.qty", transform: [to_int]}',
        'quantity: {recipe: direct, from: {quantity: "$.units"}}',
    )
    sources["mapping_legacy"] = legacy
    evidence = evaluate(load_project(sources), catalog=_ecom_catalog())
    assert evidence.stage_reached is Stage.COMPLETE, evidence.refusals

    quantity = [entry for entry in evidence.provenance if entry.field == "quantity"]
    assert [(e.mapping, e.provenance, e.recipe_id) for e in quantity] == [
        ("mapping_legacy", Provenance.RECIPE, "direct"),
        ("mapping_order_items", Provenance.DIRECT, None),
    ]
    assert "recipe: direct" in sources["mapping_legacy"], (
        "the fixture must actually disagree with the other mapping, or this proves nothing"
    )


def test_a_single_mapping_entitys_provenance_does_not_grow_rows() -> None:
    """The shape almost every project has is unchanged but for a field.

    Naming the mapping is additive: an entity built by one document reports the
    same fields it always did, each now saying which document that was. Without
    this, a keying change that quietly duplicated every entry would still pass
    the merged case above.
    """
    evidence = evaluate(load_project(fixture_sources("ecom_basic")), catalog=_ecom_catalog())

    assert {e.mapping for e in evidence.provenance} == {
        "mapping_order_items",
        "mapping_orders",
    }
    keyed = [(e.entity, e.field) for e in evidence.provenance]
    assert len(keyed) == len(set(keyed)), "one mapping per field here — no row should repeat"


def test_the_fixture_corpus_is_actually_being_walked() -> None:
    """A guard on the parametrization above: an empty ``LOADABLE`` would make
    every corpus test vacuously green."""
    assert len(LOADABLE) > 10
    assert "dirty" not in LOADABLE  # CSV specimens, not a spec project
    assert Path(FIXTURES / "minimal").is_dir()


# ....................... #
# RFC 0044 §3, D5 — the surfaces `check` counts


@pytest.mark.parametrize(
    ("name", "surface", "count"),
    [
        ("ecom_basic", "entities", 2),
        ("ecom_basic", "relationships", 1),
        ("ecom_basic", "marts", 1),
        ("currency_convert", "conversions", 1),
        ("currency_convert_refusal", "conversions", 1),
        ("scd2_as_of", "temporal_joins", 1),
        ("ecom_basic", "temporal_joins", 0),
        ("minimal", "relationships", 0),
    ],
)
def test_each_counted_surface_has_a_fixture_that_makes_it_non_zero(
    name: str, surface: str, count: int
) -> None:
    """One fixture per surface where the count is not zero (RFC 0044 §3).

    A count read from the wrong place is green against a corpus where every
    project happens to hold none of that surface, which is what a table of
    zeros cannot distinguish from a working counter. Two rows are controls:
    ``minimal`` carries no relationships, and ``ecom_basic`` carries a mart
    join that is *not* temporal — without it, counting every join and counting
    the anchored ones are the same number on every fixture in the corpus, and
    a sabotage that drops the ``as_of`` test survives (`logs/T-0030.md`).

    ``currency_convert_refusal`` is here for a narrower reason. Its conversion
    resolves and passes every guardrail and is refused at **emit**, where the
    marker reaches a target that does not define it (RFC 0023 D4) — a stage
    ``check`` never runs. It is counted, because it was checked; a count that
    had quietly become "conversions that survive emission" would read zero here
    and stay green on ``currency_convert``.
    """

    project, catalog = load_fixture(name)
    checked = evaluate(project, catalog=catalog).checked

    assert checked is not None
    assert getattr(checked, surface) == count


def test_measures_counts_what_was_authored_not_what_the_ir_holds() -> None:
    """``dirty_corpus`` authors no metric and its IR holds five.

    They are the quality mart's bloomery-owned measures (RFC 0016 §5.8), which
    nobody wrote and ``resolve()`` has never heard of. Counting ``ir.metrics``
    would report five type-checked measures to an author whose spec declares
    none — the same population mistake :func:`~bloomery.evidence._from_ir`
    avoids for reachability, made one field later.
    """

    project, catalog = load_fixture("dirty_corpus")
    evidence = evaluate(project, catalog=catalog)
    ir = build_project_ir(project, catalog=catalog)

    assert evidence.checked is not None
    assert len(ir.metrics) == 5
    assert evidence.checked.measures == 0
    assert evidence.checked.measures == len(evidence.reachable) + len(evidence.unreachable)


def test_measures_counts_an_unreachable_metric_as_checked() -> None:
    """Reachability is an answer about a measure, not a reason to skip it.

    ``ecom_basic`` authors four and one is unreachable; a count of three would
    report the surface as smaller because the project has a *gap*, which is the
    opposite of what a checked-surface count means.
    """

    project, catalog = load_fixture("ecom_basic")
    evidence = evaluate(project, catalog=catalog)

    assert evidence.checked is not None
    assert len(evidence.unreachable) == 1
    assert evidence.checked.measures == 4


@pytest.mark.parametrize("name", ["step_resolution", "identity_resolution"])
def test_nothing_is_counted_before_an_ir_exists(name: str) -> None:
    """``None``, never a zeroed count (RFC 0044 §3; ``logs/T-0030.md``).

    Both fixtures refuse at the lower stage, so no IR was built and no surface
    was checked. A ``CheckedSurfaces`` of zeros would say six surfaces were
    checked and found empty, which is a different claim and a false one.
    """

    project, catalog = load_fixture(name)
    evidence = evaluate(project, catalog=catalog)

    assert evidence.stage_reached is not Stage.COMPLETE
    assert evidence.checked is None


def test_nothing_is_counted_when_there_is_no_resolution_either() -> None:
    """The *other* IR-less shape, which the fixtures above do not reach.

    ``_partial`` has two ways to return without counts: a resolution that
    produced no IR, and no resolution at all. Every refusing fixture in the
    corpus takes the first — they all get past the resolve stage — so a
    sabotage that zeroed the second survived the sweep untouched
    (`logs/T-0030.md`). ``BAD_REFERENCE`` refuses at ``RESOLVE``, which is the
    only thing that reaches it.
    """

    evidence = evaluate(load_project(BAD_REFERENCE))

    assert evidence.stage_reached is Stage.RESOLVE
    assert evidence.reachable == ()
    assert evidence.checked is None


def test_a_draft_ir_is_counted_and_the_stage_says_it_is_a_prefix() -> None:
    """``fanout_trap`` refuses at the guardrail stage over a draft IR.

    The counts are real — those entities and that relationship were resolved —
    and they are not totals. Both halves are asserted here because dropping
    either is a plausible simplification: withholding them loses the prefix
    RFC 0022 D3 exists to preserve, and presenting them without the stage lets
    them read as a finished answer.
    """

    project, catalog = load_fixture("fanout_trap")
    evidence = evaluate(project, catalog=catalog)

    assert evidence.stage_reached is Stage.GUARDRAILS
    assert evidence.checked == CheckedSurfaces(
        entities=2, relationships=1, measures=2, marts=0, conversions=0, temporal_joins=0
    )


def test_only_a_simple_mapping_and_a_key_carry_a_transform_chain() -> None:
    """The count reads a chain off whatever has one, and this says which do.

    ``_conversions`` asks each field for its ``transform`` with a default, so a
    mapping kind that gained a chain would be walked past in silence and every
    conversion in it would go uncounted — a failure with no symptom, since the
    number would simply be smaller. This fails instead, in the commit that adds
    the chain (RFC 0061 D7 reached the same answer for ``currency_in``).
    """

    from bloomery.spec.mapping import (
        KeyField,
        MacroFieldMapping,
        RecipeFieldMapping,
        SimpleFieldMapping,
    )

    assert "transform" in KeyField.model_fields
    assert "transform" in SimpleFieldMapping.model_fields
    assert "transform" not in RecipeFieldMapping.model_fields
    assert "transform" not in MacroFieldMapping.model_fields


def test_a_conversion_on_a_key_is_counted() -> None:
    """``resolve.build`` walks a key's chain, so the count walks it too.

    A key is a strange place to convert and RFC 0061 D7 keeps it legal anyway:
    a decimal key can carry a marker, and an unwalked one reaches emit. No
    fixture has one, so dropping ``mapping.key`` from the walk changed no test
    (`logs/T-0030.md`) — the helper is exercised directly here rather than
    through a pipeline that would first have to accept a decimal key.
    """

    sources = fixture_sources("currency_convert")
    original = 'payment_id: {from: "$.id", transform: [to_string]}'
    converted = 'payment_id: {from: "$.id", transform: [{convert: [EUR, USD, paid_at]}]}'
    assert original in sources["mapping"]
    sources["mapping"] = sources["mapping"].replace(original, converted)

    assert _conversions(load_project(sources)) == 2
    assert _conversions(load_project(fixture_sources("currency_convert"))) == 1
