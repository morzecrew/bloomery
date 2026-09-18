"""Reading a MetricFlow semantic manifest into relationships (S-0075/the-mapping-field-by-field, S-0075/tests).

Every manifest here is hand-authored, and §3 of that document says why it has
to be: bloomery's own MetricFlow output is emitted per *mart*, so compiling
`ecom_basic` produces one semantic model carrying `('order', 'foreign', …)` and
no model declaring `order` as primary. The pairs an importer reads come from a
project that declares one semantic model per source table, which is what a
Semantic Layer project looks like and what these build.

The suite is one test per row of the mapping table plus the two that matter
most and are not rows: that the block the importer prints **loads back** into
the project it was read against, and that a relationship it produced lowers the
grade a strict consumer reads. An importer whose output does not load is one
whose refusals are all beside the point.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from bloomery import build_project_ir, load_project
from bloomery.errors import ArtifactImportError
from bloomery.guardrails import evidence as guard
from bloomery.imports import metricflow_relationships, render
from support.compiling import fixture_sources, load_fixture

pytestmark = pytest.mark.unit

#: The project every case is read against: two entities, `order` and
#: `order_item`, and one declared `many_to_one` between them.
_FIXTURE = "ecom_basic"

#: What the two semantic models in most cases are called, mapped onto the two
#: entities the fixture declares. Spelled differently from the entities on
#: purpose — that difference is the ordinary case (`logs/T-0056.md`), and a
#: suite whose models happened to match would never exercise the map.
_MAP = {"order_items": "order_item", "orders": "order"}


def _manifest(*models: dict[str, object]) -> str:
    """A semantic manifest carrying ``models`` and nothing else.

    The empty collections are not padding: `PydanticSemanticManifest` requires
    every one of them, so a manifest built without them fails to parse for a
    reason that has nothing to do with the case under test.
    """

    return json.dumps(
        {
            "semantic_models": list(models),
            "metrics": [],
            "project_configuration": {"time_spine_table_configurations": []},
            "interpreted_apis": [],
            "saved_queries": [],
            "semantic_version": None,
        }
    )


def _model(name: str, *entities: dict[str, object]) -> dict[str, object]:
    return {
        "name": name,
        "node_relation": {"alias": name, "schema_name": "analytics"},
        "entities": list(entities),
        "measures": [],
        "dimensions": [],
    }


def _element(name: str, kind: str, expr: str | None = None) -> dict[str, object]:
    element: dict[str, object] = {"name": name, "type": kind}
    if expr is not None:
        element["expr"] = expr
    return element


def _project():
    return load_project(fixture_sources(_FIXTURE))


def _import(manifest: str, *, entities: dict[str, str] | None = None, project=None):
    return metricflow_relationships(
        manifest,
        _project() if project is None else project,
        artifact="semantic_manifest.json",
        entities=_MAP if entities is None else entities,
    )


def _messages(error: ArtifactImportError) -> list[str]:
    """Every refusal in an aggregate, or the one that was raised alone."""

    return [str(one) for one in (error.collected or (error,))]


# ....................... #
# The pair, and what it is made of


def test_a_foreign_and_a_primary_element_become_one_many_to_one() -> None:
    """§5.2's first four rows, together: the pairing carries the cardinality and
    both halves are authored in the artifact."""

    (relationship,) = _import(
        _manifest(
            _model("order_items", _element("customer", "foreign", "order_id")),
            _model("customers", _element("customer", "primary", "customer_id")),
        ),
        entities={"order_items": "order_item", "customers": "order"},
    )

    assert relationship.from_ == "order_item"
    assert relationship.to == "order"
    assert relationship.via == {"order_id": "customer_id"}
    assert relationship.cardinality == "many_to_one"
    assert relationship.imported_from == "metricflow:semantic_manifest.json"


def test_the_endpoints_are_the_models_and_never_the_elements() -> None:
    """The mistake §5.1 exists to prevent, asserted rather than trusted.

    A semantic model is the relation and an entity element is a join identity
    several models share. Reading the element names as endpoints produces a
    relationship between two things bloomery has no name for, and it does so
    silently — both spellings are strings, and `resolve` would refuse the
    result with a message about the spec rather than about this.
    """

    (relationship,) = _import(
        _manifest(
            _model("order_items", _element("customer", "foreign", "order_id")),
            _model("customers", _element("customer", "primary", "customer_id")),
        ),
        entities={"order_items": "order_item", "customers": "order"},
    )

    assert "customer" not in (relationship.from_, relationship.to)


def test_unique_is_a_target_exactly_as_primary_is() -> None:
    """Both assert at most one row per value, which is the whole of what
    `many_to_one` needs on the to-side (§5.2)."""

    (relationship,) = _import(
        _manifest(
            _model("order_items", _element("customer", "foreign", "order_id")),
            _model("customers", _element("customer", "unique", "customer_id")),
        ),
        entities={"order_items": "order_item", "customers": "order"},
    )

    assert relationship.to == "order"


def test_natural_imports_nothing_and_a_valid_pair_beside_it_still_imports() -> None:
    """Asserted positively rather than by its absence from a count (§6).

    `natural` is MetricFlow's marker for a key that is *not* unique, so no
    cardinality follows from it. A test that only counted one relationship
    would pass equally if `natural` had been read as a target and the pair
    dropped.
    """

    (relationship,) = _import(
        _manifest(
            _model(
                "order_items",
                _element("bucket", "natural", "line_no"),
                _element("customer", "foreign", "order_id"),
            ),
            _model("customers", _element("customer", "primary", "customer_id")),
            _model("buckets", _element("bucket", "natural", "line_no")),
        ),
        entities={"order_items": "order_item", "customers": "order"},
    )

    assert (relationship.from_, relationship.to) == ("order_item", "order")


# ....................... #
# The refusals, one per row


def test_a_foreign_element_no_model_declares_unique_refuses() -> None:
    with pytest.raises(ArtifactImportError) as caught:
        _import(_manifest(_model("order_items", _element("customer", "foreign", "order_id"))))

    message = str(caught.value)
    assert "'customer'" in message
    assert "'order_items'" in message
    assert "no other model declares it primary or unique" in message


def test_two_models_declaring_one_primary_refuses_as_ambiguous() -> None:
    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model("order_items", _element("order", "foreign", "order_id")),
                _model("orders", _element("order", "primary", "order_id")),
                _model("archived_orders", _element("order", "primary", "order_id")),
            ),
            entities={"order_items": "order_item", "orders": "order", "archived_orders": "order"},
        )

    message = str(caught.value)
    assert "'archived_orders', 'orders'" in message, "both claimants are named"
    assert "ambiguous" in message


@pytest.mark.parametrize(
    ("source_expr", "target_expr", "named"),
    [
        (None, "order_id", "order_items"),
        ("order_id", None, "orders"),
    ],
    ids=["source", "target"],
)
def test_a_missing_expr_refuses_naming_the_side_that_is_missing_it(
    source_expr: str | None, target_expr: str | None, named: str
) -> None:
    """Either side, because the join needs a column on both and only one of
    them is the element the loop is looking at."""

    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model("order_items", _element("order", "foreign", source_expr)),
                _model("orders", _element("order", "primary", target_expr)),
            )
        )

    assert any(f"{named!r} declares no expr" in one for one in _messages(caught.value))


def test_an_expr_that_is_an_expression_refuses() -> None:
    """A relationship joins columns and bloomery has nowhere to put a
    computation, so `lower(customer_id)` is refused rather than pasted into a
    `via:` that `resolve` would then reject as an unknown column."""

    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model("order_items", _element("order", "foreign", "lower(order_id)")),
                _model("orders", _element("order", "primary", "order_id")),
            )
        )

    assert "expression rather than a bare column name" in str(caught.value)


def test_a_model_naming_no_entity_this_project_declares_refuses() -> None:
    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model("order_items", _element("order", "foreign", "order_id")),
                _model("orders", _element("order", "primary", "order_id")),
            ),
            entities={},
        )

    messages = _messages(caught.value)
    assert any("--entity order_items=<entity>" in one for one in messages), (
        "the refusal names the flag that fixes it"
    )


def test_an_entity_flag_naming_no_model_in_the_artifact_refuses() -> None:
    """A typo in the map is caught against the artifact rather than ignored.

    Silently accepting it would leave the model it was meant for unmapped, and
    the refusal the author then reads would be about that model rather than
    about the flag they mistyped.
    """

    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(_model("orders", _element("order", "primary", "order_id"))),
            entities={"ordrs": "order"},
        )

    assert "names no semantic model in this artifact" in str(caught.value)


def test_an_entity_flag_naming_no_entity_in_the_project_refuses() -> None:
    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model("order_items", _element("order", "foreign", "order_id")),
                _model("orders", _element("order", "primary", "order_id")),
            ),
            entities={"order_items": "order_item", "orders": "nonesuch"},
        )

    assert any("'nonesuch'" in one for one in _messages(caught.value))


def test_an_unreadable_artifact_refuses_rather_than_crashing() -> None:
    """A caller handed us a file, so a file that is not a manifest is a refusal
    and not a bug in bloomery — which is the difference between exit 1 and
    exit 3."""

    with pytest.raises(ArtifactImportError) as caught:
        _import("{ not json")

    assert "not a readable MetricFlow semantic manifest" in str(caught.value)


def test_an_element_declared_primary_and_foreign_in_one_model_is_not_its_own_target() -> None:
    """The library accepts a model carrying `E` as both, so the case is
    reachable rather than theoretical.

    Counting the model's own declaration would produce a relation joined to
    itself on one column — every row matching itself — and would turn "nothing
    declares this unique" into a self-join instead of a refusal.
    """

    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model(
                    "order_items",
                    _element("order", "primary", "order_id"),
                    _element("order", "foreign", "order_id"),
                )
            ),
            entities={"order_items": "order_item"},
        )

    assert "no other model declares it primary or unique" in str(caught.value)


def test_every_refusal_is_collected_rather_than_only_the_first() -> None:
    """An import is a bulk operation, and fixing a manifest one message per run
    is the experience batching exists to prevent (S-0019/source-paths)."""

    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model(
                    "order_items",
                    _element("customer", "foreign", "order_id"),
                    _element("promo", "foreign", "quantity"),
                )
            ),
            entities={"order_items": "order_item"},
        )

    assert len(caught.value.collected) == 2


# ....................... #
# Against what the project already says (§5.4, D4)


def test_a_relationship_the_project_already_declares_identically_is_not_returned() -> None:
    """Two statements that agree are not a contradiction (D4), and returning it
    would ask the author to paste a duplicate `resolve` then refuses by name."""

    assert (
        _import(
            _manifest(
                _model("order_items", _element("order", "foreign", "order_id")),
                _model("orders", _element("order", "primary", "order_id")),
            )
        )
        == ()
    )


def test_rendering_nothing_is_empty_rather_than_an_empty_block() -> None:
    """`render` is public and its empty case is the one the command hits
    whenever the project already says everything the artifact does.

    Empty text rather than `relationships:` over an empty list: the output is
    pasted, and pasting a second `relationships:` key into a document that has
    one is a duplicate key rather than a no-op.
    """

    assert render(()) == ""


def test_a_cardinality_disagreement_on_the_same_join_refuses_naming_both() -> None:
    """Same `(from, to, via)`, different cardinality: neither side wins by
    default, because "declared is more true" quietly overwrites a mechanically
    verified fact with an authored guess (S-0057/D-4)."""

    sources = fixture_sources(_FIXTURE)
    sources["entity_model"] = sources["entity_model"].replace(
        "    cardinality: many_to_one", "    cardinality: one_to_one", 1
    )
    assert "one_to_one" in sources["entity_model"], "the fixture stopped spelling it this way"

    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model("order_items", _element("order", "foreign", "order_id")),
                _model("orders", _element("order", "primary", "order_id")),
            ),
            project=load_project(sources),
        )

    message = str(caught.value)
    assert "'one_to_one'" in message
    assert "'many_to_one'" in message
    assert "'item_of_order'" in message


def test_a_generated_name_colliding_with_a_declared_one_refuses() -> None:
    """A name is a key (row 10), so renaming around an author's choice would be
    this module deciding which of two spellings of one edge wins."""

    sources = fixture_sources(_FIXTURE)
    sources["entity_model"] = sources["entity_model"].replace(
        "  - name: item_of_order", "  - name: order_item__order", 1
    )

    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model("order_items", _element("customer", "foreign", "order_id")),
                _model("customers", _element("customer", "primary", "customer_id")),
            ),
            entities={"order_items": "order_item", "customers": "order"},
            project=load_project(sources),
        )

    assert "already a relationship in this project" in str(caught.value)


def test_two_edges_between_one_pair_of_entities_get_distinct_names() -> None:
    """`resolve` refuses two relationships of one name, so a manifest carrying
    two foreign elements onto one target must not produce two of one name."""

    first, second = _import(
        _manifest(
            _model(
                "order_items",
                _element("buyer", "foreign", "line_no"),
                _element("payer", "foreign", "quantity"),
            ),
            _model("parties", _element("buyer", "primary", "order_id")),
            _model("payers", _element("payer", "primary", "customer_id")),
        ),
        entities={"order_items": "order_item", "parties": "order", "payers": "order"},
    )

    assert first.name != second.name
    assert {first.name, second.name} == {
        "order_item__order__line_no_order_id",
        "order_item__order__quantity_customer_id",
    }


# ....................... #
# The two that are not rows


def test_the_rendered_block_loads_back_into_the_project_it_was_read_against() -> None:
    """The property §5.3's `imported.yaml` did not have (`logs/T-0056.md`).

    A project holds exactly one `EntityModel`, so a standalone document
    carrying a `relationships:` block is refused as an unknown kind without a
    version key and as a second entity model with one. What the importer prints
    is a *fragment* of the document the author already has, and this is the
    test that it still is one after rendering.
    """

    relationships = _import(
        _manifest(
            _model("order_items", _element("customer", "foreign", "order_id")),
            _model("customers", _element("customer", "primary", "customer_id")),
        ),
        entities={"order_items": "order_item", "customers": "order"},
    )
    sources = fixture_sources(_FIXTURE)
    sources["entity_model"] += "\n" + render(relationships).split("relationships:\n", 1)[1]

    reloaded = load_project(sources)
    pasted = {one.name: one for one in reloaded.entity_model.relationships}

    assert "order_item__order" in pasted
    assert pasted["order_item__order"].imported_from == "metricflow:semantic_manifest.json"


def test_an_imported_relationship_lowers_the_grade_a_strict_consumer_reads() -> None:
    """The producer, end to end (§6): a manifest in, and a refusal out that
    S-0070 shipped with no project able to trip it.

    The relationship the manifest states is the one the `order_items` mart
    flattens through, so marking it imported moves every column that hop
    carries to `ASSUMED` — and a mart asking for `locked` is refused, naming
    the artifact rather than telling the author to declare an edge that is
    already declared.
    """

    # The declared edge is taken out first, so the one the mart flattens
    # through is the one the artifact stated. Left in, the import correctly
    # returns nothing — the triple matches and D4 accepts agreement silently —
    # which is a different test, above.
    sources = fixture_sources(_FIXTURE)
    head, marker, _ = sources["entity_model"].partition("relationships:")
    assert marker, "the fixture stopped declaring relationships"
    sources["entity_model"] = head
    without = load_project(sources)

    relationships = _import(
        _manifest(
            _model("order_items", _element("order", "foreign", "order_id")),
            _model("orders", _element("order", "primary", "order_id")),
        ),
        project=without,
    )
    assert relationships, "the manifest states the edge the fixture no longer declares"

    sources["entity_model"] = head + render(relationships)
    # The mart's flatten step names the relationship it traverses, so adopting
    # an imported edge means repointing it — which is the real adoption step,
    # not a fixture convenience: a generated name is not the author's name.
    sources["marts"] = sources["marts"].replace("item_of_order", relationships[0].name)
    sources["marts"] = sources["marts"].replace(
        "    measures: [gross_revenue]",
        "    measures: [gross_revenue]\n    requires_evidence: locked",
        1,
    )

    strict = load_project(sources)
    relaxed_sources = dict(sources)
    relaxed_sources["marts"] = relaxed_sources["marts"].replace("locked", "assumed", 1)
    relaxed = load_project(relaxed_sources)
    _, catalog = load_fixture(_FIXTURE)

    errors = guard.check_evidence(strict, build_project_ir(relaxed, catalog))

    assert errors, "a mart asking for 'locked' over an imported hop is refused"
    # Every one, not just the first: the point is that the artifact is named
    # wherever the weakness is reported, because "declare the relationship" is
    # advice this author cannot act on — it is declared, by an importer.
    assert all("'metricflow:semantic_manifest.json'" in str(one) for one in errors)
    assert all(relationships[0].name in str(one) for one in errors)


# ....................... #
# Determinism (S-0020)


#: Two *source* models and two targets. A version of this with one source
#: model cannot fail when the model sort is removed — every edge comes from the
#: same iteration — which is what a sweep found it doing (`logs/T-0056.md`).
_TWO_MAP = {
    "order_items": "order_item",
    "orders": "order",
    "parties": "order",
    "payers": "order",
    "shippers": "order",
}


def test_the_order_of_models_and_elements_in_the_artifact_does_not_reach_the_output() -> None:
    """Nothing in MetricFlow orders a model's elements or a manifest's models,
    so an artifact regenerated upstream must not produce a different paste.

    Both axes in one test and both exercised: two models carry a ``foreign``
    element, so the model order changes which edge is found first, and one of
    them carries two so the element order does too.
    """

    forwards = _manifest(
        _model(
            "order_items",
            _element("buyer", "foreign", "line_no"),
            _element("shipper", "foreign", "quantity"),
        ),
        _model("orders", _element("payer", "foreign", "customer_id")),
        _model("parties", _element("buyer", "primary", "order_id")),
        _model("shippers", _element("shipper", "primary", "customer_id")),
        _model("payers", _element("payer", "primary", "order_id")),
    )
    backwards = _manifest(
        _model("payers", _element("payer", "primary", "order_id")),
        _model("shippers", _element("shipper", "primary", "customer_id")),
        _model("parties", _element("buyer", "primary", "order_id")),
        _model("orders", _element("payer", "foreign", "customer_id")),
        _model(
            "order_items",
            _element("shipper", "foreign", "quantity"),
            _element("buyer", "foreign", "line_no"),
        ),
    )

    one = render(_import(forwards, entities=_TWO_MAP))
    other = render(_import(backwards, entities=_TWO_MAP))

    assert one == other
    assert one.count("- name:") == 3, "every edge is in the value being compared"


def test_a_foreign_element_declared_only_natural_elsewhere_refuses() -> None:
    """`natural` imports nothing on the *target* side too, which is the half a
    test built from a `natural` element nobody points at cannot reach.

    MetricFlow's `natural` marks a key that is not unique. Admitting one as a
    target would produce a `many_to_one` whose to-side may repeat — an edge
    that determines nothing, arrived at by reading a type that says so.
    """

    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model("order_items", _element("customer", "foreign", "order_id")),
                _model("customers", _element("customer", "natural", "customer_id")),
            ),
            entities={"order_items": "order_item", "customers": "order"},
        )

    assert "no other model declares it primary or unique" in str(caught.value)


def test_a_refusal_stops_the_run_before_names_are_generated() -> None:
    """The mapping stage raises before the naming stage, so a reader is not
    handed a second finding derived from a half-resolved edge set.

    Here the project already declares `order_item__order`, which is the name the
    valid edge would generate — so without the stop, the same run reports both
    the unresolvable element *and* a name collision. Fixing the first changes
    the edge set, so the second may not be true once the manifest is corrected:
    it is a consequence of the broken state rather than a second problem.
    """

    sources = fixture_sources(_FIXTURE)
    sources["entity_model"] = sources["entity_model"].replace(
        "  - name: item_of_order", "  - name: order_item__order", 1
    )

    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model(
                    "order_items",
                    _element("customer", "foreign", "order_id"),
                    _element("dangling", "foreign", "quantity"),
                ),
                _model("customers", _element("customer", "primary", "customer_id")),
            ),
            entities={"order_items": "order_item", "customers": "order"},
            project=load_project(sources),
        )

    assert _messages(caught.value) == [one for one in _messages(caught.value) if "foreign" in one]
    assert not any("already a relationship in this project" in one for one in _messages(caught.value))


def test_the_rendered_block_is_byte_identical_across_processes_and_hash_seeds() -> None:
    """S-0020's claim, asked of the one surface this phase adds.

    In subprocesses rather than in this one: `PYTHONHASHSEED` is fixed at
    interpreter start, so a same-process loop compares a value to itself and
    reports success whatever the code does (`logs/T-0021.md`).
    """

    script = (
        "import json, sys;"
        "sys.path.insert(0, 'tests');"
        "from bloomery import load_project;"
        "from bloomery.imports import metricflow_relationships, render;"
        "from support.compiling import fixture_sources;"
        "manifest = sys.argv[1];"
        "project = load_project(fixture_sources('ecom_basic'));"
        "print(render(metricflow_relationships("
        "manifest, project, artifact='semantic_manifest.json',"
        " entities={'order_items': 'order_item', 'customers': 'order'})), end='')"
    )
    manifest = _manifest(
        _model("order_items", _element("customer", "foreign", "order_id")),
        _model("customers", _element("customer", "primary", "customer_id")),
    )

    rendered = {
        subprocess.run(  # noqa: S603 — fixed argv, no shell
            [sys.executable, "-c", script, manifest],
            check=True,
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        ).stdout
        for seed in ("0", "1", "12345", "random")
    }

    assert len(rendered) == 1
    assert "order_item__order" in rendered.pop()


# ....................... #
# Review round 1 — four findings, each red before its fix


def test_an_expr_with_a_trailing_newline_is_not_a_bare_column() -> None:
    """`$` matches before a final newline as well as at the end of the string,
    so an anchored `match` accepted `"order_id\\n"`.

    It reached `via` as a column name with a newline in it, which no entity
    declares and no reader would spot in the pasted block. The pattern is shared
    and read by pydantic elsewhere, so the fix is `fullmatch` here rather than a
    second spelling of the grammar.
    """

    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model("order_items", _element("customer", "foreign", "order_id\n")),
                _model("customers", _element("customer", "primary", "customer_id")),
            ),
            entities={"order_items": "order_item", "customers": "order"},
        )

    assert "expression rather than a bare column name" in str(caught.value)


def test_a_mapping_target_is_checked_even_for_a_model_that_builds_no_edge() -> None:
    """Checked lazily, a model carrying no `foreign` element never had its
    mapping looked at — so `--entity customers=nonesuch` was accepted in full
    whenever `customers` was only ever a target."""

    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(_model("customers", _element("customer", "primary", "customer_id"))),
            entities={"customers": "nonesuch"},
        )

    assert "names no entity this project declares" in str(caught.value)


def test_two_models_stating_one_join_produce_one_relationship() -> None:
    """Two semantic models can map to one entity, and then they state the same
    relationship twice.

    Collapsed rather than refused, on the rule that agreement is not a
    contradiction — and before naming, because both would otherwise widen to the
    same generated name and `render` would print a duplicate that `resolve`
    refuses by name.
    """

    (relationship,) = _import(
        _manifest(
            _model("order_items", _element("customer", "foreign", "order_id")),
            _model("line_items", _element("customer", "foreign", "order_id")),
            _model("customers", _element("customer", "primary", "customer_id")),
        ),
        entities={
            "order_items": "order_item",
            "line_items": "order_item",
            "customers": "order",
        },
    )

    assert relationship.name == "order_item__order"


@pytest.mark.parametrize(
    ("source_expr", "target_expr", "column", "entity"),
    [
        ("nonexistent_col", "customer_id", "nonexistent_col", "order_item"),
        ("order_id", "nonexistent_col", "nonexistent_col", "order"),
    ],
    ids=["from-side", "to-side"],
)
def test_a_join_column_the_mapped_entity_does_not_declare_refuses(
    source_expr: str, target_expr: str, column: str, entity: str
) -> None:
    """Being a bare identifier is not being a column this project has.

    Without the check the importer printed a block that parsed, pasted cleanly,
    and then refused at resolution — with a message about the author's own spec
    rather than about the artifact it came out of, which is the wrong file to
    send them to.
    """

    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model("order_items", _element("customer", "foreign", source_expr)),
                _model("customers", _element("customer", "primary", target_expr)),
            ),
            entities={"order_items": "order_item", "customers": "order"},
        )

    message = str(caught.value)
    assert f"{column!r}" in message
    assert f"entity {entity!r} does not declare" in message


#: A project whose two entities carry column names that make the generated
#: widening ambiguous: `order_id` + `_` + `x` and `order` + `_` + `id_x` are one
#: string. Hand-built rather than taken from the corpus, because no fixture has
#: a pair of columns shaped to collide and the collision is the whole case.
_COLLIDING_SOURCES = {
    "entity_model": """
spec_version: 1
entities:
  a:
    grain: one row per a
    key: [k]
    fields:
      k: {type: string}
      order_id: {type: string}
      order: {type: string}
  b:
    grain: one row per b
    key: [k]
    fields:
      k: {type: string}
      x: {type: string}
      id_x: {type: string}
""",
}


def test_two_joins_whose_generated_names_would_collide_refuse() -> None:
    """The widening is not injective and nothing downstream would notice.

    `{order_id: x}` and `{order: id_x}` are different joins between the same two
    entities, and the name built from each is `a__b__order_id_x`. Rendered, that
    is two relationships of one name — which `resolve` refuses by name, after the
    author has pasted it. No separator fixes it: every character a bare column
    name may hold is one it may also hold in the middle.
    """

    with pytest.raises(ArtifactImportError) as caught:
        _import(
            _manifest(
                _model(
                    "ma",
                    _element("p", "foreign", "order_id"),
                    _element("q", "foreign", "order"),
                ),
                _model("t1", _element("p", "primary", "x")),
                _model("t2", _element("q", "primary", "id_x")),
            ),
            entities={"ma": "a", "t1": "b", "t2": "b"},
            project=load_project(_COLLIDING_SOURCES),
        )

    message = str(caught.value)
    assert "would both be named 'a__b__order_id_x'" in message
    assert "'order_id': 'x'" in message
    assert "'order': 'id_x'" in message
