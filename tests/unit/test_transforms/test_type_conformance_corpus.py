"""The declared-vs-produced corpus is complete and its register is well formed
(RFC 0028 D5).

The battery itself needs an engine, so it runs in tiers 4 and 5. What can be
checked without one is the thing most likely to rot: whether the hand-written
corpus still covers the registry. A transform added — or an input domain
widened — without a case would not fail anything; it would simply stop being
measured, which is how ``regex_extract`` came to ship on three dialects with a
capture-group argument that did nothing and no fixture exercising it.
"""

from __future__ import annotations

import pytest
from sqlglot import exp
from support.type_conformance import CASES, KNOWN, UNRUNNABLE, uncovered

from bloomery.dialects import get_dialect
from bloomery.transforms import DEFAULT_REGISTRY

pytestmark = pytest.mark.unit


def test_every_transform_and_input_type_has_a_case() -> None:
    assert uncovered() == ()


def test_the_unrunnable_list_names_real_transforms_and_explains_itself() -> None:
    """A name that left the registry must leave this list with it, or the
    exemption outlives the thing it exempted."""
    assert set(UNRUNNABLE) <= set(DEFAULT_REGISTRY)
    assert all(reason for reason in UNRUNNABLE.values())


def test_case_ids_are_unique() -> None:
    """The register is keyed by id, so a collision would silently make one case
    stand in for another."""
    ids = [case.id for case in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("port", sorted(KNOWN))
def test_registered_divergences_name_real_cases_and_a_shipped_port(port: str) -> None:
    assert get_dialect(port).name == port
    ids = {case.id for case in CASES}
    unknown = sorted(set(KNOWN[port]) - ids)
    assert not unknown, f"{port}: registered divergences for cases that do not exist: {unknown}"


@pytest.mark.parametrize("port", sorted(KNOWN))
def test_every_registered_divergence_says_why(port: str) -> None:
    """A register of bare type names is a list of numbers nobody can act on;
    each row is scheduled work and has to say what it is (RFC 0029)."""
    silent = sorted(name for name, entry in KNOWN[port].items() if not entry.why.strip())
    assert not silent, f"{port}: divergences registered without a reason: {silent}"


def test_a_case_declares_what_the_registry_says_it_declares() -> None:
    """``Case.declared`` reads the registry rather than restating it, so a
    transform whose output type function changes moves the expectation with
    it. Spot-checked on the two shapes that depend on their arguments."""
    to_decimal = next(c for c in CASES if c.transform == "to_decimal" and c.args == (10, 2))
    assert repr(to_decimal.declared) == repr(
        DEFAULT_REGISTRY["to_decimal"].output_type(to_decimal.source, to_decimal.args)
    )
    multiply = next(c for c in CASES if c.transform == "multiply")
    assert multiply.declared != multiply.source  # decimal(12, 4) widened to decimal(13, 4)


def test_probing_uses_the_expression_emit_sees_not_the_builders() -> None:
    """The corpus round-trips every case through canonical text before probing
    (RFC 0003 D2), and the round trip is not lossless.

    ``json_path`` is the visible proof: its builder leaves the path as a plain
    string literal, and only re-parsing makes it the
    :class:`sqlglot.exp.JSONPath` that the PostgreSQL port's rewrite looks for.
    Probing the builder's output would measure a tree no artifact contains —
    and would have scored that port's JSON extraction against SQL it never
    emits.
    """
    case = next(c for c in CASES if c.transform == "json_path" and c.label == "deep")
    built = DEFAULT_REGISTRY["json_path"].builder(exp.column("x"), *case.args)
    assert built.find(exp.JSONPath) is None
    assert case.expression("x").find(exp.JSONPath) is not None
