"""Every plan this directory builds is checked against its own sentences
(S-0024/D-11).

A `Change` says what happened twice: once as `detail`, for a person, and once
as `action` and `member`, for a program. The fixture below holds every change
of every plan these tests build to agreeing with itself, so a construction
site that forgets the structured half — or spells it differently from its
sentence — fails whichever test reaches it, not only the tests written for
the fields.

It wraps the `Plan` constructor `plan()` calls, which is looked up at call
time, rather than `plan()` itself, which the tests import by value.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from bloomery.plan import diff
from bloomery.plan import Change, ChangeAction, ChangeClass

if TYPE_CHECKING:
    from bloomery.plan import Plan

# ----------------------- #

#: The phrases whose verb is not their last word before a clause break.
_LEADING: tuple[tuple[str, ChangeAction], ...] = (
    ("renamed from ", ChangeAction.RENAMED),
    ("type ", ChangeAction.RETYPED),
    ("optional field became required", ChangeAction.RETYPED),
    ("required field became optional", ChangeAction.RETYPED),
    ("new field is required", ChangeAction.ADDED),
    # A relation joins or leaves the merge; the entity named is still there.
    ("source ", ChangeAction.CHANGED),
)
_LAST_WORD: dict[str, ChangeAction] = {
    "added": ChangeAction.ADDED,
    "dropped": ChangeAction.REMOVED,
    "removed": ChangeAction.REMOVED,
    "unreachable": ChangeAction.REMOVED,
}
_QUOTED = re.compile(r"\b(flattened column|measure|dimension) '([^']+)'")


def _expected_action(detail: str) -> ChangeAction:
    for phrase, action in _LEADING:
        if detail.startswith(phrase):
            return action

    clause = re.split(r" \(| — |;", detail, maxsplit=1)[0]
    return _LAST_WORD.get(clause.rsplit(" ", 1)[-1], ChangeAction.CHANGED)


def assert_reads_as_its_detail(change: Change) -> None:
    """`action`, `member` and `advice` against `detail` and `subject`."""

    expected = _expected_action(change.detail)
    if change.change_class is ChangeClass.RENAME:
        expected = ChangeAction.RENAMED
    assert change.action is expected, change

    kind, _, name = change.subject.partition(":")
    quoted = _QUOTED.search(change.detail)
    if kind == "field":
        assert change.member == name, change
    elif quoted is not None and quoted.group(1) != "dimension":
        assert change.member == quoted.group(2), change
    elif quoted is not None:
        # A dimension is quoted by its qualified name and carried by the
        # column serving it, which the mart may spell with a prefix.
        assert change.member is not None, change
    elif kind != "quality":
        assert change.member is None, change

    assert "on dbt" not in change.detail, change
    targets = [target for target, _sentence in change.advice]
    assert targets == sorted(set(targets)), change


# ....................... #


@pytest.fixture(autouse=True)
def every_change_reads_as_its_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    built = diff.Plan

    def checked(**fields: object) -> Plan:
        made = built(**fields)  # type: ignore[arg-type]
        for change in made.changes:
            assert_reads_as_its_detail(change)
        return made

    monkeypatch.setattr(diff, "Plan", checked)
