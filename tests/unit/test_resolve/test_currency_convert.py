"""What `convert` refuses at resolve time (RFC 0023 §5.4).

Every one of these is a detection branch — code that runs only when the bug it
detects is present — so none of them is exercised by the feature working. They
are here because the audit found them uncovered, and because each guards a
compile that would otherwise succeed and produce a wrong number rather than a
crash: an unmatched rate converts silently to NULL, and a NULL amount in a sum
is a total nobody can tell from a smaller one.

The happy path, the emitted SQL and the executed numbers live in
`test_emit/test_currency_convert.py` and `execution/test_currency_convert.py`.
"""

from __future__ import annotations

import pathlib

import pytest

from bloomery import build_project_ir, load_catalog, load_project
from bloomery.errors import ResolutionError
from bloomery.spec import Catalog

pytestmark = pytest.mark.unit

FIXTURE = pathlib.Path(__file__).parents[2] / "fixtures" / "currency_convert"
STEP = "{convert: [EUR, USD, paid_at]}"


def _sources() -> dict[str, str]:
    """The fixture's project documents (the catalog is loaded separately)."""

    return {
        path.stem: path.read_text()
        for path in sorted(FIXTURE.glob("*.yaml"))
        if path.stem != "catalog"
    }


def _catalog() -> Catalog:
    return load_catalog((FIXTURE / "catalog.yaml").read_text())


def _build(mapping_step: str = STEP) -> None:
    sources = _sources()
    sources["mapping"] = sources["mapping"].replace(STEP, mapping_step)
    build_project_ir(load_project(sources), catalog=_catalog())


def test_the_fixture_builds_as_written() -> None:
    """The non-vacuity guard. Every test below asserts a refusal after editing
    one thing; if the unedited fixture did not build, they would all pass for
    the wrong reason."""
    _build()


# ....................... #
# The currency codes


@pytest.mark.parametrize(
    ("step", "offender", "role"),
    [
        ("{convert: [eur, USD, paid_at]}", "eur", "from"),
        ("{convert: [EURO, USD, paid_at]}", "EURO", "from"),
        ("{convert: [EUR, usd, paid_at]}", "usd", "to"),
        ("{convert: [EUR, US, paid_at]}", "US", "to"),
    ],
)
def test_a_currency_code_that_is_not_iso_4217_is_refused(
    step: str, offender: str, role: str
) -> None:
    """The silent-NULL hole. A transform argument is an `ArgKind.STR` and never
    passes through the spec layer's `CurrencyCode` annotation, so `eur` and
    `EURO` reached the emitted predicate verbatim — where they matched no rate
    row and converted every amount to NULL. Nothing failed; the numbers were
    just gone."""
    with pytest.raises(ResolutionError) as excinfo:
        _build(step)
    message = str(excinfo.value)
    assert f"{offender!r} as its {role} currency" in message
    assert "convert every amount to NULL" in message


def test_converting_a_currency_to_itself_is_refused() -> None:
    """It converts nothing and still joins the rate relation, so it depends on
    a self-rate row existing — and turns the amount into NULL where one does
    not."""
    with pytest.raises(ResolutionError, match="converts nothing"):
        _build("{convert: [USD, USD, paid_at]}")


def test_converting_into_a_column_declared_as_another_currency_is_refused() -> None:
    """`amount_usd` is declared USD in the catalog. Producing GBP into it would
    leave the currency guardrail reasoning about the column in a currency it is
    not in — every check passes and the arithmetic is wrong."""
    with pytest.raises(ResolutionError) as excinfo:
        _build("{convert: [EUR, GBP, paid_at]}")
    assert "produces 'GBP'" in str(excinfo.value)
    assert "declared 'USD'" in str(excinfo.value)


# ....................... #
# The anchor


def test_an_anchor_the_entity_does_not_declare_is_refused() -> None:
    with pytest.raises(ResolutionError) as excinfo:
        _build("{convert: [EUR, USD, settled_at]}")
    message = str(excinfo.value)
    assert "'settled_at'" in message
    assert "declared fields:" in message


def test_a_non_temporal_anchor_is_refused() -> None:
    """The anchor is compared against the rate's validity interval, so a string
    anchor would compare a payment id against a date."""
    with pytest.raises(ResolutionError) as excinfo:
        _build("{convert: [EUR, USD, payment_id]}")
    assert "which is string" in str(excinfo.value)


def test_an_anchor_this_mapping_does_not_lower_is_refused() -> None:
    """A merged entity's branches map different columns, and the branch that
    converts is the one that has to supply the date."""
    sources = _sources()
    sources["entity_model"] = sources["entity_model"].replace(
        "      paid_at: {type: date}\n",
        "      paid_at: {type: date}\n      settled_at: {type: date}\n",
    )
    sources["mapping"] = sources["mapping"].replace(STEP, "{convert: [EUR, USD, settled_at]}")
    with pytest.raises(ResolutionError) as excinfo:
        build_project_ir(load_project(sources), catalog=_catalog())
    assert "does not lower" in str(excinfo.value)


def test_a_recipe_anchor_is_refused_by_name() -> None:
    """Only a direct `from:` path is re-lowered into the conversion; a derived
    anchor would splice its whole derivation into every converted column. The
    refusal says which kind it found, because "step" and "recipe" send an
    author to different documents.
    """
    sources = _sources()
    sources["entity_model"] = sources["entity_model"].replace(
        "      paid_at: {type: date}\n", "      paid_at: {type: date, canonical: paid_at}\n"
    )
    sources["mapping"] = sources["mapping"].replace(
        '  paid_at: {from: "$.paid_at", transform: [{parse_date: ISO8601}]}\n',
        '  paid_at: {recipe: direct, from: {paid_at: "$.paid_at"}}\n',
    )
    catalog = load_catalog(
        (FIXTURE / "catalog.yaml").read_text()
        + "  paid_at:\n"
        "    entity: payment\n"
        "    type: date\n"
        "    recipes:\n"
        "      - {id: direct, requires: [paid_at]}\n"
    )
    with pytest.raises(ResolutionError) as excinfo:
        build_project_ir(load_project(sources), catalog=catalog)
    assert "lowered by a recipe" in str(excinfo.value)


def test_a_key_field_is_a_valid_anchor() -> None:
    """The nearest non-trigger, and a bug this test was written for.

    `key:` entries are `KeyField` and `fields:` entries are
    `SimpleFieldMapping` — two classes for one direct-path shape. Testing only
    the second refused an ordinary key anchor, and told the author it was
    "lowered by a step", which it was not.
    """
    sources = _sources()
    sources["entity_model"] = sources["entity_model"].replace(
        "    key: [payment_id]\n", "    key: [payment_id, paid_at]\n"
    )
    sources["mapping"] = (
        "mapping_version: 1\n"
        "source: psp__payments\n"
        "target: payment\n"
        "key:\n"
        '  payment_id: {from: "$.id", transform: [to_string]}\n'
        '  paid_at: {from: "$.paid_at", transform: [{parse_date: ISO8601}]}\n'
        "fields:\n"
        '  amount_eur: {from: "$.amount", transform: [{to_decimal: [12, 4]}]}\n'
        '  amount_usd:\n'
        '    from: "$.amount"\n'
        f"    transform: [{{to_decimal: [12, 4]}}, {STEP}]\n"
        '  fee_usd: {from: "$.fee", transform: [{to_decimal: [12, 4]}]}\n'
    )
    ir = build_project_ir(load_project(sources), catalog=_catalog())
    converted = next(
        column
        for source in ir.entities[0].sources
        for column in source.columns
        if column.name == "amount_usd"
    )
    # At resolve time the marker is still a marker; what the fix guarantees is
    # that its anchor is the key field's own *lowering* rather than the name
    # the author wrote.
    assert "CAST(paid_at AS DATE)" in converted.expr.sql
    assert "'paid_at'" not in converted.expr.sql
