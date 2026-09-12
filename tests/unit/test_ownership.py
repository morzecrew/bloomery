"""`owner` on an entity, a mart and a metric (RFC 0055 §5.1).

One value authored on a spec node, carried through the IR unchanged, and
written into whichever metadata slot the target has. The tests are organised by
the claim each makes rather than by target, because the claims are what the RFC
argues: it changes no SQL, it does not inherit, and it reaches the slot each
node actually has rather than a flat list of three.
"""

from __future__ import annotations

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
    plain = dict(fixture_sources("ecom_basic"))
    annotated = dict(plain)
    annotated["entity_model"] = annotated["entity_model"].replace(
        "  order_item:\n", "  order_item:\n    owner: BLOOMERY_OWNER_MARKER\n", 1
    )
    annotated["marts"] = annotated["marts"].replace(
        "marts:\n  order_items:", "marts:\n  order_items:\n    owner: BLOOMERY_OWNER_MARKER", 1
    )

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
    plain = dict(fixture_sources("ecom_basic"))
    annotated = dict(plain)
    annotated["marts"] = annotated["marts"].replace(
        "marts:\n  order_items:", "marts:\n  order_items:\n    owner: BLOOMERY_OWNER_MARKER", 1
    )

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
    sources = dict(fixture_sources("ecom_basic"))
    sources["marts"] = sources["marts"].replace(
        "marts:\n  order_items:", "marts:\n  order_items:\n    owner: analytics", 1
    )
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    loaded = load_project(sources)

    sqlmesh = {
        a.path: a.content
        for a in compile_project(loaded, target="sqlmesh", dialect="duckdb", catalog=catalog)
    }
    assert "owner 'analytics'" in sqlmesh["models/gold/mart_order_items.sql"]

    dbt = {
        a.path: a.content
        for a in compile_project(loaded, target="dbt", dialect="duckdb", catalog=catalog)
    }
    entries = yaml.safe_load(dbt["models/schema.yml"])["models"]
    assert {"name": "mart_order_items", "meta": {"owner": "analytics"}} in entries

    cube = {
        a.path: a.content
        for a in compile_project(loaded, target="cube", dialect="duckdb", catalog=catalog)
    }
    document = yaml.safe_load(cube["model/cubes/order_items.yml"])
    assert document["cubes"][0]["meta"] == {"owner": "analytics"}


def test_a_metric_owner_reaches_cube_alone() -> None:
    """A metric has no SQLMesh model and no dbt schema entry of its own, so a
    Cube measure's `meta` is the only owner slot it has."""
    sources = dict(fixture_sources("ecom_basic"))
    sources["metrics"] = sources["metrics"].replace(
        "  gross_revenue:\n    template: gross_revenue",
        "  gross_revenue:\n    template: gross_revenue\n    owner: metrics-guild",
        1,
    )
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    loaded = load_project(sources)

    cube = {
        a.path: a.content
        for a in compile_project(loaded, target="cube", dialect="duckdb", catalog=catalog)
    }
    measures = yaml.safe_load(cube["model/cubes/order_items.yml"])["cubes"][0]["measures"]
    revenue = next(m for m in measures if m["name"] == "gross_revenue")
    assert revenue["meta"]["owner"] == "metrics-guild"

    for target in ("sqlmesh", "dbt"):
        emitted = compile_project(loaded, target=target, dialect="duckdb", catalog=catalog)
        assert not any("metrics-guild" in a.content for a in emitted)


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
    sources["entity_model"] = sources["entity_model"].replace(
        "  order_item:\n", "  order_item:\n    owner: ingestion\n", 1
    )
    catalog = load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    ir = build_project_ir(load_project(sources), catalog)

    assert next(e for e in ir.entities if e.name == "order_item").owner == "ingestion"
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
