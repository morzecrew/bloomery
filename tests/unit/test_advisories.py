"""The compile-time advisory channel (S-0004 (§5)) — the vocabulary, the
ordering rules, and the one producer that remains.

Findings are **values**, carried on the evidence a caller already receives.
Nothing important is ever only logged (D5), which is why nothing in this
module reads a log to find out what the compiler noticed.
"""

from __future__ import annotations

import dataclasses

import pytest

from bloomery import (
    Advisory,
    AdvisoryCode,
    CheckedSurfaces,
    SpecEvidence,
    Stage,
    evaluate,
)
from bloomery.evidence import (  # pyright: ignore[reportPrivateUsage]
    _advisories,
    _sorted_advisories,
)
from support.compiling import load_fixture

pytestmark = pytest.mark.unit


def _advisory(code: AdvisoryCode, message: str, source_path: str | None = None) -> Advisory:
    return Advisory(code=code, message=message, source_path=source_path)


# ....................... #
# The producer


def test_a_project_with_no_ir_reports_nothing() -> None:
    """No IR, no finding — and no crash reaching for one."""
    project, _catalog = load_fixture("minimal")

    assert evaluate(project).advisories == ()
    assert _advisories(None) == ()


# ....................... #
# Ordering and identity (§5.1)


def test_advisories_are_not_directly_orderable() -> None:
    """`Advisory` carries no `order=True`, deliberately (PR #110 review).

    It used to, on the claim that the dataclass's own comparison *was* §5.1's
    key. It was not — the declared key is `(code, source_path, message)` and
    the field order is `(code, message, source_path)`, so the two disagreed
    whenever two advisories shared a code, and comparing a `None` source path
    against a string raised `TypeError` on a legal pair.

    Not orderable at all is the honest state: there is one ordering rule, it
    lives in `_advisory_key`, and `sorted()` without a key now says so loudly
    instead of answering differently from the documentation.

    **Both source paths are set**, deliberately. A pair with a `None` path
    raises `TypeError` under `order=True` too — comparing `None` with a string
    — so a test built on that pair passes in both worlds and pins nothing. This
    pair is the one the old code compared *successfully* and wrongly, so it is
    the one that tells the two apart: putting `order=True` back makes this
    comparison succeed, and this assertion fail.
    """
    one = _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "zzz", "catalog: a")
    other = _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "aaa", "catalog: b")

    with pytest.raises(TypeError):
        _ = one < other  # type: ignore[operator]


def test_the_documented_key_disagrees_with_field_order_and_the_key_wins() -> None:
    """The half that makes the removal necessary rather than tidy.

    These two sort one way by `(code, source_path, message)` and the other way
    by the dataclass's field order. A type that answers both questions answers
    one of them wrongly, and nothing at the call site says which.
    """
    later_path_first_message = _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "aaa", "catalog: b")
    earlier_path_last_message = _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "zzz", "catalog: a")

    ordered = _sorted_advisories([later_path_first_message, earlier_path_last_message])

    assert ordered == (earlier_path_last_message, later_path_first_message)


def test_advisories_sort_by_code_then_path_then_message() -> None:
    """The declared total key. Fed in reverse so a stable sort cannot pass by
    accident."""
    first = _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "aaa", "catalog: a")
    second = _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "bbb", "catalog: a")
    third = _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "aaa", "catalog: b")

    assert _sorted_advisories([third, second, first]) == (first, second, third)


def test_a_missing_source_path_sorts_first_and_stays_none() -> None:
    """§5.1: it normalizes to the empty string *for ordering* while staying
    `None` on the value — the same split a refusal's missing path already has.
    """
    pathless = _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "m")
    placed = _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "m", "catalog: a")

    ordered = _sorted_advisories([placed, pathless])

    assert ordered == (pathless, placed)
    assert ordered[0].source_path is None


def test_two_advisories_equal_in_all_three_fields_collapse() -> None:
    """The identity rule, stated rather than defaulted."""
    one = _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "m", "catalog: a")
    same = _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "m", "catalog: a")

    assert _sorted_advisories([one, same]) == (one,)


@pytest.mark.parametrize(
    "other",
    [
        _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "m", "catalog: b"),
        _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "different", "catalog: a"),
    ],
)
def test_advisories_differing_in_any_field_both_survive(other: Advisory) -> None:
    """Dedup on all three, not on the code — two places publishing an
    undeclared audience are two findings, and collapsing them would hide one
    of the two places to fix.
    """
    one = _advisory(AdvisoryCode.UNDECLARED_AUDIENCE, "m", "catalog: a")

    assert len(_sorted_advisories([one, other])) == 2


def test_the_result_is_a_tuple() -> None:
    """S-0020: tuples, not sets. This value reaches a caller and is compared
    across processes."""
    assert isinstance(_sorted_advisories([]), tuple)


# ....................... #
# The field


def test_advisories_is_the_last_field() -> None:
    """S-0004 (§5.1) asks for a positional-construction regression test, and
    this is the claim behind it.

    Every field on `SpecEvidence` has a default, so inserting one mid-list does
    not raise for a positional caller — it silently rebinds, producing evidence
    that is wrong in two places and refuses nothing. Appending is what keeps
    the addition additive (S-0035/D-1).
    """
    names = [field.name for field in dataclasses.fields(SpecEvidence)]

    assert names[-1] == "advisories"


def test_positional_construction_still_binds_what_it_did() -> None:
    """The regression the rule above exists to prevent, executed.

    A caller who built evidence positionally before this field existed must
    still get the same object — every argument landing in the field it named.

    **Every pre-existing field is supplied**, through `checked`, and that is
    the whole point rather than thoroughness for its own sake. A shorter call
    stops before the insertion point and passes against a field inserted after
    it: a sabotage adding a field between `provenance` and `checked` survived a
    seven-argument version of this test, because the eighth argument it would
    have rebound was never passed.
    """
    checked = CheckedSurfaces(
        entities=1,
        relationships=0,
        measures=1,
        marts=1,
        rollups=0,
        conversions=0,
        temporal_joins=0,
    )
    evidence = SpecEvidence(
        Stage.COMPLETE,
        ("revenue",),
        (),
        (),
        (),
        ("order",),
        "blm1:abc",
        (),
        (),
        checked,
    )

    assert evidence.stage_reached is Stage.COMPLETE
    assert evidence.reachable == ("revenue",)
    assert evidence.entities == ("order",)
    assert evidence.fingerprint == "blm1:abc"
    assert evidence.unresolved == ()
    assert evidence.provenance == ()
    assert evidence.checked is checked
    assert evidence.advisories == ()


def test_the_positional_call_above_covers_every_pre_existing_field() -> None:
    """The control that keeps the test above honest as the type grows.

    It passes one argument per field that existed before `advisories`, and the
    claim only holds while that is true — a field appended tomorrow leaves the
    call one short and the insertion sabotage alive again, silently.
    """
    names = [field.name for field in dataclasses.fields(SpecEvidence)]

    assert len(names) - 1 == 10


def test_advisories_defaults_to_empty() -> None:
    """Absent means "nothing to say", and it is a tuple rather than `None`:
    unlike `checked`, an empty advisory list has an honest zero to print."""
    assert SpecEvidence(stage_reached=Stage.RESOLVE).advisories == ()


# ....................... #
# The vocabulary is closed


def test_every_code_has_a_value_that_is_not_its_name() -> None:
    """A `StrEnum` whose value is the lowercase code, which is what a caller
    branches on and what the reference documents."""
    for code in AdvisoryCode:
        assert code.value == code.value.lower()
        assert " " not in code.value
