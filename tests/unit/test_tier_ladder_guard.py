"""The ladder's fourth rung has a name of its own (S-0012/D-2).

A surrogate is evidence, never the oracle (S-0012/D-1), and the place that claim
gets made is a test name: a Postgres-backed Redshift shim marked
``engine("redshift")`` reads, in a CI log and in a report nobody re-reads the body
of, as "Redshift passed". The distinction is spelled as a marker in
``pyproject.toml`` and as prose in ``tests/README.md``, and both are the kind of
claim that rots quietly — so this reads them, in the shape
``tests/unit/test_purity_guard.py`` uses to hold a ``pyproject.toml`` claim.

There is no surrogate lane yet. That is the point: the selector has to exist
before the four per-engine documents can name their first one honestly.
"""

from __future__ import annotations

import pathlib
import tomllib

import pytest

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parents[2]


def markers() -> list[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return config["tool"]["pytest"]["ini_options"]["markers"]


def test_the_fourth_rung_has_a_selector() -> None:
    """Without this the tree can only say ``engine``, which overstates a shim."""
    assert any(marker.startswith("surrogate(name):") for marker in markers()), (
        "the surrogate rung has gone missing from the marker table; a lane backed "
        "by an emulator, a Spark session or a Postgres shim would have to select "
        "and report as the engine matrix does"
    )


def test_the_selector_is_distinct_from_engine() -> None:
    """S-0012/D-9 rejects the parameter form: ``engine`` keeps meaning Docker plus
    the real engine, so a CI log separates the two without anyone reading a test
    body."""
    table = {marker.split(":", 1)[0]: marker.split(":", 1)[1] for marker in markers()}
    assert "surrogate(name)" in table and "engine(name)" in table
    assert "real engine" in table["engine(name)"]
    for banned in ("emulator", "Spark", "shim"):
        assert banned not in table["engine(name)"], (
            f"`engine` has taken on {banned!r}; the two rungs have merged"
        )


def test_the_table_records_why() -> None:
    """The marker table is where a person running the suite reads the ladder, and
    a selector whose reason lives only in a decision row is a convention."""
    config = (ROOT / "pyproject.toml").read_text()
    assert "S-0012/D-9" in config, "the reason for the marker form is not beside it"
    assert "S-0012/D-1" in config, "a surrogate is evidence, never the oracle — say so"


def test_the_tier_list_carries_the_same_distinction() -> None:
    readme = (ROOT / "tests" / "README.md").read_text()
    assert "`surrogate(<name>)`" in readme, "the tier list still has eight selectors"
    assert "never the oracle" in readme, (
        "the tier list names the rung without saying what a green one may not claim"
    )
