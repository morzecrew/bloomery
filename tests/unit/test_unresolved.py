"""The unresolved-work report — what a spec leaves open (RFC 0030).

Four claims, and none of them is "the dataclass has the fields".

* **The two gaps split.** RFC 0030 §3 measured five spec states that report
  identically today; the report's reason to exist is that two of them need
  different edits. The battery below asserts which pair must *agree* — a
  ``required:`` field is the same decision as a non-required one — as loudly as
  which pair must differ.
* **The loop terminates**, and the measure that decreases is the pair
  ``(open, unlinked among them)`` rather than the count (§5.4, D10). The test
  is a chooser: it reads the report, applies the first entry mechanically, and
  recompiles until nothing is open.
* **Catalog order survives.** ``options`` is the one collection on this surface
  that is not sorted, because recipe order is authored (D2). Asserted against a
  catalog written out of alphabetical order, so a stray ``sorted()`` fails.
* **One notion of availability.** The report and reachability are two readings
  of one graph, and the corpus sweep is what stops them drifting apart (§9).
"""

from __future__ import annotations

import pytest
from support.compiling import FIXTURES, fixture_sources, load_fixture, spec_fixture_names
from support.steps import registry_for

from bloomery import Catalog, Gap, SpecEvidence, Stage, evaluate, load_catalog, load_project
from bloomery.resolve import resolve
from bloomery.resolve.reach import available_canonicals

pytestmark = pytest.mark.unit


def _catalog() -> Catalog:
    return load_fixture("ecom_basic")[1] or pytest.fail("ecom_basic must carry a catalog")


def _evaluate(sources: dict[str, str], catalog: Catalog | None = None) -> SpecEvidence:
    return evaluate(load_project(sources), catalog=catalog or _catalog())


# ....................... #
# §3's states, as one battery — including the pair that must agree


#: Where a new field goes in `ecom_basic`'s entity model, and where a new field
#: mapping goes in the mapping that targets the same entity. Anchored on a line
#: the fixture actually has, so a fixture edit fails here rather than silently
#: producing a spec that no longer exercises the case.
_ENTITY_ANCHOR = "      quantity: {type: int, canonical: quantity}\n"
_MAPPING_ANCHOR = "fields:\n"


def _with(*, field: str = "", mapped: str = "") -> dict[str, str]:
    """`ecom_basic` plus an entity field, a mapping field, or both."""
    sources = fixture_sources("ecom_basic")
    if field:
        assert _ENTITY_ANCHOR in sources["entity_model"]
        sources["entity_model"] = sources["entity_model"].replace(
            _ENTITY_ANCHOR, _ENTITY_ANCHOR + field
        )
    if mapped:
        assert _MAPPING_ANCHOR in sources["mapping_order_items"]
        sources["mapping_order_items"] = sources["mapping_order_items"].replace(
            _MAPPING_ANCHOR, _MAPPING_ANCHOR + mapped
        )
    return sources


#: `cogs` is the corpus's deliberately-unmapped canonical (`ecom_basic`'s
#: catalog says so in a comment), and `margin` is the metric blocked on it.
LINKED = '      cogs: {type: "decimal(12,4)", canonical: cogs}\n'
LINKED_REQUIRED = '      cogs: {type: "decimal(12,4)", canonical: cogs, required: true}\n'
MAPPED_DIRECT = '  cogs: {from: "$.cost"}\n'
MAPPED_RECIPE = '  cogs: {recipe: direct, from: {cogs: "$.cost"}}\n'
MAPPED_UNKNOWN_RECIPE = '  cogs: {recipe: nosuch, from: {cogs: "$.cost"}}\n'
MAPPED_UNBOUND_RECIPE = '  cogs: {recipe: direct, from: {wrong_alias: "$.cost"}}\n'


@pytest.mark.parametrize(
    ("case", "sources", "expected"),
    [
        pytest.param("a", _with(field=LINKED, mapped=MAPPED_DIRECT), None, id="a-direct"),
        pytest.param("b", _with(field=LINKED, mapped=MAPPED_RECIPE), None, id="b-recipe"),
        pytest.param("c", _with(field=LINKED), (Gap.UNMAPPED, "cogs"), id="c-unmapped"),
        pytest.param(
            "c-prime", _with(field=LINKED_REQUIRED), (Gap.UNMAPPED, "cogs"), id="c-required"
        ),
        pytest.param("c-second", _with(), (Gap.UNLINKED, None), id="c-unlinked"),
    ],
)
def test_the_five_resolvable_states_report_as_designed(
    case: str, sources: dict[str, str], expected: tuple[Gap, str | None] | None
) -> None:
    """RFC 0030 §3's table, with the two mapped states asserted to be silent.

    ``required:`` constrains the emitted column and not the mapping, so ``c``
    and ``c′`` are the *same* decision and must report identically — that is
    the pair a reader of this battery should see agreeing. ``c″`` is the one
    that splits: nothing links the canonical, so the edit is an entity-model
    edit rather than a mapping one.
    """
    evidence = _evaluate(sources)
    assert evidence.stage_reached is Stage.COMPLETE, case
    if expected is None:
        assert evidence.unresolved == (), case
        assert "margin" in evidence.reachable, case
        return
    gap, field = expected
    (decision,) = evidence.unresolved
    assert (decision.canonical, decision.gap, decision.entity, decision.field) == (
        "cogs",
        gap,
        "order_item",
        field,
    )
    assert decision.blocks == ("margin",)
    assert [option.id for option in decision.options] == ["direct"]


def test_a_transitively_blocked_metric_is_in_blocks() -> None:
    """``blocks`` is what a caller sets a priority from, so it has to be the
    whole cost of leaving the decision open.

    ``missing`` already carries leaves inherited through a blocked requirement
    (RFC 0005 D3, and ``via`` beside it), so a metric blocked *through* another
    is waiting on this decision as surely as the one blocked on it directly —
    and a report that named only the direct one would understate the decision by
    exactly the derived metrics nobody sees.
    """
    sources = _with()
    sources["metrics"] = (
        sources["metrics"]
        + """
  margin_rate:
    requires_metrics: [margin, order_count]
    additivity: non_additive
    ratio: {numerator: margin, denominator: order_count}
"""
    )
    (decision,) = _evaluate(sources).unresolved
    assert decision.blocks == ("margin", "margin_rate")


def test_required_changes_nothing_about_the_decision() -> None:
    """The pair that must agree, asserted as an equality rather than left to a
    reader comparing two parametrized rows."""
    assert _evaluate(_with(field=LINKED)).unresolved == _evaluate(
        _with(field=LINKED_REQUIRED)
    ).unresolved


@pytest.mark.parametrize(
    "mapped",
    [
        pytest.param(MAPPED_UNKNOWN_RECIPE, id="d-unknown-id"),
        pytest.param(MAPPED_UNBOUND_RECIPE, id="e-unbound-requires"),
    ],
)
def test_a_recipe_refusal_costs_the_round_its_worklist(mapped: str) -> None:
    """RFC 0030 D5, cases (d) and (e), as the design accepts them.

    Recipe validation is inside the resolve stage, so a malformed choice means
    no graph, no reachability and nothing to project. The refusal names its own
    fix precisely, which is what makes this an accepted cost rather than a hole:
    fix the error, recompile, read the report.
    """
    evidence = _evaluate(_with(field=LINKED, mapped=mapped))
    assert evidence.stage_reached is Stage.RESOLVE
    assert evidence.refusals
    assert evidence.unresolved == ()
    assert evidence.provenance == ()


def test_a_later_refusal_keeps_the_report() -> None:
    """The departure from D5's headline (`logs/T-0007.md` D-031).

    A spec that resolved cleanly and is refused two stages later has open
    decisions that were computed and are correct. Emptying them there would make
    ``unresolved`` the one field on this type whose emptiness ``stage_reached``
    cannot explain — and ``reachable`` is already reported at the same stage,
    from the same ``Resolution``.
    """
    sources = _with()
    sources["mapping_order_items"] = sources["mapping_order_items"].replace(
        'quantity: {from: "$.qty", transform: [to_int]}',
        'quantity: {from: "$.qty", transform: [to_string]}',
    )
    evidence = _evaluate(sources)
    assert evidence.stage_reached is Stage.TYPECHECK
    assert evidence.refusals
    assert [decision.canonical for decision in evidence.unresolved] == ["cogs"]
    assert evidence.provenance


# ....................... #
# The loop: a chooser that reads the report and edits one document a round


#: Two more open decisions on top of `cogs`, one of which the entity model
#: already links — so a round of the loop below has both gaps to close and the
#: `UNLINKED` → `UNMAPPED` transition (D10) is exercised rather than assumed.
LOOP_CATALOG = """
  net_revenue:
    entity: order_item
    type: "decimal(12,4)"
    unit: currency
    tax_basis: net
    recipes:
      - {id: gross_minus_tax, requires: [gross, tax], expr: "gross - tax"}
      - {id: direct_net, requires: [net_revenue]}
"""

LOOP_METRICS = """
  total_net_revenue:
    requires: [net_revenue]
    grain: order_item
    additivity: additive
    agg: sum
    expr: "net_revenue"
"""


def _loop_sources() -> dict[str, str]:
    sources = _with(field='      net_revenue: {type: "decimal(12,4)", canonical: net_revenue}\n')
    sources["metrics"] = sources["metrics"] + LOOP_METRICS
    return sources


def _loop_catalog() -> Catalog:
    """`ecom_basic`'s catalog plus `net_revenue` and its two recipes."""
    text = (FIXTURES / "ecom_basic" / "catalog.yaml").read_text()
    anchor = "\ncanonical_relationships:"
    assert anchor in text
    return load_catalog(text.replace(anchor, LOOP_CATALOG + anchor))


def _apply(sources: dict[str, str], evidence: SpecEvidence, catalog: Catalog) -> dict[str, str]:
    """One round of a chooser: close the report's first entry, mechanically.

    Deliberately the *first* entry and the *first* option — this stands in for
    an agent, and what it proves is that the loop shrinks, not that the choice
    is good. Which document it edits is decided by ``gap`` alone, which is the
    whole of what RFC 0030 D3 claims the field is for.
    """
    decision = evidence.unresolved[0]
    updated = dict(sources)
    if decision.gap is Gap.UNLINKED:
        declared = catalog.canonical_fields[decision.canonical]
        line = f'      {decision.canonical}: {{type: "{declared.type}", '
        line += f"canonical: {decision.canonical}}}\n"
        updated["entity_model"] = updated["entity_model"].replace(
            _ENTITY_ANCHOR, _ENTITY_ANCHOR + line
        )
        return updated
    option = decision.options[0]
    bindings = ", ".join(f'{slot}: "$.{slot}"' for slot in option.requires)
    line = f"  {decision.field}: {{recipe: {option.id}, from: {{{bindings}}}}}\n"
    updated["mapping_order_items"] = updated["mapping_order_items"].replace(
        _MAPPING_ANCHOR, _MAPPING_ANCHOR + line
    )
    return updated


def test_the_loop_reaches_a_fixed_point() -> None:
    """§5.4 as a check rather than as prose.

    The measure is the **pair** ``(open, unlinked)`` under lexicographic order,
    not the count: an entity-model edit closes nothing, it turns an ``UNLINKED``
    entry into an ``UNMAPPED`` one, and a test asserting the count strictly
    decreases would fail on exactly the transition D10 exists to name.
    """
    sources, catalog = _loop_sources(), _loop_catalog()
    evidence = _evaluate(sources, catalog)
    assert {(d.canonical, d.gap) for d in evidence.unresolved} == {
        ("cogs", Gap.UNLINKED),
        ("net_revenue", Gap.UNMAPPED),
    }, "the loop must start with both gaps present, or it proves half of D10"

    seen: list[tuple[int, int]] = []
    for _round in range(10):
        measure = (
            len(evidence.unresolved),
            sum(1 for d in evidence.unresolved if d.gap is Gap.UNLINKED),
        )
        if not evidence.unresolved:
            break
        assert not seen or measure < seen[-1], f"measure did not decrease: {seen} then {measure}"
        seen.append(measure)
        sources = _apply(sources, evidence, catalog)
        evidence = _evaluate(sources, catalog)
        assert evidence.stage_reached is Stage.COMPLETE, evidence.refusals
    else:  # pragma: no cover — a loop that does not terminate fails here
        pytest.fail(f"the loop did not reach a fixed point: {seen}")

    assert evidence.unresolved == ()
    assert "margin" in evidence.reachable
    assert "total_net_revenue" in evidence.reachable
    # Three rounds, and the middle one is the transition: closing `cogs` takes
    # two edits (D10) while `net_revenue` takes one.
    assert seen == [(2, 1), (2, 0), (1, 0)]


# ....................... #
# What the report may not do: rank, re-sort, or invent a second availability


def test_options_keep_catalog_order() -> None:
    """RFC 0030 D2, against a catalog whose order is *not* alphabetical.

    ``gross_minus_tax`` before ``direct_net`` is the whole test: sorted, the
    pair reverses. Recipe order is authored — "ordered by reliability" — so a
    renderer or a projection that normalized it would destroy information while
    looking like it was tidying up.
    """
    sources = _with()
    sources["metrics"] = sources["metrics"] + LOOP_METRICS
    evidence = _evaluate(sources, _loop_catalog())
    (decision,) = [d for d in evidence.unresolved if d.canonical == "net_revenue"]
    assert [option.id for option in decision.options] == ["gross_minus_tax", "direct_net"]
    assert [option.id for option in decision.options] != sorted(
        option.id for option in decision.options
    )
    assert decision.options[0].requires == ("gross", "tax")
    assert decision.options[0].expr == "gross - tax"
    assert decision.options[1].expr is None


@pytest.mark.parametrize("name", spec_fixture_names())
def test_the_report_never_names_an_available_canonical(name: str) -> None:
    """One notion of availability, asserted rather than intended (§9).

    The report and ``unreachable`` are two readings of one graph. This is the
    check that fails the day a change gives the report its own idea of what is
    available — which is the shape §9's last risk names and the one a reader
    would otherwise have to take on trust.
    """
    project, catalog = load_fixture(name)
    evidence = evaluate(project, catalog=catalog, steps=registry_for(name))
    if evidence.stage_reached is Stage.RESOLVE:
        pytest.skip(f"{name} refuses before reachability is computed")
    available = available_canonicals(resolve(project, catalog).graph)
    for decision in evidence.unresolved:
        assert decision.canonical not in available, f"{name}: {decision.canonical}"
        assert decision.blocks, f"{name}: a decision nothing blocks is not work"
        blocked = {
            metric.name
            for metric in evidence.unreachable
            if decision.canonical in metric.missing
        }
        assert set(decision.blocks) == blocked, name


def test_the_sweep_has_something_to_look_at() -> None:
    """A guard on the sweep above: a corpus where nothing is open makes every
    assertion in it vacuous, and no failure says so.

    `ecom_basic` leaves `cogs` unmapped on purpose, so the corpus is a witness
    to the report — never its definition, which is what the built specs above
    are for.
    """
    found = [
        name
        for name in spec_fixture_names()
        for project, catalog in [load_fixture(name)]
        if evaluate(project, catalog=catalog, steps=registry_for(name)).unresolved
    ]
    assert "ecom_basic" in found, found


# ....................... #
# The shapes RFC 0030 does not name


def test_two_fields_linking_one_canonical_name_the_first() -> None:
    """`logs/T-0007.md` D-032, and the measurement it rests on.

    Nothing refuses an entity carrying the same ``canonical:`` on two fields —
    reference validation checks that the entity matches the catalog's and never
    compares two fields with each other — so §5.3's "one does, and `entity`/
    `field` name it" has two candidates. Mapping *either* closes the gap, so the
    entry names one edit rather than choosing between unequal options, and which
    one it names is fixed by sort order rather than by document order.
    """
    sources = _with(
        field=LINKED + '      alt_cogs: {type: "decimal(12,4)", canonical: cogs}\n'
    )
    evidence = _evaluate(sources)
    assert evidence.stage_reached is Stage.COMPLETE, evidence.refusals
    (decision,) = evidence.unresolved
    assert (decision.gap, decision.field) == (Gap.UNMAPPED, "alt_cogs")
    # Declared second and named first: the answer is the sort, not the file.
    assert sources["entity_model"].index("cogs:") < sources["entity_model"].index("alt_cogs:")


def _catalog_without_cogs_recipes() -> Catalog:
    """`ecom_basic`'s catalog with `cogs` stripped of its one recipe."""
    text = (FIXTURES / "ecom_basic" / "catalog.yaml").read_text()
    stripped = text.replace(
        """    recipes:
      - {id: direct, requires: [cogs]}""",
        "",
    )
    assert stripped != text
    return load_catalog(stripped)


def test_a_canonical_with_no_recipes_is_still_an_open_decision() -> None:
    """An empty ``options`` is a fact about the **catalog**, never about data.

    It says the catalog declares no derivation for that field — not that the
    source lacks the paths, which bloomery cannot know, having read none. The
    entry still names its edit, so it is still work.
    """
    evidence = _evaluate(_with(field=LINKED), _catalog_without_cogs_recipes())
    (decision,) = evidence.unresolved
    assert decision.options == ()
    assert decision.blocks == ("margin",)


def test_the_table_says_so_when_the_catalog_offers_nothing() -> None:
    """The rendered row for that state: an empty column would read as a
    formatting bug, and "(no recipes)" reads as the answer it is."""
    from bloomery.cli.render import render_evidence

    rendered = render_evidence(_evaluate(_with(field=LINKED), _catalog_without_cogs_recipes()))
    row = next(line for line in rendered.splitlines() if line.strip().startswith("cogs"))
    assert row.split() == ["cogs", "unmapped", "order_item.cogs", "(no", "recipes)", "blocks:",
                           "margin"]


# ....................... #
# D9: an entry that cannot name one edit is not reported at all


def test_a_merged_entity_reports_no_open_decision() -> None:
    """RFC 0030 D9, and the one shape it withholds today.

    A merged entity's columns are per mapping (RFC 0024 D26), so a decision
    keyed on the canonical field cannot say which mapping document to edit —
    and an entry a caller cannot act on is a worklist item that never clears.
    What is withheld is the *entry*, never the gap: the metric blocked on it is
    still unreachable, by the machinery that already existed.
    """
    sources = _with()
    sources["mapping_order_items_legacy"] = sources["mapping_order_items"].replace(
        "source: shopify__order_lines", "source: legacy__order_lines"
    )
    evidence = _evaluate(sources)
    assert evidence.stage_reached is Stage.COMPLETE
    assert evidence.unresolved == ()
    assert [metric.name for metric in evidence.unreachable] == ["margin"]
    # The single-mapping form of the same spec does report it — otherwise this
    # asserts only that something, somewhere, went wrong.
    assert [d.canonical for d in _evaluate(_with()).unresolved] == ["cogs"]


def test_a_step_produced_relation_names_the_catalogs_entity() -> None:
    """`logs/T-0007.md` D-034 — the third place a canonical link can live.

    `identity_resolution` makes `customer_ref` available through its step
    wiring's ``canonical:`` block (RFC 0017 D49), not through any entity field.
    Remove that block and the decision is `UNLINKED`, naming the entity the
    catalog declares the field for — which is right, and is not where the edit
    goes. `customer` is a step output and is absent from the entity model
    entirely, so a reader following ``gap`` alone would open the wrong document;
    the how-to carries that third case, and this pins the value it describes.
    """
    sources = fixture_sources("identity_resolution")
    wiring = "    canonical:\n      customer: {canonical_id: customer_ref}\n"
    assert wiring in sources["steps"]
    sources["steps"] = sources["steps"].replace(wiring, "")
    project, catalog = load_project(sources), load_fixture("identity_resolution")[1]
    evidence = evaluate(project, catalog=catalog, steps=registry_for("identity_resolution"))
    (decision,) = evidence.unresolved
    assert (decision.canonical, decision.gap, decision.entity, decision.field) == (
        "customer_ref",
        Gap.UNLINKED,
        "customer",
        None,
    )
    assert decision.blocks == ("customer_count",)
    assert "customer" not in project.entity_model.entities, (
        "the entity is a step output — that is what makes the entity-model reading wrong here"
    )
