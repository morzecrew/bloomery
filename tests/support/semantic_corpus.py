"""The semantic bug corpus, loaded (RFC 0042).

Every case is a directory under ``tests/fixtures/semantic_corpus/`` holding a
statement, a warehouse, two queries, the expected numbers, and one bloomery
spec per pinned expectation. This module is the only thing that knows that
layout, so a case is added by adding a directory rather than by editing a test.

**A case with nothing to say is a bug in the corpus, not a passing test.** The
loader refuses a case missing any required part, and refuses an expectation
declared in ``semantic_outcome.json`` with no spec beside it or a spec with no
declared outcome. A corpus whose harness silently skips half of it is worse
than no corpus — it reports green for the cases nobody wrote.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from bloomery import load_catalog, load_project

if TYPE_CHECKING:
    from bloomery.spec.catalog import Catalog
    from bloomery.spec.project import Project

# ----------------------- #

__all__ = [
    "CORPUS",
    "Case",
    "Expectation",
    "Outcome",
    "cases",
]

CORPUS = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "semantic_corpus"

#: What every case owns. Listed rather than globbed so a half-written case
#: fails loudly at collection instead of contributing a shorter test.
REQUIRED = (
    "problem.md",
    "schema/schema.sql",
    "data/rows.sql",
    "naive.sql",
    "correct.sql",
    "expected/result.json",
    "expected/semantic_outcome.json",
    # A directory rather than a file, and here rather than left to
    # `_expectations` to discover: without it that helper's `iterdir()` raises
    # FileNotFoundError, which reads as a harness bug rather than as the
    # incomplete case it is.
    "bloomery",
)

#: The two queries every case runs, and the two keys `result.json` is therefore
#: written against. Named because the pair is a contract, not a convention: a
#: file carrying only one of them loads clean and fails much later, in the
#: execution tier, as a `KeyError` naming neither the case nor the omission.
QUERIES = ("naive", "correct")


class Outcome(StrEnum):
    """What bloomery does with one expectation of a case.

    Each is a claim about **the number bloomery's own planner returns** when
    asked this case's metric — not about the hand-written queries beside it,
    and not about prose. ``ACCEPTED`` and ``UNGUARDED`` both compile; what
    separates them is which of the case's two results comes back.

    ``UNGUARDED`` is the one the corpus needed a name for. Without it a case
    whose guard has not been built yet can only be written as a fiction or
    left out, and leaving it out drops exactly the cases a future RFC exists
    to convert — which is the direction the semantic sequence travels, and
    what makes the corpus a design gate (RFC 0042 §8).
    """

    #: bloomery refuses the spec. ``error`` names the class, and there is no
    #: number: nothing was planned.
    REFUSED = "refused"
    #: It compiles, and the planned SQL returns the case's **correct** result.
    ACCEPTED = "accepted"
    #: It compiles, and the planned SQL returns the case's **naive** result —
    #: the wrong one. Nothing refused it.
    UNGUARDED = "unguarded"

    # ....................... #

    @property
    def answer(self) -> str | None:
        """Which entry of ``expected/result.json`` the planner must return."""

        return {Outcome.ACCEPTED: "correct", Outcome.UNGUARDED: "naive"}.get(self)


@dataclass(frozen=True, slots=True)
class Expectation:
    """One pinned behaviour: a spec directory and what it should do."""

    name: str
    outcome: Outcome
    #: The refusal's class name, for ``REFUSED``; ``None`` otherwise. The
    #: machine-readable half of RFC 0042 D3 — prose is not asserted.
    error: str | None
    #: The decision this case belongs to, e.g. ``"RFC 0010 D2"``. Stable by
    #: the retirement policy: a retired RFC keeps its number.
    rule: str
    directory: pathlib.Path

    # ....................... #

    def project(self) -> tuple[Project, Catalog | None]:
        sources = {
            path.stem: path.read_text(encoding="utf-8")
            for path in sorted(self.directory.glob("*.yaml"))
            if path.stem != "catalog"
        }
        catalog = self.directory / "catalog.yaml"

        return (
            load_project(sources),
            load_catalog(catalog.read_text(encoding="utf-8")) if catalog.exists() else None,
        )


@dataclass(frozen=True, slots=True)
class Case:
    """One corpus case."""

    name: str
    directory: pathlib.Path
    expectations: tuple[Expectation, ...]

    # ....................... #

    def sql(self, name: str) -> str:
        return (self.directory / name).read_text(encoding="utf-8")

    # ....................... #

    @property
    def supplied(self) -> frozenset[str]:
        """Relations the case creates in ``silver`` itself.

        Declared by being created rather than by a field, because creating one
        is already the statement: a relation the case builds is one bloomery
        reads and does not derive. The case it exists for is an ``scd: type2``
        entity — its versions come from the operator's snapshotting, and a
        harness that rebuilt it from bronze would be asserting a pipeline
        nobody runs — and a rate relation is the same shape.
        """

        return frozenset(
            f"silver.{name}"
            for name in re.findall(
                r"CREATE TABLE silver\.(\w+)", self.sql("schema/schema.sql")
            )
        )

    # ....................... #

    @property
    def metric(self) -> str:
        """The metric to ask for, which is the single column both results name.

        A convention rather than a field: a case whose expected numbers are
        keyed by anything but the metric they measure would be asserting a
        number against a name nothing connects to it.
        """
        columns = {column for row in self.results().values() for column in row}
        if len(columns) != 1:
            raise AssertionError(
                f"{self.name}: expected exactly one measured column, got {sorted(columns)}"
            )

        return columns.pop()

    # ....................... #

    def results(self) -> dict[str, dict[str, Decimal]]:
        """The expected numbers, as ``Decimal`` — never floats (RFC 0003 D5).

        Authored as strings for the same reason: ``9.0`` in JSON is a float
        before any of this code sees it.
        """
        raw = json.loads((self.directory / "expected" / "result.json").read_text("utf-8"))

        if set(raw) != set(QUERIES):
            raise AssertionError(
                f"{self.name}: result.json must name exactly {list(QUERIES)}, got {sorted(raw)}"
            )

        return {
            query: {column: Decimal(value) for column, value in columns.items()}
            for query, columns in raw.items()
        }


def _expectations(directory: pathlib.Path) -> tuple[Expectation, ...]:
    declared = json.loads(
        (directory / "expected" / "semantic_outcome.json").read_text("utf-8")
    )
    specs = {path.name for path in (directory / "bloomery").iterdir() if path.is_dir()}

    # Agreement is not enough: an empty outcome map and an empty `bloomery/`
    # agree perfectly, and the case then contributes its SQL assertions and
    # nothing about bloomery at all — a case that has stopped being one, which
    # nothing else here would notice.
    if not declared:
        raise AssertionError(f"{directory.name}: no expectations — a case must pin something")

    if specs != set(declared):
        missing, extra = sorted(set(declared) - specs), sorted(specs - set(declared))
        problem = (
            f"{directory.name}: semantic_outcome.json and bloomery/ disagree — "
            f"declared with no spec: {missing}, spec with no declared outcome: {extra}"
        )
        raise AssertionError(problem)

    # A spec directory is a *project*, and an empty one is not. Left unchecked
    # it passes every structural test here — the name matches, the outcome map
    # agrees — and only fails when something tries to compile it, which for a
    # `refused` expectation is indistinguishable from the refusal being asserted.
    # After the agreement check, so a directory that is empty *and* undeclared
    # is reported as the disagreement it also is.
    empty = sorted(
        name for name in specs if not any((directory / "bloomery" / name).glob("*.yaml"))
    )
    if empty:
        raise AssertionError(f"{directory.name}: spec directory with no YAML in it: {empty}")

    return tuple(
        Expectation(
            name=name,
            outcome=Outcome(declared[name]["outcome"]),
            error=declared[name].get("error"),
            rule=declared[name]["rule"],
            directory=directory / "bloomery" / name,
        )
        for name in sorted(declared)
    )


def cases() -> tuple[Case, ...]:
    """Every case, sorted by directory name — which is why they are numbered."""
    found = []

    for directory in sorted(CORPUS.iterdir()):
        if not directory.is_dir():
            continue
        absent = [part for part in REQUIRED if not (directory / part).exists()]
        if absent:
            raise AssertionError(f"{directory.name}: incomplete case, missing {absent}")
        case = Case(
            name=directory.name, directory=directory, expectations=_expectations(directory)
        )
        # Reading it is the check: `metric` parses result.json, which refuses a
        # file naming anything but both queries, and then refuses one whose two
        # halves measure different columns. Done here so a malformed case fails
        # at collection rather than in whichever parametrized cell reaches it.
        _ = case.metric
        found.append(case)

    if not found:
        raise AssertionError(f"no cases under {CORPUS} — the corpus cannot be empty")

    return tuple(found)
