"""What every fuzz target shares: the expectation tuple, the valid documents a
target mutates one field of, and the refusal-quality check (S-0008).

Not a package and not importable from ``src/``: this directory is dev-only,
ships in no wheel, and nothing under ``src/bloomery/`` may import it.
"""

from __future__ import annotations

from pathlib import Path

from bloomery import Catalog, Project, load_catalog, load_project
from bloomery.errors import BloomeryError

#: The compile boundary's claim, restated as code (S-0008/D-1).
#:
#: `pages/docs/reference/errors.md` tells a caller that `except BloomeryError`
#: is sufficient. Any other exception crossing `load_project`,
#: `compile_project` or the planner is therefore a finding — either a code bug
#: or a documentation lie, with nothing in between — so a target catches this
#: and nothing else, and Atheris reports whatever is left.
#:
#: **Never widen this to make a run green.** An addition here is a change to
#: the error taxonomy and carries the error reference's own review bar
#: (S-0008/D-3): it lands with a fix translating the exception into a
#: `BloomeryError`, or with a recorded decision in the error reference that the
#: escape is intended. A tuple that grows to fit the last crash is how a fuzz
#: lane becomes decorative.
#:
#: What deliberately stays out, and why: `yaml.YAMLError`, because the loader
#: owns YAML and a raw parser error reaching a caller is a leaked abstraction;
#: `SqlglotError` and `TokenError`, which are the escape this lane descends
#: from; `RecursionError`, because catching it at a harness hides an unbounded
#: recursion rather than bounding it; `KeyError`, `AttributeError` and
#: `TypeError`, the signature of a spec field read without validation;
#: `UnicodeDecodeError`, `MemoryError`, `OverflowError`; and `AssertionError`,
#: because a harness never catches its own oracle.
EXPECTED: tuple[type[BaseException], ...] = (BloomeryError,)

#: The valid document set a target holds fixed while mutating one field of it.
#:
#: The test corpus's richest project rather than a copy under `fuzz/`: it is
#: six document kinds (entity model, mappings, marts, metrics, exports,
#: exposures) beside a catalog, every one of them kept valid by the test tiers
#: that read it. A copy here would be valid on the day it was made and would
#: then rot into a set that refuses at document one — where a fuzzer spends
#: every execution and finds nothing.
FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ecom_basic"


def documents() -> dict[str, str]:
    """The fixture's spec documents, by `load_project`'s own naming."""

    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(FIXTURE.glob("*.yaml"))
        if path.name != "catalog.yaml"
    }


def catalog_text() -> str:
    """The fixture's catalog, as text, so a target can splice a field."""

    return (FIXTURE / "catalog.yaml").read_text(encoding="utf-8")


def valid_project() -> Project:
    """The fixture as a loaded `Project`.

    Raising here is a finding about the fixture, not about the input under
    test, and it is better read as a crash on execution zero than as a lane
    that runs for an hour over a project nothing reaches.
    """

    return load_project(documents())


def valid_catalog() -> Catalog:
    return load_catalog(catalog_text())


def check_refusal(error: BloomeryError) -> None:
    """The refusal-quality oracle: a refusal a caller cannot read is a finding.

    Rendering is asserted rather than assumed because the batched aggregates
    are where message-formatting bugs live — the first refusal in a batch
    formats fine and the twelfth is the one carrying the field that is `None`.
    """

    assert str(error).strip(), f"{type(error).__name__} rendered empty"
    for collected in error.collected:
        assert str(collected).strip(), (
            f"{type(error).__name__} collected a {type(collected).__name__} that rendered empty"
        )
