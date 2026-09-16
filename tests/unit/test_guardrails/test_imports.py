"""The import guards (RFC 0059 §5.4, D1, D8).

Three ways a declared dependency can fail to be one, and each needs a *second
project* to be visible at all — which is what separates these from the document
tests next door. The upstream side is read from the IR it arrived as, because
under D2 that is what crosses; the local side from the authored documents,
because that is what an author can see and fix.
"""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, load_catalog, load_project
from bloomery.errors import GuardrailError, ImportCollision, UnexportedImport, UnknownUpstream
from bloomery.ir import ProjectIR
from support.compiling import FIXTURES, fixture_sources

pytestmark = pytest.mark.unit

#: `ecom_basic` is the upstream in every case here: it is the one fixture with
#: an export list, which is what makes it the only one that can be one.
UPSTREAM = "ecom_basic"

#: `multi_mart_refusal` is the downstream: it declares `order`, `order_item`
#: and `order_items`, every one of which `ecom_basic` also exports — so the
#: collision leg has a subject without inventing a project for it.
DOWNSTREAM = "multi_mart_refusal"


def _catalog():
    return load_catalog((FIXTURES / UPSTREAM / "catalog.yaml").read_text())


def _upstream() -> ProjectIR:
    return build_project_ir(load_project(fixture_sources(UPSTREAM)), catalog=_catalog())


def _compile(body: str, *, supplied: bool = True, fixture: str = DOWNSTREAM) -> ProjectIR:
    documents = fixture_sources(fixture)
    documents["imports"] = f"imports_version: 1\nimports:\n{body}"
    upstream = {"platform": _upstream()} if supplied else {}
    return build_project_ir(load_project(documents), catalog=_catalog(), upstream=upstream)


def test_the_upstream_export_list_is_what_an_import_is_checked_against() -> None:
    """The clean case, and it is not vacuous: `ecom_basic` exports exactly
    these, and `multi_mart_refusal` declares none of them under these names."""

    ir = _compile("  platform:\n    metrics: [gross_revenue, order_count]\n")

    assert ir.exports is None  # the downstream publishes nothing of its own


def test_an_upstream_the_compile_was_not_given_is_refused() -> None:
    with pytest.raises(GuardrailError) as caught:
        _compile("  platform:\n    metrics: [gross_revenue]\n", supplied=False)

    leaf = caught.value.collected[0]
    assert isinstance(leaf, UnknownUpstream)
    assert "imports from 'platform', which this compile was not given" in str(caught.value)
    # An empty set is a different repair from a misspelled alias, so the
    # message says which it is rather than trailing off.
    assert "Supplied: (none)" in str(caught.value)
    assert leaf.supplied == ()
    assert leaf.source_path == "imports: imports.platform"


def test_the_supplied_aliases_are_named_when_there_are_some() -> None:
    """`UnknownStep`'s reasoning, one input over: the registry is the whole
    world, so the refusal prints the world."""

    with pytest.raises(GuardrailError) as caught:
        _compile("  platfrom:\n    metrics: [gross_revenue]\n")

    leaf = caught.value.collected[0]
    assert isinstance(leaf, UnknownUpstream)
    assert "Supplied: 'platform'" in str(caught.value)
    assert leaf.supplied == ("platform",)


def test_a_name_the_upstream_does_not_export_is_refused() -> None:
    """`margin` is declared by `ecom_basic` and absent from its export list,
    which is the distinction an export list exists to make — the name is real
    and it is not published."""

    with pytest.raises(GuardrailError) as caught:
        _compile("  platform:\n    metrics: [margin]\n")

    message = str(caught.value)
    assert isinstance(caught.value.collected[0], UnexportedImport)
    assert "imports metric 'margin' from 'platform', which does not export it" in message
    # The fix is a corrected name here or an added name there, and only the
    # list tells an author which.
    assert "Exported metrics: 'gross_revenue', 'order_count'" in message


def test_a_local_name_colliding_with_an_imported_one_is_refused() -> None:
    with pytest.raises(GuardrailError) as caught:
        _compile("  platform:\n    entities: [order]\n")

    message = str(caught.value)
    assert isinstance(caught.value.collected[0], ImportCollision)
    assert "imports entity 'order' from 'platform' and declares one of its own" in message


def test_each_kind_names_itself_in_the_singular() -> None:
    """Sliced off the plural, `entities` spells `entitie` — which is the shape
    of mistake that reaches a user and nothing else catches.

    **Both messages, and that is the point.** The refusals are written twice,
    once per class, so a singular fixed in one and sliced in the other reads
    correct in whichever test happens to exercise it. `metrics` is no use as a
    subject either way: its slice is already `metric`.
    """

    with pytest.raises(GuardrailError) as collision:
        _compile("  platform:\n    entities: [order]\n    marts: [order_items]\n")

    with pytest.raises(GuardrailError) as unexported:
        _compile("  platform:\n    entities: [ghost]\n    marts: [phantom]\n")

    for caught in (collision, unexported):
        message = str(caught.value)
        assert "entity '" in message
        assert "mart '" in message
        # Anchored on the position the singular is spelled at: the plural
        # `entities` legitimately contains `entitie`, so a bare substring check
        # here would pass against the very bug it is written for.
        assert "imports entitie " not in message


def test_a_missing_upstream_reports_once_rather_than_once_per_name() -> None:
    """With no IR there is no export list to compare against, so reporting
    every name under it would be three refusals for one mistake, each naming a
    fix that is not the fix."""

    with pytest.raises(GuardrailError) as caught:
        _compile("  ghost:\n    entities: [a]\n    marts: [b]\n    metrics: [c]\n")

    assert len(caught.value.collected) == 1
    assert isinstance(caught.value.collected[0], UnknownUpstream)


def test_every_failing_name_is_reported_not_only_the_first() -> None:
    """A boundary is usually got wrong the same way more than once, and one
    refusal per round-trip would make an author fix a rename four times."""

    with pytest.raises(GuardrailError) as caught:
        _compile("  platform:\n    entities: [order]\n    metrics: [margin, nope]\n")

    assert len(caught.value.collected) == 3


def test_an_upstream_that_exports_nothing_refuses_every_import_from_it() -> None:
    """A project with no exports document has `ProjectIR.exports is None`, and
    the guard must read that as an empty surface rather than skipping it —
    otherwise the one project that publishes nothing is the one that publishes
    everything."""

    documents = fixture_sources(DOWNSTREAM)
    documents["imports"] = "imports_version: 1\nimports:\n  platform:\n    metrics: [anything]\n"
    bare = build_project_ir(load_project(fixture_sources("minimal")))
    assert bare.exports is None

    with pytest.raises(GuardrailError) as caught:
        build_project_ir(
            load_project(documents), catalog=_catalog(), upstream={"platform": bare}
        )

    assert isinstance(caught.value.collected[0], UnexportedImport)
    assert "Exported metrics: (none)" in str(caught.value)


def test_no_imports_document_is_no_refusal() -> None:
    """Absence is how a project says it reads nothing, and it is the state
    every project in the corpus is in.

    Asserted on the *parsed project*, not on the IR, and that is the phase's
    shape rather than an oversight: an import list is local — read by this
    project's own guardrails and never by a further downstream, which reads
    this project's exports — so it does not reach `ProjectIR` (RFC 0059 D2).
    """

    project = load_project(fixture_sources("minimal"))
    assert project.imports is None
    assert build_project_ir(project) is not None


# ....................... #
# Both halves of "a name is claimed twice"


def _exporting(fixture: str, body: str) -> ProjectIR:
    """A fixture compiled with an exports document added, as an upstream."""

    documents = fixture_sources(fixture)
    documents["exports"] = f"exports_version: 1\nexports:\n{body}"
    return build_project_ir(load_project(documents))


def test_a_step_produced_entity_collides_with_an_imported_one() -> None:
    """The collision the authored entity model cannot see.

    A step output is an entity too, named after the last segment of the
    relation its wiring binds (RFC 0017 §5.8) — `step_resolution` declares one
    entity and drafts three. Reading `project.entity_model.entities` here would
    make this guard blind to exactly the entities the spec layer never sees,
    which is `check_lineage_names`'s argument and the reason it reads the draft.
    """

    from support.steps import registry_for

    documents = fixture_sources("step_resolution")
    documents["imports"] = "imports_version: 1\nimports:\n  platform:\n    entities: [customer]\n"
    upstream = _exporting("scd2_customers", "  entities: [customer]\n")

    with pytest.raises(GuardrailError) as caught:
        build_project_ir(
            load_project(documents),
            steps=registry_for("step_resolution"),
            upstream={"platform": upstream},
        )

    leaf = caught.value.collected[0]
    assert isinstance(leaf, ImportCollision)
    assert "imports entity 'customer' from 'platform' and declares one of its own" in str(
        caught.value
    )


def test_two_upstreams_supplying_one_name_are_refused() -> None:
    """§5.4 names the local-against-imported collision and stops there. This is
    the same ambiguity with neither claimant local — and worse, because each
    upstream's file is correct on its own, so no single author can see it.
    """

    upstream = _upstream()
    documents = fixture_sources("minimal")
    documents["imports"] = (
        "imports_version: 1\nimports:\n"
        "  platform:\n    metrics: [gross_revenue]\n"
        "  other:\n    metrics: [gross_revenue]\n"
    )

    with pytest.raises(GuardrailError) as caught:
        build_project_ir(
            load_project(documents), upstream={"platform": upstream, "other": upstream}
        )

    message = str(caught.value)
    assert isinstance(caught.value.collected[0], ImportCollision)
    assert "imports metric 'gross_revenue' from 2 upstreams — 'other', 'platform'" in message


def test_one_name_from_three_upstreams_is_one_refusal_naming_all_three() -> None:
    """Per colliding name rather than per pair: three upstreams would otherwise
    say the same thing three times."""

    upstream = _upstream()
    documents = fixture_sources("minimal")
    documents["imports"] = "imports_version: 1\nimports:\n" + "".join(
        f"  {alias}:\n    metrics: [gross_revenue]\n" for alias in ("a", "b", "c")
    )

    with pytest.raises(GuardrailError) as caught:
        build_project_ir(
            load_project(documents), upstream=dict.fromkeys(("a", "b", "c"), upstream)
        )

    assert len(caught.value.collected) == 1
    assert "from 3 upstreams — 'a', 'b', 'c'" in str(caught.value)


def test_the_public_entry_point_reaches_the_guard() -> None:
    """Every test above compiles through `build_project_ir`, which is one
    signature short of the surface a caller uses.

    `upstream` threads `compile_project → build_project_ir → pipeline →
    check_guardrails`, and a keyword dropped at the first of those four hops is
    invisible to a suite that starts at the second — the guard would be
    reachable and unreached.
    """

    from bloomery import Target, compile_project

    documents = fixture_sources(DOWNSTREAM)
    documents["imports"] = "imports_version: 1\nimports:\n  platform:\n    metrics: [margin]\n"

    with pytest.raises(GuardrailError) as caught:
        compile_project(
            load_project(documents),
            target=Target.SQLMESH,
            dialect="duckdb",
            catalog=_catalog(),
            upstream={"platform": _upstream()},
        )

    assert isinstance(caught.value.collected[0], UnexportedImport)


def test_every_surface_that_compiles_can_supply_an_upstream() -> None:
    """`pipeline` has three callers and threading one is not threading the
    guard.

    `evaluate` and the timeline compile the same project and would report a
    refusal the compiler does not — a guard handed a world its caller never
    passed along. One parametrized assertion rather than three tests, because
    the property is "every surface", and a fourth caller added later fails
    here rather than reporting a phantom `UnknownUpstream` to whoever uses it.
    """

    from bloomery.evidence import evaluate
    from bloomery.resolve.timeline import SpecVersion, timeline

    documents = fixture_sources(DOWNSTREAM)
    documents["imports"] = (
        "imports_version: 1\nimports:\n  platform:\n    metrics: [gross_revenue]\n"
    )
    project = load_project(documents)
    upstream = {"platform": _upstream()}

    # The compiler: clean.
    build_project_ir(project, catalog=_catalog(), upstream=upstream)

    # The evidence surface: clean only if it can pass the same input along.
    assert evaluate(project, catalog=_catalog()).refusals  # without it, a phantom refusal
    assert not evaluate(project, catalog=_catalog(), upstream=upstream).refusals

    # The timeline: every refusal propagates, so an unthreaded input is no
    # timeline at all for any importing project.
    versions = (
        SpecVersion(label="a", project=project, catalog=_catalog(), upstream=upstream),
        SpecVersion(label="b", project=project, catalog=_catalog(), upstream=upstream),
    )
    assert timeline(versions, "metric:gross_revenue") is not None
