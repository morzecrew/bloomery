"""`owner` on an entity, a mart and a metric (RFC 0055 §5.1).

One value authored on a spec node, carried through the IR unchanged, and
written into whichever metadata slot the target has. The tests are organised by
the claim each makes rather than by target, because the claims are what the RFC
argues: it changes no SQL, it does not inherit, and it reaches the slot each
node actually has rather than a flat list of three.
"""

from __future__ import annotations

import re

import pytest
import yaml

from bloomery import build_project_ir, compile_project, load_catalog, load_project
from support.compiling import FIXTURES, fixture_sources

pytestmark = pytest.mark.unit

def entity_model(owner: str | None) -> str:
    """The one-entity model, with or without the annotation.

    Assembled rather than templated with `.format`, because the spec body is
    full of YAML flow mappings and doubling every brace to escape them makes
    the fixture unreadable and the un-formatted branch wrong.
    """
    declared = f"    owner: {owner}\n" if owner is not None else ""
    return (
        "spec_version: 1\n"
        "entities:\n"
        "  event:\n"
        "    grain: one row per event\n"
        "    key: [event_id]\n"
        f"{declared}"
        "    fields:\n"
        "      event_id: {type: string, required: true}\n"
        "      kind: {type: string}\n"
    )

MAPPING = """\
mapping_version: 1
target: event
source: raw__events
key:
  event_id: {from: "$.id"}
fields:
  kind: {from: "$.kind"}
"""


#: The corpus's flagship project now *carries* the three annotations, so a test
#: that needs an un-annotated baseline has to make one rather than assume the
#: fixture is plain. That assumption is what broke when the annotations landed
#: in `ecom_basic`, and it broke loudly only because YAML refuses a duplicate
#: key — a fixture gaining an annotation the other way round would have made
#: these comparisons quietly compare nothing.
_ANNOTATION_LINE = re.compile(r"^ *(owner|grants|classification):.*\n( +select:.*\n)?", re.M)
_INLINE_CLASSIFICATION = re.compile(r", classification: [a-z]+")


def unannotated(sources: dict[str, str]) -> dict[str, str]:
    """The same project with every RFC 0055 annotation taken back out.

    Asserted to have removed something: a stripper that silently matches
    nothing turns every before/after comparison below into a comparison of a
    project with itself, which passes and proves nothing.
    """
    # Only the documents this RFC annotates. `owner:` is not its word alone —
    # a dbt exposure has carried a *required* one since RFC 0056, and stripping
    # that made the project unloadable rather than un-annotated.
    annotated_kinds = {"entity_model", "marts", "metrics"}
    stripped = {
        name: _INLINE_CLASSIFICATION.sub("", _ANNOTATION_LINE.sub("", text))
        if name in annotated_kinds
        else text
        for name, text in sources.items()
    }
    assert stripped != sources, "the corpus fixture carries no annotation to strip"
    return stripped


def _sql_body(content: str) -> str:
    """An emitted file with everything that is not SQL taken off the front.

    Two things, and both have to go or the comparison fails for a reason that
    is not SQL: the fingerprint header, which moves for any IR change at all,
    and SQLMesh's `MODEL (...)` envelope, which is exactly where the owner is
    supposed to appear. dbt models carry the header and no envelope, so the
    envelope split is conditional rather than assumed — splitting on a `);`
    that is not there would have left dbt's header in and failed on the
    fingerprint.
    """
    body = "\n".join(
        line for line in content.splitlines() if not line.startswith("-- fingerprint:")
    )
    return body.split(");", 1)[1] if body.startswith("-- Generated") and ");" in body else body


def project(owner: str | None = "analytics-team"):  # noqa: ANN201 — Project is a handle
    return load_project({"entity_model": entity_model(owner), "mapping": MAPPING})


def artifacts(target: str, owner: str | None = "analytics-team") -> dict[str, str]:
    return {
        artifact.path: artifact.content
        for artifact in compile_project(project(owner), target=target, dialect="duckdb")
    }


# ....................... #
# It changes no SQL (D1)


def test_an_owner_moves_no_select() -> None:
    """D1, as a test rather than a sentence.

    The whole claim of this RFC is that three annotations reach metadata slots
    and nothing else. Asserted on the SELECT half of the emitted model —
    everything after the `MODEL (...)` envelope — because the envelope is
    exactly where the owner is *supposed* to appear, so comparing whole files
    would pass for the wrong reason.
    """
    with_owner = artifacts("sqlmesh")["models/silver/event.sql"]
    without = artifacts("sqlmesh", owner=None)["models/silver/event.sql"]

    assert with_owner.split(");", 1)[1] == without.split(");", 1)[1]
    assert "owner 'analytics-team'" in with_owner
    assert "owner" not in without.split(");", 1)[0]


# Cube is absent deliberately: it emits no SQL at all, so a SQL comparison
# there compares nothing — which the emptiness assertion below caught rather
# than passing quietly on an empty dict.
@pytest.mark.parametrize("target", ["sqlmesh", "dbt"])
def test_the_annotation_moves_no_sql_anywhere_in_a_project(target: str) -> None:
    """The other half of D1, over a whole project rather than one entity.

    D1's words are that an existing golden's *SQL* is byte-identical with the
    annotations absent, so that is what is compared: every emitted SQL body,
    with the fingerprint header and the `MODEL (...)` envelope excluded, since
    the envelope is where the owner is supposed to appear and the header moves
    for any IR change at all.

    Not a grep for the word "owner": dbt exposures have carried a required
    `owner:` key since RFC 0056, so "no artifact mentions an owner" is already
    false on this corpus and would pass for the wrong reason.
    """
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    annotated = dict(fixture_sources("ecom_basic"))
    plain = unannotated(annotated)

    def sql_bodies(sources: dict[str, str]) -> dict[str, str]:
        emitted = compile_project(
            load_project(sources), target=target, dialect="duckdb", catalog=catalog
        )
        return {a.path: _sql_body(a.content) for a in emitted if a.path.endswith(".sql")}

    before, after = sql_bodies(plain), sql_bodies(annotated)

    assert before.keys() == after.keys(), "an annotation added or removed a SQL artifact"
    assert before == after
    assert before, "no SQL artifact was compared — the filter matched nothing"


@pytest.mark.parametrize("target", ["sqlmesh", "dbt", "cube"])
def test_the_annotation_removes_nothing(target: str) -> None:
    """The direction the comparison above cannot see.

    Metadata is additive by construction, so the failure worth catching is a
    line that *disappeared* — a `meta:` block overwriting one a target already
    wrote, say. Every line of every artifact without the annotation must still
    be there with it.
    """
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    annotated = dict(fixture_sources("ecom_basic"))
    plain = unannotated(annotated)

    def lines(sources: dict[str, str]) -> dict[str, list[str]]:
        return {
            a.path: [line for line in a.content.splitlines() if "fingerprint:" not in line]
            for a in compile_project(
                load_project(sources), target=target, dialect="duckdb", catalog=catalog
            )
        }

    before, after = lines(plain), lines(annotated)

    for path in sorted(before):
        assert [line for line in before[path] if line not in after[path]] == [], path


# ....................... #
# It reaches the slot each node has


def test_an_entity_owner_reaches_sqlmesh_and_dbt() -> None:
    """Two slots, not three: Cube emits no entities at all, so there is no
    third object for an entity's owner to land on."""
    model = artifacts("sqlmesh")["models/silver/event.sql"]
    assert "owner 'analytics-team'" in model

    schema = yaml.safe_load(artifacts("dbt")["models/schema.yml"])
    assert schema["models"] == [{"name": "event", "meta": {"owner": "analytics-team"}}]


def test_an_entity_with_no_quality_rules_still_gets_a_schema_file() -> None:
    """`models/schema.yml` was emitted only for entities carrying audits, so
    this entity — which declares no quality rule — had no file at all, and an
    owner on it would have had nowhere to go (logs/T-0050.md)."""
    assert "models/schema.yml" in artifacts("dbt")

    without_owner = artifacts("dbt", owner=None)
    # ...and the file still does not exist when there is neither, which is what
    # says the gate was widened rather than removed.
    assert "models/schema.yml" not in without_owner


def test_a_mart_owner_reaches_all_three_targets() -> None:
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    loaded = load_project(fixture_sources("ecom_basic"))
    declared = "analytics@example.com"

    sqlmesh = {
        a.path: a.content
        for a in compile_project(loaded, target="sqlmesh", dialect="duckdb", catalog=catalog)
    }
    assert f"owner '{declared}'" in sqlmesh["models/gold/mart_order_items.sql"]

    dbt = {
        a.path: a.content
        for a in compile_project(loaded, target="dbt", dialect="duckdb", catalog=catalog)
    }
    entries = yaml.safe_load(dbt["models/schema.yml"])["models"]
    assert {"name": "mart_order_items", "meta": {"owner": declared}} in entries

    cube = {
        a.path: a.content
        for a in compile_project(loaded, target="cube", dialect="duckdb", catalog=catalog)
    }
    document = yaml.safe_load(cube["model/cubes/order_items.yml"])
    assert document["cubes"][0]["meta"] == {"owner": declared}


def test_a_metric_owner_reaches_cube_alone() -> None:
    """A metric has no SQLMesh model and no dbt schema entry of its own, so a
    Cube measure's `meta` is the only owner slot it has."""
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    loaded = load_project(fixture_sources("ecom_basic"))
    declared = "finance-reporting@example.com"

    cube = {
        a.path: a.content
        for a in compile_project(loaded, target="cube", dialect="duckdb", catalog=catalog)
    }
    measures = yaml.safe_load(cube["model/cubes/order_items.yml"])["cubes"][0]["measures"]
    revenue = next(m for m in measures if m["name"] == "gross_revenue")
    assert revenue["meta"]["owner"] == declared

    for target in ("sqlmesh", "dbt"):
        emitted = compile_project(loaded, target=target, dialect="duckdb", catalog=catalog)
        assert not any(declared in a.content for a in emitted)


def test_the_reject_table_carries_its_entity_owner() -> None:
    """The reject model is the same entity's second artifact rather than a
    second node, so carrying the owner there is not the inheritance D2
    refuses."""
    model = """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    owner: analytics-team
    quarantine: {retention: 90d}
    dedupe: {keep: latest_by, field: _ingested_at, tie_break: [_load_id]}
    fields:
      event_id: {type: string, required: true}
      kind: {type: string, required: true}
"""
    mapping = """\
mapping_version: 1
target: event
source: raw__events
key:
  event_id: {from: "$.id"}
fields:
  kind: {from: "$.kind"}
unmapped: ["$._ingested_at", "$._load_id", "$._source_row_id"]
"""
    emitted = {
        a.path: a.content
        for a in compile_project(
            load_project({"entity_model": model, "mapping": mapping}),
            target="sqlmesh",
            dialect="duckdb",
        )
    }
    reject = next(content for path, content in emitted.items() if "reject" in path)
    assert "owner 'analytics-team'" in reject


# ....................... #
# What it does not do


def test_an_owner_is_not_inherited_by_a_mart(): # noqa: ANN201
    """D2. A mart over an owned entity has no owner of its own — silent
    inheritance makes an owner nobody wrote look like one somebody did."""
    sources = dict(fixture_sources("ecom_basic"))
    # The entity keeps its owner; the mart's is taken away. A mart over an
    # owned entity must then have *none* — not the entity's.
    sources["marts"] = _ANNOTATION_LINE.sub("", sources["marts"])
    assert sources["marts"] != fixture_sources("ecom_basic")["marts"]

    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    ir = build_project_ir(load_project(sources), catalog)

    owned = next(e for e in ir.entities if e.name == "order")
    assert owned.owner == "commerce-platform@example.com"
    assert all(mart.owner is None for mart in ir.marts)


def test_an_owner_is_not_merged_from_a_metric_template() -> None:
    """The other inheritance this codebase has, which D2 does not mention.

    `description` merges from a catalog template; an owner must not, for D2's
    own reason at the other edge — a template is instantiated many times, so an
    owner it carried would appear on every instantiation as an owner nobody
    wrote. `MetricTemplate` therefore has no `owner` key, and a document that
    writes one is refused rather than silently ignored.
    """
    from bloomery.errors import SpecParseError

    catalog_text = (FIXTURES / "ecom_basic" / "catalog.yaml").read_text().replace(
        "  gross_revenue:\n    requires: [unit_price, quantity]",
        "  gross_revenue:\n    owner: nobody\n    requires: [unit_price, quantity]",
        1,
    )
    with pytest.raises(SpecParseError) as excinfo:
        load_catalog(catalog_text)
    # The field is in the source path; pydantic's message for an unknown key is
    # "Extra inputs are not permitted" and names nothing.
    assert excinfo.value.source_path == "catalog: metric_templates.gross_revenue.owner"


def test_an_owner_is_any_string_a_project_spells_it_as() -> None:
    """D8: no spelling rule. The awkward one is the case that matters — an
    apostrophe is legal in a name and would end a SQL string literal early, so
    it is the emitted quoting that has to hold rather than a validator."""
    model = artifacts("sqlmesh", owner="\"o'brien@example.com\"")["models/silver/event.sql"]
    assert "owner 'o''brien@example.com'" in model


# ....................... #
# `classification` (RFC 0055 §5.2)


CLASSIFIED_MODEL = """\
spec_version: 1
entities:
  customer:
    grain: one row per customer
    key: [customer_id]
    fields:
      customer_id: {type: string, required: true}
      email: {type: string, classification: pii}
      segment: {type: string, classification: internal}
"""

CLASSIFIED_MAPPING = """\
mapping_version: 1
target: customer
source: raw__customers
key:
  customer_id: {from: "$.id"}
fields:
  email: {from: "$.email"}
  segment: {from: "$.segment"}
"""


def classified(target: str) -> dict[str, str]:
    return {
        a.path: a.content
        for a in compile_project(
            load_project({"entity_model": CLASSIFIED_MODEL, "mapping": CLASSIFIED_MAPPING}),
            target=target,
            dialect="duckdb",
        )
    }


@pytest.mark.parametrize("value", ["tag", "PII", "confidential", "secrets"])
def test_the_vocabulary_is_closed(value: str) -> None:
    """D3. An open string is a tag that means whatever its writer meant, and
    the routing — Cube's `public: false` — is what makes this more than a
    `meta:` passthrough. The near-misses are the cases worth pinning: `PII` in
    the wrong case is the mistake an author actually makes."""
    from bloomery.errors import SpecParseError

    with pytest.raises(SpecParseError) as excinfo:
        load_project(
            {
                "entity_model": CLASSIFIED_MODEL.replace("classification: pii", f"classification: {value}"),
                "mapping": CLASSIFIED_MAPPING,
            }
        )
    assert excinfo.value.source_path == (
        "entity_model: entities.customer.fields.email.classification"
    )


def test_a_classification_reaches_a_dbt_column_entry() -> None:
    schema = yaml.safe_load(classified("dbt")["models/schema.yml"])
    assert schema["models"] == [
        {
            "name": "customer",
            "columns": [
                {"name": "email", "meta": {"classification": "pii"}},
                {"name": "segment", "meta": {"classification": "internal"}},
            ],
        }
    ]


def test_a_classified_column_that_also_has_tests_is_one_entry() -> None:
    """Two reasons for a column to appear and one list to appear in. Two
    entries for one column is a duplicate key as far as dbt is concerned, and
    the second silently wins."""
    # An `assert:` clause rather than `required: true`: a required field emits
    # no dbt *column* test at all, so the obvious spelling of this test passed
    # with an entry that had nothing to collide with.
    model = CLASSIFIED_MODEL.replace(
        "      email: {type: string, classification: pii}",
        "      email: {type: string, classification: pii, assert: {not_null: true}}",
    )
    emitted = {
        a.path: a.content
        for a in compile_project(
            load_project({"entity_model": model, "mapping": CLASSIFIED_MAPPING}),
            target="dbt",
            dialect="duckdb",
        )
    }
    columns = yaml.safe_load(emitted["models/schema.yml"])["models"][0]["columns"]
    email = [column for column in columns if column["name"] == "email"]
    assert len(email) == 1
    assert email[0]["meta"] == {"classification": "pii"}
    assert email[0]["data_tests"] == ["not_null"]


def test_sqlmesh_carries_no_classification() -> None:
    """SQLMesh has no per-column metadata slot — `description`, `tags` and
    `column_descriptions`, none of them a key-value per column. Writing the
    value into `column_descriptions` would put a routing value into a field
    people read as prose; the honest emission is none (logs/T-0050.md)."""
    assert not any("classification" in content for content in classified("sqlmesh").values())


def test_pii_and_secret_leave_cubes_api_surface_and_internal_does_not() -> None:
    """§5.2's one target-native consumer. `public: false` removes the member
    from what Cube serves without removing it from the relation — and
    `internal` is deliberately still served, because "internal" is a statement
    about who should read a column, not one Cube can enforce."""
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    emitted = {
        a.path: a.content
        for a in compile_project(
            load_project(fixture_sources("ecom_basic")),
            target="cube",
            dialect="duckdb",
            catalog=catalog,
        )
    }
    dimensions = yaml.safe_load(emitted["model/cubes/order_items.yml"])["cubes"][0]["dimensions"]
    by_name = {d["name"]: d for d in dimensions}

    # The flattened column, traced back through the mart's provenance to
    # `order.customer_id` — a mart renames it, so this is also the assertion
    # that the lookup follows provenance rather than matching on a name.
    assert by_name["order_customer_id"]["public"] is False
    assert by_name["order_customer_id"]["meta"]["classification"] == "pii"
    assert all("public" not in d for name, d in by_name.items() if name != "order_customer_id")


def test_a_classification_does_not_remove_the_column_from_the_relation() -> None:
    """`public: false` is Cube's API surface, not the warehouse. The column is
    still selected — a classification that dropped it would be masking, which
    §4 refuses in as many words."""
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    emitted = {
        a.path: a.content
        for a in compile_project(
            load_project(fixture_sources("ecom_basic")),
            target="sqlmesh",
            dialect="duckdb",
            catalog=catalog,
        )
    }
    assert "order_customer_id" in emitted["models/gold/mart_order_items.sql"]


def test_a_classified_column_no_mart_projects_has_no_cube_surface() -> None:
    """Stated rather than discovered: Cube emits no entities, so a column that
    never becomes a mart dimension has nothing there to be removed from. Its
    classification still reaches dbt."""
    assert "model/cubes" not in " ".join(classified("cube"))
    assert "classification" in classified("dbt")["models/schema.yml"]


# ....................... #
# `grants` (RFC 0055 §5.3)


def granted(target: str, select: str = "[analyst]") -> dict[str, str]:
    model = entity_model(None).replace(
        "    fields:\n", f"    grants: {{select: {select}}}\n    fields:\n", 1
    )
    return {
        a.path: a.content
        for a in compile_project(
            load_project({"entity_model": model, "mapping": MAPPING}),
            target=target,
            dialect="duckdb",
        )
    }


def test_grants_reach_sqlmesh_in_a_form_sqlmesh_reads_back() -> None:
    """Asserted by loading the emitted block through SQLMesh rather than by
    matching text.

    The permission name has to be *quoted*: `select` is a SQL keyword, so
    `grants (select = (...))` — the spelling SQLMesh's own examples suggest —
    is a SQLGlot parse error before SQLMesh ever sees it. A text assertion
    would have passed on the broken spelling.
    """
    from sqlglot import parse
    from sqlmesh.core.model import load_sql_based_model

    content = granted("sqlmesh", "[analyst, \"role o'brien\"]")["models/silver/event.sql"]
    model = load_sql_based_model(parse(content, read="duckdb"), dialect="duckdb")
    assert model.grants == {"select": ["analyst", "role o'brien"]}


def test_grants_reach_a_dbt_model_config() -> None:
    schema = yaml.safe_load(granted("dbt")["models/schema.yml"])
    assert schema["models"] == [{"name": "event", "config": {"grants": {"select": ["analyst"]}}}]


def test_an_empty_grant_list_is_not_an_absent_block() -> None:
    """D6, at both targets that apply grants.

    `{select: []}` says no role may select; no block at all says bloomery has
    no opinion and the warehouse's grants stand. Emitting the first as the
    second would revoke nothing while looking like it did — so the emitted
    artifacts have to keep them apart, and SQLMesh's own reader is what says
    whether they do: `{}` for an empty grant against `None` for absence.
    """
    from sqlglot import parse
    from sqlmesh.core.model import load_sql_based_model

    empty = granted("sqlmesh", "[]")["models/silver/event.sql"]
    assert load_sql_based_model(parse(empty, read="duckdb"), dialect="duckdb").grants == {
        "select": []
    }

    absent = artifacts("sqlmesh", owner=None)["models/silver/event.sql"]
    assert load_sql_based_model(parse(absent, read="duckdb"), dialect="duckdb").grants is None

    assert yaml.safe_load(granted("dbt", "[]")["models/schema.yml"])["models"] == [
        {"name": "event", "config": {"grants": {"select": []}}}
    ]


def test_a_grants_block_with_no_select_is_refused() -> None:
    """`select` is required rather than defaulted, so `grants: {}` cannot
    become a third state meaning neither "no opinion" nor "no role"."""
    from bloomery.errors import SpecParseError

    model = entity_model(None).replace("    fields:\n", "    grants: {}\n    fields:\n", 1)
    with pytest.raises(SpecParseError) as excinfo:
        load_project({"entity_model": model, "mapping": MAPPING})
    assert excinfo.value.source_path == "entity_model: entities.event.grants.select"


def test_the_reject_table_carries_its_entity_grants() -> None:
    """Sharper than the owner case: a reject row is this entity's data that
    failed a rule, so a reject table left open while the silver table is closed
    publishes exactly the rows an author restricted."""
    model = """\
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    grants: {select: [analyst]}
    quarantine: {retention: 90d}
    dedupe: {keep: latest_by, field: _ingested_at, tie_break: [_load_id]}
    fields:
      event_id: {type: string, required: true}
      kind: {type: string, required: true}
"""
    mapping = """\
mapping_version: 1
target: event
source: raw__events
key:
  event_id: {from: "$.id"}
fields:
  kind: {from: "$.kind"}
unmapped: ["$._ingested_at", "$._load_id", "$._source_row_id"]
"""
    emitted = {
        a.path: a.content
        for a in compile_project(
            load_project({"entity_model": model, "mapping": mapping}),
            target="sqlmesh",
            dialect="duckdb",
        )
    }
    reject = next(content for path, content in emitted.items() if "reject" in path)
    assert 'grants ("select" = (\'analyst\'))' in reject


@pytest.mark.parametrize("node", ["entity", "mart"])
def test_cube_refuses_grants_rather_than_dropping_them(node: str) -> None:
    """D5. Cube reads relations it does not own, so a grant there would be a
    restriction in a file that restricts nothing — and dropping it silently
    would let a project believe a restriction it declared is in force on every
    target it compiles for.

    Both node kinds, because an entity has no cube of its own: a per-cube check
    would pass a project whose silver relations are restricted and say nothing.
    """
    from bloomery.errors import UnsupportedByTarget

    sources = dict(fixture_sources("ecom_basic"))
    if node == "entity":
        sources["entity_model"] = sources["entity_model"].replace(
            "  order_item:\n", "  order_item:\n    grants: {select: [analyst]}\n", 1
        )
    else:
        sources["marts"] = sources["marts"].replace(
            "marts:\n  order_items:", "marts:\n  order_items:\n    grants: {select: [analyst]}", 1
        )
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())

    with pytest.raises(UnsupportedByTarget, match="which Cube cannot apply"):
        compile_project(load_project(sources), target="cube", dialect="duckdb", catalog=catalog)

    # ...and the targets that do apply them still compile, which is what says
    # the refusal is Cube's rather than a project-wide ban.
    for target in ("sqlmesh", "dbt"):
        compile_project(load_project(sources), target=target, dialect="duckdb", catalog=catalog)


# ....................... #
# Seeds (D7)


@pytest.mark.parametrize(
    "written", ["seeds:\n  countries: {}\n", "seeds:\n", "seeds: []\n"], ids=["mapping", "bare", "list"]
)
def test_seeds_are_refused_by_name(written: str) -> None:
    """A permanent refusal, not a gap — and the message has to say so.

    Every value, including none at all: `seeds:` with nothing after it is still
    someone asking for seeds, and typing the field as `... | None` would have
    sent that spelling down the `None` branch without running the validator.
    """
    from bloomery.errors import SpecParseError

    with pytest.raises(SpecParseError) as excinfo:
        load_project({"entity_model": f"spec_version: 1\n{written}entities: {{}}\n"})

    assert excinfo.value.source_path == "entity_model: seeds"
    assert "refused, permanently, and not missing" in str(excinfo.value)
    assert "RFC 0003" in str(excinfo.value)


def test_a_project_without_seeds_is_unaffected() -> None:
    """The control for a key that exists only to refuse: its presence in the
    model must not make an ordinary document harder to write."""
    assert load_project({"entity_model": entity_model(None), "mapping": MAPPING}) is not None
