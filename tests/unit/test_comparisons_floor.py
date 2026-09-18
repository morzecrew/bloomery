"""The comparison bundles keep their shape and their cells do not go stale
silently (S-0006 (§3), S-0006 (§4), S-0006/D-2, S-0006/D-7).

A cell pins a version and a date, and those two facts are the whole difference
between a measurement and a claim. Nothing stops them drifting on their own:
the bundles are manual by §7, so no run reports that the version a bundle names
is no longer the one installed. That drift is D2's failure arriving slowly — a
cell nobody guessed, still read as researched long after it stopped being true
— and it is mechanically detectable, which is why it is a gate rather than a
line of prose.

The date half is checked against a twelve-month ceiling; the version half only
for a system this repository resolves as a dependency, since nothing here can
know what version an uninstalled system was checked at.

The last check is D4's: the matrix's rows **are** the corpus's cases, and the
bloomery column is a transcription of their pinned outcomes. A transcription
is exactly the thing that goes quietly wrong when the thing it transcribes
moves, so it is compared rather than trusted.
"""

from __future__ import annotations

import datetime as dt
import importlib.metadata
import pathlib
import re

import pytest
from support.semantic_corpus import Outcome, cases

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPARISONS = ROOT / "comparisons"

#: S-0006 (§3)'s bundle layout, exactly.
REQUIRED = ("README.md", "config", "commands.txt", "observed.txt", "sources.md")

#: Bundle directory name → the distribution whose version its cells pin. A
#: system absent from here is one this repository does not resolve, and only
#: the date half of D7 applies to it.
DISTRIBUTION = {"metricflow": "metricflow", "dbt": "dbt-core", "sqlmesh": "sqlmesh"}

#: D7's ceiling. A cell older than this is `UNKNOWN` again whatever it says.
MAX_AGE = dt.timedelta(days=365)

_VERSION = re.compile(r"^- \*\*System:\*\* .*?`([^`]+)`", re.MULTILINE)
_CHECKED = re.compile(r"^- \*\*Checked:\*\* (\d{4}-\d{2}-\d{2})", re.MULTILINE)


def bundles() -> tuple[pathlib.Path, ...]:
    """Every `<system>/<case>/` directory under `comparisons/`."""

    return tuple(
        sorted(
            path
            for system in COMPARISONS.iterdir()
            if system.is_dir()
            for path in system.iterdir()
            if path.is_dir()
        )
    )


BUNDLES = bundles()


def test_there_is_at_least_one_bundle() -> None:
    """Otherwise every check below collects nothing and passes vacuously."""

    assert BUNDLES, f"no bundles under {COMPARISONS}"


@pytest.mark.parametrize("bundle", BUNDLES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_bundle_carries_every_required_entry(bundle: pathlib.Path) -> None:
    """S-0006 (§3): a bundle missing `observed.txt` is an argument."""

    missing = [name for name in REQUIRED if not (bundle / name).exists()]
    assert not missing, f"{bundle.relative_to(ROOT)} is missing {missing}"


@pytest.mark.parametrize("bundle", BUNDLES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_bundle_pins_a_version_and_a_date(bundle: pathlib.Path) -> None:
    """S-0006 (§4): a cell that pins neither claims permanence, and D1 forbids
    it."""

    readme = (bundle / "README.md").read_text(encoding="utf-8")
    assert _VERSION.search(readme), f"{bundle.relative_to(ROOT)}: no **System:** version pin"
    assert _CHECKED.search(readme), f"{bundle.relative_to(ROOT)}: no **Checked:** date"


@pytest.mark.parametrize("bundle", BUNDLES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_pinned_version_is_the_one_installed(bundle: pathlib.Path) -> None:
    """D7's first half: the cell is about a version, so a moved dependency
    returns it to `UNKNOWN` rather than leaving it read as current."""

    distribution = DISTRIBUTION.get(bundle.parent.name)

    if distribution is None:
        pytest.skip(f"{bundle.parent.name} is not a resolved dependency; only the date applies")

    match = _VERSION.search((bundle / "README.md").read_text(encoding="utf-8"))
    assert match is not None
    installed = importlib.metadata.version(distribution)
    assert match.group(1) == installed, (
        f"{bundle.relative_to(ROOT)} pins {distribution} {match.group(1)}, "
        f"{installed} is installed — re-run commands.txt and update the cell"
    )


@pytest.mark.parametrize("bundle", BUNDLES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_checked_date_is_within_the_ceiling(bundle: pathlib.Path) -> None:
    """D7's second half, and the only one that applies to a system this
    repository does not install.

    Bounded at both ends. A date in the future subtracts to a negative age and
    satisfies any ceiling, so the freshness gate would wave through a cell
    pinning a check that has not happened — which is D2's failure with a
    timestamp on it rather than a guess.
    """

    match = _CHECKED.search((bundle / "README.md").read_text(encoding="utf-8"))
    assert match is not None
    checked = dt.date.fromisoformat(match.group(1))
    age = dt.date.today() - checked
    assert age >= dt.timedelta(), (
        f"{bundle.relative_to(ROOT)} is dated {checked}, which has not happened yet — "
        f"a cell cannot pin a check in the future"
    )
    assert age <= MAX_AGE, (
        f"{bundle.relative_to(ROOT)} was checked {age.days} days ago — re-run commands.txt "
        f"or mark its cells `UNKNOWN`"
    )


#: S-0006 (§2)'s vocabulary, for the one column whose evidence is the corpus.
#: `unguarded` is a case bloomery compiles and answers **wrongly**, which is
#: what `NOT-REPRESENTED` names — D3, and the reason this mapping is written
#: down rather than applied by eye.
AS_CELL = {
    Outcome.REFUSED: "NATIVE-PREVENT",
    Outcome.ACCEPTED: "NATIVE-PLAN",
    Outcome.UNGUARDED: "NOT-REPRESENTED",
}

_ROW = re.compile(r"^\| `([0-9a-z-]+)` \| `([a-z_]+)` \| \*?\*?`([A-Z-]+)`", re.MULTILINE)


def test_matrix_rows_are_the_corpus_cases() -> None:
    """S-0006/D-4: one set of cases, or the matrix and the regression suite
    become two accounts of the same question — and the one nobody runs is the
    one that drifts."""

    expected = {
        (case.name, expectation.name): AS_CELL[expectation.outcome]
        for case in cases()
        for expectation in case.expectations
    }
    found = {
        (case, expectation): cell
        for case, expectation, cell in _ROW.findall(
            (COMPARISONS / "MATRIX.md").read_text(encoding="utf-8")
        )
    }

    assert expected, "the corpus loaded no cases; every comparison below would be vacuous"
    assert found.keys() == expected.keys(), (
        f"matrix rows do not match the corpus: "
        f"missing {sorted(expected.keys() - found.keys())}, "
        f"unknown {sorted(found.keys() - expected.keys())}"
    )
    assert found == expected, {
        key: (found[key], expected[key]) for key in found if found[key] != expected[key]
    }


#: Feature → how it appears in a bundle's `config/`, for features whose
#: presence a `sources.md` claims. Keyed on what the citation says, so a row
#: added to one bundle's table has to be true of that bundle's manifest.
FEATURES = {
    "`ratio` metric type": "type: ratio",
    "`non_additive_dimension` on a measure": "non_additive_dimension:",
}


@pytest.mark.parametrize("bundle", BUNDLES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_sources_cite_only_the_feature_set_this_bundle_uses(bundle: pathlib.Path) -> None:
    """S-0006 (§3) and D1: `sources.md` names the feature set *this*
    configuration exercises, so a reader can check the configuration is
    idiomatic rather than a strawman.

    A shared template is the failure this catches. Three bundles written from
    one file cite features two of them never declare, and the citation then
    reads as per-bundle research while being boilerplate — the same shape as a
    version string typed from memory, and just as invisible once written down.
    """

    cited = (bundle / "sources.md").read_text(encoding="utf-8")
    declared = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((bundle / "config").rglob("*.y*ml"))
    )

    for feature, marker in FEATURES.items():
        assert (feature in cited) == (marker in declared), (
            f"{bundle.relative_to(ROOT)}: sources.md "
            f"{'cites' if feature in cited else 'omits'} {feature}, "
            f"config {'declares' if marker in declared else 'does not declare'} it"
        )
