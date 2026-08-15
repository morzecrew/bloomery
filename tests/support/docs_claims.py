"""Reading the docs' claims out of the pages (RFC 0025 §5.1).

Shared because two consumers need the same answer from opposite ends of the
session: `tests/unit/test_docs_floor.py` checks the documented set against the
exported one inside a test, and `tests/conftest.py` checks it against the set
the whole run produced, at session finish. Parsing the page twice would let the
two disagree about what "documented" means — and the one that disagreed
quietly would be the census, which has no test of its own to fail.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import bloomery.errors as errors_module
from bloomery.errors import BloomeryError

__all__ = [
    "ERRORS_PAGE",
    "TAXONOMY_SMOKE_MODULE",
    "census_exempt_classes",
    "documented_error_classes",
    "exported_error_classes",
]

#: The module that constructs every exported class as ``cls("boom")`` to check
#: the hierarchy. Its constructions do **not** count toward the refusal census:
#: a smoke test that instantiates the whole ``__all__`` would satisfy "this
#: refusal is produced somewhere" for every class that exists, which is the
#: gate measuring itself. Discovered by building the census and finding it
#: could not fail.
TAXONOMY_SMOKE_MODULE = "tests/unit/test_errors.py"

#: The reference's own words for "bloomery never raises this".
_NEVER_RAISED = "never raised by bloomery"

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "pages" / "docs"
ERRORS_PAGE = DOCS / "reference" / "errors.md"

#: A row of the reference's per-class table: ``| `FanoutRisk` | guardrails | … |``.
#: The ASCII hierarchy above it is deliberately *not* the source: it is a
#: drawing, and a name can appear there with no row explaining when it is
#: raised — which is the half a reader actually needs.
_TABLE_ROW = re.compile(r"^\|\s*`([A-Z][A-Za-z]+)`\s*\|", re.M)


def documented_error_classes() -> set[str]:
    """Every error class named by a row of the reference's class table."""
    return set(_TABLE_ROW.findall(ERRORS_PAGE.read_text()))


def census_exempt_classes() -> set[str]:
    """Documented classes the census must not require a real refusal for.

    Derived from the page rather than listed here, which is the point: adding
    an exemption means editing the public reference to say a class is
    ``never raised by bloomery``, where a reader and a reviewer both see it. A
    hand-kept list beside the gate would be the curated-table failure the
    census exists to avoid — an omission nobody can see.

    ``BloomeryError`` is exempt on a different footing: it is the base every
    other row is a kind of, so "some code path produces it" is answered by all
    52 of them and asserting it separately measures nothing.
    """
    exempt = {"BloomeryError"}
    for line in ERRORS_PAGE.read_text().splitlines():
        match = _TABLE_ROW.match(line)
        if match and _NEVER_RAISED in line:
            exempt.add(match[1])
    return exempt


def exported_error_classes() -> set[str]:
    """Every ``BloomeryError`` subclass in ``bloomery.errors.__all__``.

    Read off ``__all__`` rather than off the module's contents, because
    ``__all__`` is the SemVer surface the stability reference names. A class
    defined but unexported is an implementation detail with nothing to
    document — ``VendorError`` is the live example.
    """
    return {
        name
        for name in errors_module.__all__
        if inspect.isclass(getattr(errors_module, name))
        and issubclass(getattr(errors_module, name), BloomeryError)
    }
