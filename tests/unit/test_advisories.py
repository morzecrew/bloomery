"""The compile-time advisory channel (RFC 0033 §5) — the vocabulary, the
ordering rules, and the one producer that exists.

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
    load_catalog,
)
from bloomery.evidence import _advisories, _divides, _sorted_advisories  # pyright: ignore[reportPrivateUsage]
from support.compiling import load_fixture

pytestmark = pytest.mark.unit


def _advisory(code: AdvisoryCode, message: str, source_path: str | None = None) -> Advisory:
    return Advisory(code=code, message=message, source_path=source_path)


# ....................... #
# The producer


def test_a_recipe_that_divides_is_flagged() -> None:
    """`ecom_basic`'s `from_total` recipe is `line_total / quantity` — the
    exact construct `dialects.md` documents as inexact on every engine, and
    which a spec author currently learns about only by reading the reference.
    """
    project, catalog = load_fixture("ecom_basic")
    evidence = evaluate(project, catalog=catalog)

    assert [(a.code, a.source_path) for a in evidence.advisories] == [
        (
            AdvisoryCode.INEXACT_DIVISION,
            "catalog: canonical_fields.unit_price.recipes.from_total.expr",
        )
    ]


def test_a_project_whose_recipes_do_not_divide_says_nothing() -> None:
    """The half that keeps the channel worth reading. A finding on every
    project is a finding nobody looks at."""
    project, catalog = load_fixture("multi_source")

    assert evaluate(project, catalog=catalog).advisories == ()


def test_the_message_says_what_why_and_the_way_out() -> None:
    """§5.1: the same contract refusals carry. Not the exact words — message
    text is not API — but the three parts a reader needs."""
    project, catalog = load_fixture("ecom_basic")
    (advisory,) = evaluate(project, catalog=catalog).advisories

    assert "divides in its expr:" in advisory.message  # what
    assert "binary floating point" in advisory.message  # why
    assert "Fix," in advisory.message  # the way out
    # And the bar itself (§5.2): this is legal, and the message says so rather
    # than reading as a refusal that lost its nerve.
    assert "legal and the artifacts are correct" in advisory.message


def test_a_project_with_no_catalog_reports_nothing() -> None:
    """No catalog, no recipes, no finding — and no crash reaching for one."""
    project, _catalog = load_fixture("minimal")

    assert evaluate(project).advisories == ()
    assert _advisories(None) == ()


# ....................... #
# Detection is a parse, not a scan


@pytest.mark.parametrize(
    "expr",
    [
        "line_total / quantity",
        "(a + b) / c",
        "CAST(x AS DECIMAL(10, 2)) / NULLIF(y, 0)",
    ],
)
def test_a_division_anywhere_in_the_tree_counts(expr: str) -> None:
    assert _divides(expr) is True


@pytest.mark.parametrize(
    "expr",
    [
        None,
        "line_total * quantity",
        # The reason this is a parse and not a `"/" in expr` scan: the slash is
        # inside a literal, and no division happens.
        "CONCAT(a, '/', b)",
        "a || '10/12' || b",
        # Unparseable is not an advisory: a malformed recipe is the resolve
        # stage's refusal to make, and guessing here would report a finding
        # about a project that is about to be refused for a better reason.
        "SELECT FROM WHERE ((",
    ],
)
def test_what_is_not_a_division_is_not_flagged(expr: str | None) -> None:
    assert _divides(expr) is False


def test_a_slash_in_a_literal_survives_a_real_compile() -> None:
    """The scan-versus-parse claim, end to end rather than on the helper.

    A helper test proves the predicate; this proves nothing downstream
    re-derives the answer from the text.
    """
    project, _catalog = load_fixture("ecom_basic")
    doctored = load_catalog(_catalog_text_with_literal_slash())

    assert evaluate(project, catalog=doctored).advisories == ()


def _catalog_text_with_literal_slash() -> str:
    """`ecom_basic`'s catalog with the dividing recipe replaced by one whose
    expression only *contains* a slash."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "fixtures" / "ecom_basic" / "catalog.yaml"
    text = root.read_text()
    assert "line_total / quantity" in text, "the recipe moved — repoint this test"
    return text.replace("line_total / quantity", "CONCAT(line_total, '/', quantity)")


# ....................... #
# The refusal path


def _refused(where: str) -> tuple[object, object]:
    """`ecom_basic` broken so the pipeline stops at ``where``, with its catalog
    untouched — so the dividing recipe the advisory is about survives every
    variant, and the only thing that changes is how far analysis got."""
    from bloomery import load_project
    from support.compiling import fixture_sources

    _project, catalog = load_fixture("ecom_basic")
    sources = dict(fixture_sources("ecom_basic"))

    if where == "resolve":
        key = next(name for name, text in sources.items() if "metrics_version" in text)
        sources[key] = sources[key].replace("unit_price", "no_such_field")
    elif where == "typecheck":
        key = next(name for name, text in sources.items() if "transform:" in text)
        sources[key] = sources[key].replace("to_string", "no_such_transform", 1)
    else:
        key = next(name for name, text in sources.items() if "marts_version" in text)
        sources[key] = sources[key].replace(
            "      - {date: order_date, role: ordered}\n", ""
        ).replace("    partition_by: [days(ordered_day)]\n", "")

    return load_project(sources), catalog


@pytest.mark.parametrize(
    ("where", "stage"),
    [("resolve", Stage.RESOLVE), ("typecheck", Stage.TYPECHECK), ("guardrails", Stage.GUARDRAILS)],
)
def test_a_refused_project_still_reports_its_advisories(where: str, stage: Stage) -> None:
    """"The prefix survives" applies here too, at **every** width.

    An advisory is derived from the *catalog*, which is an input: it is
    computed and correct whether or not a stage refused. Withholding it would
    make `advisories` the one field on this type that is empty for a reason
    `stage_reached` cannot explain — the objection `_partial` already raises
    about `unresolved`. §5.2's bar decides what *qualifies* as an advisory, not
    when a qualifying one is worth saying.

    Three widths because `_partial` has three returns and they are separate
    code, not three readings of one. A sabotage that removed the field from
    only the middle one survived a single-width version of this test.
    """
    project, catalog = _refused(where)
    evidence = evaluate(project, catalog=catalog)  # type: ignore[arg-type]

    assert evidence.stage_reached is stage
    assert evidence.refusals
    assert [a.code for a in evidence.advisories] == [AdvisoryCode.INEXACT_DIVISION]


def test_an_unreadable_recipe_expression_is_not_an_advisory_and_not_a_crash() -> None:
    """`SqlglotError`, not `ParseError`.

    An unterminated string literal raises `TokenError`, a *sibling* of
    `ParseError` rather than a subclass — so the narrower catch let a
    third-party exception out of a function whose whole contract is that a
    spec-level problem comes back as a value. The advisory pass must be silent
    about an expression it cannot read: a malformed recipe is the resolve
    stage's refusal to make.
    """
    assert _divides("CONCAT(a, 'oops)") is False


# ....................... #
# Ordering and identity (§5.1)


def test_advisories_sort_by_code_then_path_then_message() -> None:
    """The declared total key. Fed in reverse so a stable sort cannot pass by
    accident."""
    first = _advisory(AdvisoryCode.INEXACT_DIVISION, "aaa", "catalog: a")
    second = _advisory(AdvisoryCode.INEXACT_DIVISION, "bbb", "catalog: a")
    third = _advisory(AdvisoryCode.INEXACT_DIVISION, "aaa", "catalog: b")

    assert _sorted_advisories([third, second, first]) == (first, second, third)


def test_a_missing_source_path_sorts_first_and_stays_none() -> None:
    """§5.1: it normalizes to the empty string *for ordering* while staying
    `None` on the value — the same split a refusal's missing path already has.
    """
    pathless = _advisory(AdvisoryCode.INEXACT_DIVISION, "m")
    placed = _advisory(AdvisoryCode.INEXACT_DIVISION, "m", "catalog: a")

    ordered = _sorted_advisories([placed, pathless])

    assert ordered == (pathless, placed)
    assert ordered[0].source_path is None


def test_two_advisories_equal_in_all_three_fields_collapse() -> None:
    """The identity rule, stated rather than defaulted."""
    one = _advisory(AdvisoryCode.INEXACT_DIVISION, "m", "catalog: a")
    same = _advisory(AdvisoryCode.INEXACT_DIVISION, "m", "catalog: a")

    assert _sorted_advisories([one, same]) == (one,)


@pytest.mark.parametrize(
    "other",
    [
        _advisory(AdvisoryCode.INEXACT_DIVISION, "m", "catalog: b"),
        _advisory(AdvisoryCode.INEXACT_DIVISION, "different", "catalog: a"),
    ],
)
def test_advisories_differing_in_any_field_both_survive(other: Advisory) -> None:
    """Dedup on all three, not on the code — two recipes that both divide are
    two findings, and collapsing them would hide one of the two places to fix.
    """
    one = _advisory(AdvisoryCode.INEXACT_DIVISION, "m", "catalog: a")

    assert len(_sorted_advisories([one, other])) == 2


def test_the_result_is_a_tuple() -> None:
    """RFC 0003: tuples, not sets. This value reaches a caller and is compared
    across processes."""
    assert isinstance(_sorted_advisories([]), tuple)


# ....................... #
# The field


def test_advisories_is_the_last_field() -> None:
    """RFC 0033 §5.1 asks for a positional-construction regression test, and
    this is the claim behind it.

    Every field on `SpecEvidence` has a default, so inserting one mid-list does
    not raise for a positional caller — it silently rebinds, producing evidence
    that is wrong in two places and refuses nothing. Appending is what keeps
    the addition additive (RFC 0018 D1).
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
