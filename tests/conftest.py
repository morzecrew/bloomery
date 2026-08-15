"""Suite-wide pytest configuration.

Two jobs, both of which have to run around the whole session rather than inside
a test.

The first is the chaos meta-test's entry point (RFC 0016 §6): when
``BLOOMERY_CHAOS_MUTATION`` names a mutation, the lowering is deformed *before
collection* — test modules compile fixtures at import time, so a hook that ran
any later would test the unmutated compiler.

The second is the **refusal census** (RFC 0025 §5.1 item 2): every error class
`pages/docs/reference/errors.md` documents must actually be constructed
somewhere in the suite. A documented refusal nothing can produce is either a
class that should be deleted or a page that should be — the gate does not care
which, only that the two agree (D2). It lives here because the claim is about
the *session*: no single test can observe it.

The environment variable is read in the **test** process only; ``src/bloomery/``
reads no environment at all (RFC 0003), and the determinism guard enforces that.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import bloomery.errors as errors_module

if TYPE_CHECKING:
    import pytest

#: Set by ``tests/chaos/test_mutation_harness.py`` in a subprocess.
CHAOS_ENV = "BLOOMERY_CHAOS_MUTATION"

#: The opt-in for the refusal census. Declared rather than inferred — see
#: :func:`census_is_enforceable`.
CENSUS_FLAG = "--refusal-census"

#: Error class name → the test node ids that constructed one. A mapping rather
#: than a set because *which* test produced it decides whether it counts: see
#: :data:`~support.docs_claims.TAXONOMY_SMOKE_MODULE`.
CONSTRUCTED: dict[str, set[str]] = {}

#: The test currently running, for :data:`CONSTRUCTED`. Constructions outside a
#: test — at import time, in a fixture teardown — are attributed to ``""`` and
#: count, since they still come from real code.
_CURRENT: list[str] = [""]

#: How many items this session deselected, via the public ``pytest_deselected``
#: hook. Read against the collected count to tell a *deselecting* marker
#: expression from a *selecting* one — see :func:`census_is_enforceable`.
_DESELECTED: list[int] = [0]

_ORIGINAL_INIT = errors_module.BloomeryError.__init__


def _recording_init(self: errors_module.BloomeryError, *args: object, **kwargs: object) -> None:
    """``BloomeryError.__init__``, plus a note of who built it.

    Patched rather than sampled from ``pytest.raises``: a refusal that is
    constructed and *collected* into a batched aggregate is still produced by
    the code, and most guardrail leaves never surface as the raised type.
    """
    CONSTRUCTED.setdefault(type(self).__name__, set()).add(_CURRENT[0])
    _ORIGINAL_INIT(self, *args, **kwargs)  # type: ignore[arg-type]


def pytest_runtest_setup(item: pytest.Item) -> None:
    _CURRENT[0] = item.nodeid


def pytest_deselected(items: list[pytest.Item]) -> None:
    _DESELECTED[0] += len(items)


def pytest_configure(config: pytest.Config) -> None:
    del config
    errors_module.BloomeryError.__init__ = _recording_init  # type: ignore[method-assign]
    mutation = os.environ.get(CHAOS_ENV)
    if not mutation:
        return
    from support.chaos import apply_mutation

    apply_mutation(mutation)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        CENSUS_FLAG,
        action="store_true",
        default=False,
        help=(
            "Assert that every error class errors.md documents was produced by "
            "some code path during this session (RFC 0025 §5.1). Only meaningful "
            "on a whole-suite run; `just test`, `just coverage` and CI pass it."
        ),
    )


def census_is_enforceable(
    config: pytest.Config, collected: int, deselected: int
) -> str | None:
    """``None`` when the census can be trusted, else why it cannot.

    The claim is "the **suite** produces every documented refusal", which only a
    session that ran the whole suite can make. The precondition is therefore
    **declared** by the invocation rather than inferred from it, and the
    declaration is asserted by
    :func:`tests.unit.test_docs_floor.test_every_full_suite_invocation_asks_for_the_census`
    — a flag that silently stopped being passed would be a gate that silently
    stopped running.

    Inferring it was tried and was wrong twice, which is why it is not inferred
    now. Comparing ``config.args`` against the rootdir made *every* session look
    narrowed, because pytest fills ``args`` from the ``testpaths`` ini; fixing
    that left a worse bug, since a marker-selected run like ``pytest -m golden``
    is narrower than anything ``args`` can show and failed with 49 refusals the
    golden tier never had reason to produce. A precondition that has to be
    guessed from the command line is one that will be guessed wrong again.

    ``-k`` is still refused on top of the flag: ``just test -k something``
    forwards its arguments, and the census would otherwise fail a run the
    developer narrowed on purpose.

    So is a **selecting** marker expression. ``pytest -m golden --refusal-census``
    is someone pointing the flag at a tier, and it failed with 49 refusals the
    golden tier never had reason to produce. The rule is *collected must exceed
    deselected*, which needs no threshold to maintain and no expression to
    parse: a deselecting run keeps almost everything and drops the Docker
    tiers, while a marker that names a tier keeps a sliver and drops the rest —
    two orders of magnitude apart, so the comparison needs no tuning as the
    suite grows. The counts come from pytest's own hooks rather than from the
    command line, which is the whole lesson of this function's history.
    """
    if not config.getoption(CENSUS_FLAG):
        return f"not requested ({CENSUS_FLAG} is passed by `just test` and CI)"
    if config.option.keyword:
        return f"narrowed by -k {config.option.keyword!r}"
    if collected <= deselected:
        return (
            f"selecting rather than deselecting — {collected} collected against "
            f"{deselected} deselected, which is a slice of the suite rather than "
            "the suite less its Docker tiers"
        )
    return None


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail a completed, otherwise-green session that left a documented refusal
    unproduced."""
    if exitstatus != 0 or session.testsfailed:
        return  # a red suite has a better message already
    reason = census_is_enforceable(
        session.config, session.testscollected, _DESELECTED[0]
    )
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reason is not None:
        if reporter is not None:
            reporter.write_line(f"refusal census: not enforced ({reason})", yellow=True)
        return
    from support.docs_claims import (
        TAXONOMY_SMOKE_MODULE,
        census_exempt_classes,
        documented_error_classes,
    )

    def produced(name: str) -> bool:
        return any(
            not node.startswith(TAXONOMY_SMOKE_MODULE)
            for node in CONSTRUCTED.get(name, frozenset())
        )

    missing = sorted(
        name
        for name in documented_error_classes() - census_exempt_classes()
        if not produced(name)
    )
    if not missing:
        return
    session.exitstatus = 1
    if reporter is not None:
        reporter.write_line(
            "refusal census: errors.md documents refusals no code path produced — "
            f"{missing}. A documented refusal nothing can provoke is either a class "
            "to delete or a page to correct (RFC 0025 D2). A class bloomery "
            f"deliberately never raises says so in its row ({TAXONOMY_SMOKE_MODULE} "
            "constructing it does not count).",
            red=True,
        )
