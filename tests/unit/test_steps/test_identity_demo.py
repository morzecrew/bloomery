"""The demonstration resolver, standalone — no bloomery in the loop.

RFC 0021 §6's last row: a step's own fixtures run without the compiler, the
way the platform that owns the step would run them. Two things make it worth a
module rather than a comment.

**It is the half bloomery never sees.** The compiler emits a wrapper and
asserts a contract; it never executes a step body (RFC 0003 — compilation does
no I/O and runs nothing). So the only place the demonstration's *behaviour* can
be pinned is here, and if it were not pinned the fixture would be illustrating a
resolver nobody had run.

**It closes the loop on the contract.** The last test feeds this resolver's
real output to :func:`~bloomery.steps.assert_step_contract` against the real
manifest — so the fixture's two halves are checked against each other rather
than each against its own idea of the other. That is the assertion that would
catch a manifest edited without its body, which is the failure mode a
registry's parameterize-never-fork rule makes likely.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest
from support.identity import RESOLVED_AT, canonical_id, normalize_name, resolve
from support.steps import RESOLVE_CUSTOMERS_V4

from bloomery.errors import StepContractViolation
from bloomery.steps import assert_step_contract

pytestmark = pytest.mark.unit

#: Four records, three people. `C-1001`/`AC-77` are one person by email;
#: `C-1002`/`AC-91` are one person by name written two ways and no email —
#: which is the pair a shared key would have caught and neither source has.
CRM = pd.DataFrame(
    [
        {"source_system": "crm", "source_id": "C-1001", "email": "ada@example.com", "name": "Ada Lovelace"},
        {"source_system": "crm", "source_id": "C-1002", "email": "", "name": "Grace Hopper"},
    ]
)
BILLING = pd.DataFrame(
    [
        {"source_system": "billing", "source_id": "AC-77", "email": "ada@example.com", "name": "A. Lovelace"},
        {"source_system": "billing", "source_id": "AC-91", "email": "", "name": "hopper, grace"},
    ]
)


def _resolved(threshold: str = "0.9") -> dict[str, pd.DataFrame]:
    return resolve(CRM, BILLING, threshold=Decimal(threshold))


def test_two_sources_with_no_shared_key_resolve_to_one_customer() -> None:
    """The claim identity resolution exists to make.

    `crm/C-1001` and `billing/AC-77` share no identifier — one is `C-1001`, the
    other `AC-77` — and come back under a single `canonical_id`.
    """
    xref = _resolved()["customer_xref"].set_index(["source_system", "source_id"])
    assert xref.loc[("crm", "C-1001"), "canonical_id"] == xref.loc[("billing", "AC-77"), "canonical_id"]
    assert xref.loc[("crm", "C-1001"), "method"] == "exact"


def test_the_threshold_is_what_a_second_tenant_turns_up() -> None:
    """RFC 0017's parameterize-never-fork rule, exercised.

    The name-matched pair resolves at `0.85` and does not at `0.9`; a tenant
    wanting stricter matching changes one number in its wiring and gets the
    same step. At the strict setting the rows are still *reported*, with a NULL
    `canonical_id` — "we could not resolve this" is a fact, and dropping the
    rows would make it look like the source never had them.
    """
    lenient = _resolved("0.85")["customer_xref"].set_index(["source_system", "source_id"])
    assert lenient.loc[("crm", "C-1002"), "canonical_id"] == lenient.loc[("billing", "AC-91"), "canonical_id"]
    assert lenient.loc[("crm", "C-1002"), "method"] == "fuzzy"

    strict = _resolved("0.9")["customer_xref"].set_index(["source_system", "source_id"])
    assert strict.loc[("crm", "C-1002"), "canonical_id"] is None
    assert strict.loc[("crm", "C-1002"), "method"] == "none"


def test_every_source_row_appears_in_the_crosswalk_exactly_once() -> None:
    """The property a crosswalk lives or dies on: it is a *total* map from
    source rows. A resolver that silently dropped the rows it could not match
    would report a clean warehouse and a shrinking one."""
    for threshold in ("0.85", "0.9"):
        xref = _resolved(threshold)["customer_xref"]
        assert len(xref) == len(CRM) + len(BILLING)
        assert not xref.duplicated(subset=["source_system", "source_id"]).any()


def test_resolution_does_not_depend_on_the_order_rows_arrive_in() -> None:
    """`determinism: pure` is a manifest claim, and this is the cheapest real
    test of it: the same rows, reversed, produce the same ids.

    Canonical ids are derived from the matching key rather than assigned from a
    counter, which is what makes that true — and what lets the sibling
    consistency audit mean anything across two executions of one step.
    """
    forward = resolve(CRM, BILLING, threshold=Decimal("0.85"))
    backward = resolve(CRM.iloc[::-1], BILLING.iloc[::-1], threshold=Decimal("0.85"))
    assert sorted(forward["customer"]["canonical_id"]) == sorted(backward["customer"]["canonical_id"])
    assert set(forward["customer_xref"]["canonical_id"].dropna()) == set(
        backward["customer_xref"]["canonical_id"].dropna()
    )


def test_a_name_is_normalized_to_what_two_spellings_share() -> None:
    assert normalize_name("Ada Lovelace") == normalize_name("lovelace, ada")
    assert normalize_name("Ada  Lovelace") == normalize_name("Ada Lovelace")
    assert normalize_name(None) == ""
    assert normalize_name("Ada Lovelace") != normalize_name("Grace Hopper")


def test_a_canonical_id_is_a_function_of_its_key() -> None:
    """Stable for one key, distinct for different ones — and *distinct* is the
    half worth being careful about.

    The obvious version of this test compares two keys of different lengths,
    which a `len()`-based id would pass: a sabotage replacing the digest with
    `str(len(seed))` survived the whole module. Two keys of the *same* length
    is what makes the assertion about the hash rather than about the arguments
    — and a collision here merges two different people into one customer,
    which is the failure identity resolution exists to avoid.
    """
    assert canonical_id("email:ada@example.com") == canonical_id("email:ada@example.com")
    assert canonical_id("email:ada@example.com").startswith("cust_")

    same_length = ("email:ada@example.com", "email:zoe@example.com")
    assert len(same_length[0]) == len(same_length[1])
    assert canonical_id(same_length[0]) != canonical_id(same_length[1])


def test_empty_sources_produce_empty_outputs_that_still_satisfy_the_contract() -> None:
    """The boundary a resolver meets on its first run, before any data lands.

    Both frames come back empty *with their declared columns*, so the contract
    holds and the generated wrapper writes a well-shaped relation rather than
    failing the first plan. A resolver returning a bare `DataFrame()` here
    would pass its own tests and break the model that reads it.
    """
    columns = ["source_system", "source_id", "email", "name"]
    empty = pd.DataFrame(columns=columns)
    outputs = resolve(empty, empty, threshold=Decimal("0.85"))

    assert list(outputs["customer"].columns) == ["canonical_id", "confidence", "resolved_at"]
    assert outputs["customer"].empty
    assert outputs["customer_xref"].empty
    assert_step_contract(outputs, RESOLVE_CUSTOMERS_V4.model_dump(by_alias=True, mode="json"))


@pytest.mark.parametrize("missing", [None, float("nan"), pd.NA, pd.NaT])
def test_every_spelling_of_missing_reduces_to_nothing(missing: object) -> None:
    """What a real frame actually hands the matcher, and it is dtype-dependent.

    A cell with no value arrives as `None` in an object column, `NaN` once the
    column is float or once a CSV read has seen an empty field, `pd.NA` under
    the nullable string dtype, `NaT` for a datetime. Only `None` is falsy:
    `str(nan)` is `"nan"` and `str(pd.NA)` is `"<NA>"`, so a guard written
    against `None` alone lets three of the four through as ordinary text.
    """
    assert normalize_name(missing) == ""


def test_rows_with_no_email_are_not_all_the_same_person() -> None:
    """The missing-value guard at the level where its absence hurts.

    Asserted through `resolve` rather than through the helper, because the
    helper being right is not the claim — two different people staying two
    customers is. Guarded only by `or ""`, the email key became the literal
    `email:nan` for every row with no email, and the resolver merged all of
    them into one customer and called it an **exact** match: the highest
    confidence it can report, on the rows it knows least about.
    """
    unemailed = pd.DataFrame(
        [
            {"source_system": "crm", "source_id": "C-1", "email": float("nan"), "name": "Grace Hopper"},
            {"source_system": "crm", "source_id": "C-2", "email": float("nan"), "name": "Alan Turing"},
        ]
    )
    xref = resolve(unemailed, unemailed.iloc[0:0], threshold=Decimal("0.85"))["customer_xref"]
    assert xref["canonical_id"].nunique() == 2
    assert set(xref["method"]) == {"fuzzy"}


def test_the_demonstrations_output_satisfies_the_manifest_it_is_wired_to() -> None:
    """The two halves of the fixture, checked against each other.

    `assert_step_contract` is what the generated wrapper runs on every
    execution, against the manifest bloomery embedded. Feeding it this
    resolver's real frames is what makes the fixture a demonstration rather
    than two artefacts that merely sit in the same directory.
    """
    manifest = RESOLVE_CUSTOMERS_V4.model_dump(by_alias=True, mode="json")
    assert_step_contract(_resolved("0.85"), manifest)


def test_the_contract_holds_when_a_row_resolves_to_nobody() -> None:
    """The same check at the threshold the fixture actually wires — `0.9`.

    The test above runs at `0.85`, where every row resolves, so it never puts
    a NULL `canonical_id` in front of the contract. At the wiring's own
    threshold two rows resolve to nobody, and the manifest first declared that
    column `required`: the generated wrapper's assertion aborted the step
    before it wrote a relation, so the fixture *as configured* could not run.
    Two passing tests, each true, and nothing crossing them.
    """
    manifest = RESOLVE_CUSTOMERS_V4.model_dump(by_alias=True, mode="json")
    outputs = _resolved("0.9")
    assert outputs["customer_xref"]["canonical_id"].isna().any(), "the case must still arise"
    assert_step_contract(outputs, manifest)


def test_the_contract_would_catch_this_resolver_drifting() -> None:
    """The control on the test above: a passing assertion means nothing unless
    a failing one is reachable. Drop a declared column and the contract fires
    — so the check is live, not vacuous."""
    manifest = RESOLVE_CUSTOMERS_V4.model_dump(by_alias=True, mode="json")
    outputs = _resolved("0.85")
    outputs["customer"] = outputs["customer"].drop(columns=["resolved_at"])
    with pytest.raises(StepContractViolation):
        assert_step_contract(outputs, manifest)


def test_the_resolution_timestamp_is_a_constant_not_a_clock() -> None:
    """A step reading the wall clock produces a different `resolved_at` on
    every backfill of the same window — the failure `runtime_lock` and the
    determinism tier exist to catch (RFC 0017 D5), and a fixture claiming
    `determinism: pure` must not commit it.

    **The expected value is written here, not read from the module.** Comparing
    the output against `RESOLVED_AT` alone is a tautology: the module binds the
    constant once at import, so rows equal it whatever it holds — a sabotage
    setting it to `pd.Timestamp.now()` passed this module untouched. The
    purity guard does not cover `tests/`, so this assertion is the only thing
    standing between the demonstration and a clock.
    """
    assert RESOLVED_AT == pd.Timestamp("2026-01-01T00:00:00")
    assert (_resolved()["customer"]["resolved_at"] == RESOLVED_AT).all()
