"""What `zone_in:` is cross-checked against at resolve time (RFC 0074 §5.2).

The key is a declaration, and P1 checks only what one field says about *itself*:
a zone on something that is not an instant, a zone that disagrees with the
chain's `to_utc`, and a zone with nothing converting out of it. The omission —
no declaration at all — is R018's, one commit later, where the draft can say
whether the value ever reaches a boundary.

Each of these is a detection branch: the feature working never runs one. They
exist because every one of them is a compile that would otherwise succeed while
the author believes a zone was handled.
"""

from __future__ import annotations

import pathlib

import pytest

from bloomery import build_project_ir, load_catalog, load_project
from bloomery.errors import ResolutionError
from bloomery.spec import Catalog
from bloomery.steps import StepManifest, StepRegistry

pytestmark = pytest.mark.unit

FIXTURE = pathlib.Path(__file__).parents[2] / "fixtures" / "period_over_period"
PARSED = 'booked_at: {from: "$.booked_at", transform: [{parse_ts: ISO8601}], zone_in: UTC}'


def _sources() -> dict[str, str]:
    return {
        path.stem: path.read_text()
        for path in sorted(FIXTURE.glob("*.yaml"))
        if path.stem != "catalog"
    }


def _catalog() -> Catalog:
    return load_catalog((FIXTURE / "catalog.yaml").read_text())


def _build(booked_at: str = PARSED):
    sources = _sources()
    assert PARSED in sources["mapping"], "the line every test below edits has moved"
    sources["mapping"] = sources["mapping"].replace(PARSED, booked_at)
    return build_project_ir(load_project(sources), catalog=_catalog())


def _zone_of(ir, column: str = "booked_at") -> str | None:
    (entity,) = (entity for entity in ir.entities if entity.name == "sale")
    (source,) = entity.sources
    (field,) = (field for field in source.fields if field.target_field == column)
    return field.zone_in


# ....................... #


def test_the_fixture_builds_as_written() -> None:
    """The non-vacuity guard: every test below asserts something after editing
    one line, and an unedited fixture that did not build would make all of them
    pass for the wrong reason.

    The fixture declares `UTC` because R018 refuses it otherwise — its
    `booked_at` is bucketed by a date role — which is the rule working on the
    suite's own corpus rather than only on the case that motivated it.
    """

    assert _zone_of(_build()) == "UTC"


def test_a_declared_zone_reaches_the_ir() -> None:
    """P1's whole deliverable. Nothing reads it yet — R018 does, next commit —
    so the only thing that can be asserted here is that it survived the
    lowering, which is exactly the thing a later reader will assume."""

    ir = _build('booked_at: {from: "$.booked_at", transform: [{parse_ts: ISO8601}], zone_in: UTC}')

    assert _zone_of(ir) == "UTC"


def test_a_converting_chain_carries_its_own_zone_unchanged() -> None:
    """D4: `to_utc`'s argument is already the declaration, so a chain that
    converts needs no second key — and the field it did not write stays
    `None` rather than being back-filled from the chain.

    Back-filling would read as tidier and would cost the one distinction the
    IR is carrying: a zone the author stated, against one the compiler
    inferred from a step. R018 reads both, separately, and says so.
    """

    ir = _build(
        'booked_at: {from: "$.booked_at", '
        "transform: [{parse_ts: ISO8601}, {to_utc: America/New_York}]}"
    )

    assert _zone_of(ir) is None


def test_a_zone_agreeing_with_the_chain_is_allowed() -> None:
    """§5.2: the redundancy is *checked*, which is a different thing from
    refused. An author who wants the source's clock written where a reader
    will see it may say it twice, as long as the two agree."""

    ir = _build(
        'booked_at: {from: "$.booked_at", '
        "transform: [{parse_ts: ISO8601}, {to_utc: America/New_York}], "
        "zone_in: America/New_York}"
    )

    assert _zone_of(ir) == "America/New_York"


def test_a_zone_disagreeing_with_the_chain_is_refused() -> None:
    """The shape D4 exists to keep out: two statements of one fact. One of them
    is used and the other is read by a human, and nothing says which is
    right — so the refusal names both rather than picking."""

    with pytest.raises(ResolutionError) as excinfo:
        _build(
            'booked_at: {from: "$.booked_at", '
            "transform: [{parse_ts: ISO8601}, {to_utc: Europe/London}], "
            "zone_in: America/New_York}"
        )

    message = str(excinfo.value)

    assert "America/New_York" in message
    assert "Europe/London" in message
    assert excinfo.value.source_path == "mapping[shop__sales->sale]: fields.booked_at"


def test_a_non_utc_zone_with_nothing_converting_it_is_refused() -> None:
    """The declaration is right and the instant is still wrong. Worse than
    silence, because the document now reads as though somebody handled it."""

    with pytest.raises(ResolutionError) as excinfo:
        _build(
            'booked_at: {from: "$.booked_at", '
            "transform: [{parse_ts: ISO8601}], zone_in: America/New_York}"
        )

    assert "to_utc" in str(excinfo.value)


@pytest.mark.parametrize("zone", ["UTC", "Etc/UTC"])
def test_a_utc_zone_needs_no_conversion(zone: str) -> None:
    """D3, and the reason the key exists: `to_utc: UTC` converts nothing and
    nobody writes it, so a UTC feed has no step to hang its claim on. Both
    spellings, because the second is what the zone database files it as and
    refusing it would teach an author that the key wants a spelling."""

    assert _zone_of(_build(f'booked_at: {{from: "$.booked_at", zone_in: {zone}}}')) == zone


def test_a_zone_on_a_column_that_is_not_an_instant_is_refused() -> None:
    """Almost always the key on the wrong line — `sold_at` is a date beside a
    timestamp. A date has no instant to get wrong at a boundary (§4), so a zone
    on one is a fact about nothing."""

    sources = _sources()
    sold = 'sold_at: {from: "$.sold_at", transform: [{parse_date: ISO8601}]}'
    assert sold in sources["mapping"]
    sources["mapping"] = sources["mapping"].replace(
        sold, 'sold_at: {from: "$.sold_at", transform: [{parse_date: ISO8601}], zone_in: UTC}'
    )

    with pytest.raises(ResolutionError) as excinfo:
        build_project_ir(load_project(sources), catalog=_catalog())

    assert "date" in str(excinfo.value)
    assert excinfo.value.source_path == "mapping[shop__sales->sale]: fields.sold_at"


# ....................... #
# The chain this cannot read (RFC 0017 D51)


MACRO_ENTITY_MODEL = """
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [event_id]
    fields:
      event_id: {type: string, required: true}
      seen_at: {type: timestamp}
"""


def _macro_registry() -> StepRegistry:
    """A macro that converts, spelled as a macro so the chain cannot be read.

    Its body is what `to_utc` lowers to, which is the point: the author has
    done the right thing through a surface the cross-check cannot see into.
    """

    manifest = StepManifest.model_validate(
        {
            "ref": "to_ny",
            "version": 1,
            "kind": "sql_macro",
            "determinism": "pure",
            "runtime_lock": "sha256:beef",
            "accepts": {"ts": "timestamp"},
            "outputs": {
                "value": {"grain": "row", "key": ["v"], "produces": {"v": {"type": "timestamp"}}}
            },
        }
    )
    return StepRegistry(
        {("to_ny", 1): manifest},
        macro_bodies={("to_ny", 1): "(:ts AT TIME ZONE 'America/New_York')"},
    )


def _build_with_macro(chain: str):
    project = load_project(
        {
            "entity_model": MACRO_ENTITY_MODEL,
            "mapping": (
                "mapping_version: 1\ntarget: event\nsource: bronze.app__events\n"
                'key:\n  event_id: {from: "$.id"}\n'
                f"fields:\n  seen_at: {chain}\n"
            ),
        }
    )
    return build_project_ir(project, steps=_macro_registry())


def test_a_step_link_exempts_the_field_from_the_conversion_check() -> None:
    """A spliced `sql_macro` may hold the conversion this cannot see, so the
    third refusal stands down where the chain carries one.

    The exemption is deliberately one-sided. A refusal a correct project cannot
    satisfy is the kind this design cannot afford — the author's only escape
    would be dropping the declaration, which is the outcome the RFC exists to
    prevent. R018 keeps the pressure from the other side: the same field with
    no declaration at all is refused where it is consumed.
    """

    ir = _build_with_macro(
        '{from: "$.seen_at", transform: [{parse_ts: ISO8601}, {step: to_ny@1}], '
        "zone_in: America/New_York}"
    )
    (entity,) = (entity for entity in ir.entities if entity.name == "event")
    (field,) = (f for f in entity.sources[0].fields if f.target_field == "seen_at")

    assert field.zone_in == "America/New_York"


def test_the_same_chain_without_the_step_link_is_refused() -> None:
    """The other half of the exemption, and what stops it reading as a hole:
    what the check stands down for is the *opaque link*, not the declaration.
    Remove the link and the identical `zone_in:` is refused."""

    with pytest.raises(ResolutionError, match="to_utc"):
        _build_with_macro(
            '{from: "$.seen_at", transform: [{parse_ts: ISO8601}], zone_in: America/New_York}'
        )


# ....................... #
# The key half


def test_a_key_fields_declaration_reaches_the_ir_and_is_cross_checked() -> None:
    """A key is a strange place for a timestamp, and the walk reaches it
    anyway — `currency_in:`'s argument (D-158): a declaration the key half
    cannot make is one an author has to restructure an entity to state, and a
    key column flattened as a date role is read for its position like any
    other.

    Both directions in one test on purpose: the carriage and the refusal come
    from a single call, so a key path that silently returned `None` would pass
    a test that only asserted the refusal.
    """

    model = """
spec_version: 1
entities:
  event:
    grain: one row per event
    key: [seen_at]
    fields:
      seen_at: {type: timestamp, required: true}
      payload: {type: string}
"""
    mapping = """
mapping_version: 1
source: app__events
target: event
key:
  seen_at: {from: "$.seen_at", transform: [{parse_ts: ISO8601}], zone_in: UTC}
fields:
  payload: {from: "$.payload"}
"""
    ir = build_project_ir(load_project({"entity_model": model, "mapping": mapping}))
    (entity,) = ir.entities
    (field,) = (f for f in entity.sources[0].fields if f.target_field == "seen_at")

    assert field.zone_in == "UTC"

    with pytest.raises(ResolutionError, match="disagrees with the chain"):
        build_project_ir(
            load_project(
                {
                    "entity_model": model,
                    "mapping": mapping.replace(
                        "transform: [{parse_ts: ISO8601}], zone_in: UTC",
                        "transform: [{parse_ts: ISO8601}, {to_utc: Europe/London}], zone_in: UTC",
                    ),
                }
            )
        )


@pytest.mark.parametrize(
    ("declared", "converted"),
    [("Etc/UTC", "UTC"), ("UTC", "Etc/UTC")],
    ids=["declared-Etc/UTC", "converted-Etc/UTC"],
)
def test_the_two_utc_spellings_agree_with_each_other(declared: str, converted: str) -> None:
    """One zone under two names is not two statements disagreeing (PR #126).

    `{to_utc: UTC}` is a conversion nobody needs to write, which is why the
    pair reads as exotic — but the cross-check exists to catch an author who
    said two different things, and these two say the same thing. Everything
    else stays compared as written, which is what `to_utc` itself does: its
    argument reaches SQL verbatim.
    """

    ir = _build(
        f'booked_at: {{from: "$.booked_at", '
        f"transform: [{{parse_ts: ISO8601}}, {{to_utc: {converted}}}], zone_in: {declared}}}"
    )

    assert _zone_of(ir) == declared
