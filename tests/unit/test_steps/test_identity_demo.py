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
    assert canonical_id("email:ada@example.com") == canonical_id("email:ada@example.com")
    assert canonical_id("email:ada@example.com") != canonical_id("email:grace@example.com")
    assert canonical_id("email:ada@example.com").startswith("cust_")


def test_the_demonstrations_output_satisfies_the_manifest_it_is_wired_to() -> None:
    """The two halves of the fixture, checked against each other.

    `assert_step_contract` is what the generated wrapper runs on every
    execution, against the manifest bloomery embedded. Feeding it this
    resolver's real frames is what makes the fixture a demonstration rather
    than two artefacts that merely sit in the same directory.
    """
    manifest = RESOLVE_CUSTOMERS_V4.model_dump(by_alias=True, mode="json")
    assert_step_contract(_resolved("0.85"), manifest)


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
    `determinism: pure` must not commit it."""
    assert (_resolved()["customer"]["resolved_at"] == RESOLVED_AT).all()
