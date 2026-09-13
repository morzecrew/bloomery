"""What a sensitive column may not do (RFC 0055 D9–D11).

Classification composes with `grants`, not with `redact`. The superseded D4
refused `pii` on any mapped field whose path was not redacted — and a mapped
field's path *cannot* be redacted, so every legal spelling was refused at once
(`logs/T-0050.md`). These are the three tiers that replaced it, and each test
is named for which of them it exercises: a contradiction the compiler can
always see, a contradiction it can see only when both sides speak, and a
question it cannot answer at all.
"""

from __future__ import annotations

import pytest

from bloomery import build_project_ir, evaluate, load_catalog, load_project
from bloomery.errors import AudienceWidened, GuardrailError, SecretPublished
from bloomery.evidence import AdvisoryCode
from support.compiling import FIXTURES, fixture_sources

pytestmark = pytest.mark.unit


def sources(
    *,
    classification: str = "pii",
    entity_grants: str | None = None,
    mart_grants: str | None = None,
) -> dict[str, str]:
    """`ecom_basic` with the annotations this module varies.

    Built from the corpus fixture rather than a hand-written project because
    the walk under test is mart provenance: `order.customer_id` flattens into
    `order_items` as `order_customer_id`, so a test on an inline two-field spec
    would exercise a lookup that never has to trace anything.
    """
    src = dict(fixture_sources("ecom_basic"))

    src["entity_model"] = src["entity_model"].replace(
        "classification: pii", f"classification: {classification}", 1
    )

    if entity_grants is not None:
        src["entity_model"] = src["entity_model"].replace(
            "    owner: commerce-platform@example.com\n",
            f"    owner: commerce-platform@example.com\n    grants: {{select: [{entity_grants}]}}\n",
            1,
        )

    if mart_grants is not None:
        src["marts"] = src["marts"].replace(
            "    owner: analytics@example.com\n",
            f"    owner: analytics@example.com\n    grants: {{select: [{mart_grants}]}}\n",
            1,
        )

    return src


def catalog():  # noqa: ANN201 — Catalog is a handle
    return load_catalog((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())


def build(**kwargs: object):  # noqa: ANN201 — ProjectIR
    return build_project_ir(load_project(sources(**kwargs)), catalog())  # type: ignore[arg-type]


# ....................... #
# D10 — the contradiction that is always visible


def test_a_secret_column_in_a_mart_is_refused() -> None:
    """A published relation is the one thing `secret` says the column is not
    part of. Two authored statements that cannot both hold."""
    with pytest.raises(GuardrailError) as excinfo:
        build(classification="secret")

    (refusal,) = [e for e in excinfo.value.collected if isinstance(e, SecretPublished)]
    assert refusal.source_path == "marts: marts.order_items"
    assert "classified secret" in str(refusal)
    assert "order_customer_id" in str(refusal)


@pytest.mark.parametrize(
    ("entity_grants", "mart_grants"),
    [(None, None), ("analyst", "analyst"), ("analyst", "analyst, everyone")],
    ids=["ungranted", "equal", "widened"],
)
def test_secret_is_refused_whatever_is_granted(
    entity_grants: str | None, mart_grants: str | None
) -> None:
    """Unconditional (D10). It does not depend on redaction, on quarantine, or
    on anything being granted — including the case where the grants would have
    been fine, which is the one a reader most expects to slip through."""
    with pytest.raises(GuardrailError) as excinfo:
        build(classification="secret", entity_grants=entity_grants, mart_grants=mart_grants)

    assert any(isinstance(e, SecretPublished) for e in excinfo.value.collected)


def test_one_column_produces_at_most_one_classification_refusal() -> None:
    """A `secret` column whose grants *also* widen is refused once, for being
    secret.

    Both rules match here, and the second is a second answer to a settled
    question: the author fixes the classification and the widening refusal
    would vanish with it. Asserted because dropping the `continue` that holds
    this passed every other test in this module — a `secret` column was still
    refused, just twice.
    """
    with pytest.raises(GuardrailError) as excinfo:
        build(classification="secret", entity_grants="analyst", mart_grants="analyst, everyone")

    classification_refusals = [
        e for e in excinfo.value.collected if isinstance(e, SecretPublished | AudienceWidened)
    ]
    assert len(classification_refusals) == 1
    assert isinstance(classification_refusals[0], SecretPublished)


# ....................... #
# D11 — the contradiction that needs both sides to speak


def test_a_pii_column_in_a_mart_granted_wider_than_its_entity_is_refused() -> None:
    """The leak this exists for: a customer table flattened into a wide mart,
    and the mart granted to someone the entity does not admit."""
    with pytest.raises(GuardrailError) as excinfo:
        build(entity_grants="analyst", mart_grants="analyst, everyone")

    (refusal,) = [e for e in excinfo.value.collected if isinstance(e, AudienceWidened)]
    assert refusal.source_path == "marts: marts.order_items"
    assert "everyone" in str(refusal)
    # The role the entity *does* grant is not named as a problem — the message
    # reports the difference, not the mart's whole grant list.
    assert "select to everyone" in str(refusal)


@pytest.mark.parametrize(
    ("entity_grants", "mart_grants"),
    [
        ("analyst", "analyst"),
        ("analyst, everyone", "analyst"),
        ("analyst", ""),
    ],
    ids=["equal", "narrower", "mart grants nobody"],
)
def test_an_audience_no_wider_than_its_source_is_not_refused(
    entity_grants: str, mart_grants: str
) -> None:
    """Strict superset, and nothing looser. Equal passes, narrower passes, and
    `{select: []}` — no role at all — is the narrowest thing there is."""
    build(entity_grants=entity_grants, mart_grants=mart_grants)


def test_an_unclassified_column_is_never_refused_however_wide_the_grant() -> None:
    """The control that says the guard reads the classification rather than
    the grants. `order_items` carries plenty of unclassified columns, and the
    mart here is granted to a role the entity does not."""
    build(classification="public", entity_grants="analyst", mart_grants="analyst, everyone")


# ....................... #
# D11 — the question the compiler cannot answer


@pytest.mark.parametrize(
    ("entity_grants", "mart_grants"),
    [(None, None), ("analyst", None), (None, "analyst")],
    ids=["neither declares", "only the entity", "only the mart"],
)
def test_an_undeclared_audience_advises_rather_than_refuses(
    entity_grants: str | None, mart_grants: str | None
) -> None:
    """An absent `grants:` block means bloomery has no opinion and the
    warehouse's own grants stand (D6) — unknown rather than wider.

    Refusing it would refuse every project managing its gold grants outside
    bloomery, so it is an advisory: legal spec, correct artifacts, and
    something the author would want to know (RFC 0033 D7).
    """
    evidence = evaluate(
        load_project(sources(entity_grants=entity_grants, mart_grants=mart_grants)),
        catalog=catalog(),
    )

    advisories = [a for a in evidence.advisories if a.code is AdvisoryCode.UNDECLARED_AUDIENCE]
    (advisory,) = advisories
    assert advisory.source_path == "marts: marts.order_items"
    assert "no grants: block says who may read it" in advisory.message
    assert "legal and the artifacts are correct" in advisory.message

    # ...and it is an advisory *instead of*, not *as well as*, a refusal.
    build(entity_grants=entity_grants, mart_grants=mart_grants)


def test_declaring_both_sides_silences_the_advisory() -> None:
    """The advisory's whole content is "nobody said" — so saying it, on both
    sides, must remove it rather than leave a permanent nag."""
    evidence = evaluate(
        load_project(sources(entity_grants="analyst", mart_grants="analyst")),
        catalog=catalog(),
    )

    assert not [a for a in evidence.advisories if a.code is AdvisoryCode.UNDECLARED_AUDIENCE]


def test_a_project_with_no_classified_column_advises_nothing() -> None:
    """The corpus fixture without the annotation. A guard that fired on every
    project would be a guard nobody keeps."""
    src = dict(fixture_sources("ecom_basic"))
    src["entity_model"] = src["entity_model"].replace(", classification: pii", "")
    src["entity_model"] = src["entity_model"].replace(", classification: internal", "")

    evidence = evaluate(load_project(src), catalog=catalog())
    assert not [a for a in evidence.advisories if a.code is AdvisoryCode.UNDECLARED_AUDIENCE]


# ....................... #
# The relation kinds


def test_a_rollup_is_a_published_relation_too() -> None:
    """A rollup has no `columns` of its own — `keep` names its parent's — so
    it is reached one hop through the parent mart. Without that hop a
    classified column would escape both refusals by being rolled up, which is
    how the reject table escaped its grant one PR ago.

    `order_items_monthly` keeps `order_customer_id`, which traces to
    `order.customer_id` — so classifying that column is a `secret` in a
    rollup as well as in the parent mart, and both are refused.
    """
    src = dict(fixture_sources("rollup_mart"))
    src["entity_model"] = src["entity_model"].replace(
        "      customer_id: {type: string}",
        "      customer_id: {type: string, classification: secret}",
        1,
    )
    assert "classification: secret" in src["entity_model"], "the fixture's shape moved"

    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(load_project(src), catalog())

    refused = {
        e.source_path for e in excinfo.value.collected if isinstance(e, SecretPublished)
    }
    assert refused == {"marts: marts.order_items", "marts: rollups.order_items_monthly"}


def test_a_rollup_that_drops_the_column_is_not_refused() -> None:
    """The other half of the one hop: `keep` filters. A column the parent
    carries and the rollup groups away is genuinely gone from the rollup's
    relation, so the rollup must not be refused for it — and this is the
    assertion that says the walk filters rather than passing the parent's
    whole column set through.
    """
    src = dict(fixture_sources("rollup_mart"))
    src["entity_model"] = src["entity_model"].replace(
        "      line_no: {type: int, required: true}",
        "      line_no: {type: int, required: true, classification: secret}",
        1,
    )
    src["marts"] = src["marts"].replace(
        "    keep: [order_customer_id, ordered_month]", "    keep: [ordered_month]", 1
    )

    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(load_project(src), catalog())

    refused = {
        e.source_path for e in excinfo.value.collected if isinstance(e, SecretPublished)
    }
    assert refused == {"marts: marts.order_items"}


def test_a_rollups_grants_are_emitted_at_both_sql_targets() -> None:
    """D12: a rollup declares its own audience, so it needs its own emission.

    Without it the key would parse, satisfy the guardrail's comparison, and
    reach no artifact — a restriction an author wrote and no warehouse ever
    applies, which is the shape of the reject-table hole this branch's
    predecessor shipped.
    """
    src = dict(fixture_sources("rollup_mart"))
    src["marts"] = src["marts"].replace(
        "    keep: [order_customer_id, ordered_month]",
        "    grants: {select: [analyst]}\n    keep: [order_customer_id, ordered_month]",
        1,
    )
    rollup_catalog = load_catalog((FIXTURES / "rollup_mart" / "catalog.yaml").read_text())
    loaded = load_project(src)

    from bloomery import compile_project  # noqa: PLC0415 — one call site

    sqlmesh = {
        a.path: a.content
        for a in compile_project(loaded, target="sqlmesh", dialect="duckdb", catalog=rollup_catalog)
    }
    assert (
        'grants ("select" = (\'analyst\'))'
        in sqlmesh["models/gold/mart_order_items_monthly.sql"]
    )

    import yaml  # noqa: PLC0415 — one call site

    dbt = {
        a.path: a.content
        for a in compile_project(loaded, target="dbt", dialect="duckdb", catalog=rollup_catalog)
    }
    entries = {e["name"]: e for e in yaml.safe_load(dbt["models/schema.yml"])["models"]}
    assert entries["mart_order_items_monthly"]["config"] == {"grants": {"select": ["analyst"]}}


def test_a_rollup_does_not_inherit_its_parents_grants() -> None:
    """D12 is D2's rule at the one authored node that had no audience.

    A rollup over a restricted mart is *not* restricted until it says so —
    the opposite of an entity's `<entity>__reject` table, which does inherit,
    because a reject table is generated rather than authored. The consequence
    is visible: the parent's grant reaches an artifact and the rollup's
    relation carries none.
    """
    src = dict(fixture_sources("rollup_mart"))
    src["marts"] = src["marts"].replace(
        "  order_items:\n", "  order_items:\n    grants: {select: [analyst]}\n", 1
    )
    rollup_catalog = load_catalog((FIXTURES / "rollup_mart" / "catalog.yaml").read_text())

    from bloomery import compile_project  # noqa: PLC0415 — one call site

    emitted = {
        a.path: a.content
        for a in compile_project(
            load_project(src), target="sqlmesh", dialect="duckdb", catalog=rollup_catalog
        )
    }
    assert "grants" in emitted["models/gold/mart_order_items.sql"]
    assert "grants" not in emitted["models/gold/mart_order_items_monthly.sql"]


def test_a_column_a_measure_is_computed_from_is_covered() -> None:
    """`MartIR.columns` is the flattened schema, not the dimension list, so a
    column that only feeds a measure is published like any other.

    Pinned because the guard's docstring claims it and the claim is easy to
    get wrong in the other direction: a reader thinking in Cube terms would
    expect `unit_price` — an input to `gross_revenue` — to be a measure rather
    than a column, and would not expect it here.
    """
    src = dict(fixture_sources("ecom_basic"))
    src["entity_model"] = src["entity_model"].replace(
        '      unit_price: {type: "decimal(12,4)", canonical: unit_price}',
        '      unit_price: {type: "decimal(12,4)", canonical: unit_price, classification: secret}',
        1,
    )
    assert "classification: secret" in src["entity_model"], "the fixture's shape moved"

    with pytest.raises(GuardrailError) as excinfo:
        build_project_ir(load_project(src), catalog())

    refused = [e for e in excinfo.value.collected if isinstance(e, SecretPublished)]
    assert any("unit_price" in str(e) for e in refused)


def test_a_classified_column_no_relation_publishes_is_left_alone() -> None:
    """The annotation is legal on a column that never leaves silver — that is
    where a sensitive column is *declared*, and refusing it there would refuse
    the vocabulary for existing."""
    model = """\
spec_version: 1
entities:
  customer:
    grain: one row per customer
    key: [customer_id]
    fields:
      customer_id: {type: string, required: true}
      ssn: {type: string, classification: secret}
"""
    mapping = """\
mapping_version: 1
target: customer
source: raw__customers
key:
  customer_id: {from: "$.id"}
fields:
  ssn: {from: "$.ssn"}
"""
    ir = build_project_ir(load_project({"entity_model": model, "mapping": mapping}))
    assert [c.classification for c in ir.entities[0].columns if c.name == "ssn"] == ["secret"]


def test_an_entity_granting_nobody_still_refuses_a_wider_mart() -> None:
    """`{select: []}` on the entity is the narrowest audience there is, so any
    role the mart grants is strictly wider. The boundary case the subset
    comparison is most likely to get wrong, because both sides are declared and
    one of them is empty."""
    with pytest.raises(GuardrailError) as excinfo:
        build(entity_grants="", mart_grants="analyst")

    (refusal,) = [e for e in excinfo.value.collected if isinstance(e, AudienceWidened)]
    assert "select to analyst" in str(refusal)


def test_disjoint_grant_sets_are_refused() -> None:
    """A set difference, not a superset test.

    The entity grants `analyst` and the mart grants `contractor`: neither set
    contains the other, so a "strict superset" reading says this passes. It
    must not — `contractor` can read the mart and cannot read the entity, which
    is the whole leak, and every prose description of this rule said the wrong
    thing until a reviewer read the code against it (PR #113 review).
    """
    with pytest.raises(GuardrailError) as excinfo:
        build(entity_grants="analyst", mart_grants="contractor")

    (refusal,) = [e for e in excinfo.value.collected if isinstance(e, AudienceWidened)]
    assert "select to contractor" in str(refusal)
    # ...and the role the entity grants is not reported as a problem.
    assert "analyst" not in str(refusal).split("select to", 1)[1]


def test_a_secret_column_is_refused_without_also_being_advised_about() -> None:
    """RFC 0033 D7: an advisory standing where a refusal belongs is a defect.

    A `secret` column with no grants was collecting both `SecretPublished` and
    an `undeclared_audience` advisory whose text reads "This is legal and the
    artifacts are correct" — beside a refusal saying it is not. The advisory is
    about `pii` alone, because a `secret` column's audience is not a question:
    it must not be published at all.
    """
    evidence = evaluate(load_project(sources(classification="secret")), catalog=catalog())

    assert [type(r).__name__ for r in evidence.refusals] == ["SecretPublished"]
    assert not [a for a in evidence.advisories if a.code is AdvisoryCode.UNDECLARED_AUDIENCE]


def test_cube_refuses_a_granted_rollup() -> None:
    """D5 reaches every node kind that can carry grants.

    Cube refused an entity's and a mart's and never looked at rollups, so a
    project granting only a rollup compiled here with the restriction silently
    dropped — which is the degradation the refusal exists to prevent, walked
    straight back in by adding a third node kind and updating two of the three
    places that read one (PR #113 review).
    """
    from bloomery import compile_project  # noqa: PLC0415 — one call site
    from bloomery.errors import UnsupportedByTarget  # noqa: PLC0415

    src = dict(fixture_sources("rollup_mart"))
    src["marts"] = src["marts"].replace(
        "    keep: [order_customer_id, ordered_month]",
        "    grants: {select: [analyst]}\n    keep: [order_customer_id, ordered_month]",
        1,
    )
    rollup_catalog = load_catalog((FIXTURES / "rollup_mart" / "catalog.yaml").read_text())

    with pytest.raises(UnsupportedByTarget, match="rollup 'order_items_monthly'"):
        compile_project(
            load_project(src), target="cube", dialect="duckdb", catalog=rollup_catalog
        )
