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

#: Error class name → the test node ids that constructed one. A mapping rather
#: than a set because *which* test produced it decides whether it counts: see
#: :data:`~support.docs_claims.TAXONOMY_SMOKE_MODULE`.
CONSTRUCTED: dict[str, set[str]] = {}

#: The test currently running, for :data:`CONSTRUCTED`. Constructions outside a
#: test — at import time, in a fixture teardown — are attributed to ``""`` and
#: count, since they still come from real code.
_CURRENT: list[str] = [""]

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


def pytest_configure(config: pytest.Config) -> None:
    del config
    errors_module.BloomeryError.__init__ = _recording_init  # type: ignore[method-assign]
    mutation = os.environ.get(CHAOS_ENV)
    if not mutation:
        return
    from support.chaos import apply_mutation

    apply_mutation(mutation)


def census_is_enforceable(config: pytest.Config) -> str | None:
    """``None`` when the census can be trusted, else why it cannot.

    The claim is "the **suite** produces every documented refusal", which only a
    session that collected the whole suite can make. A narrowed session is told
    so out loud rather than passing quietly: a gate that decides for itself when
    not to run is the shape that let the RFC-corpus check sit unexercised in CI
    for a whole release.

    Marker filtering is fine — ``just test`` and CI both deselect the
    Docker-backed tiers, and no documented refusal lives only there. Selecting
    by path or by ``-k`` is not.

    The whole-suite case is ``config.args`` matching the ``testpaths`` ini,
    **not** matching the rootdir: pytest fills ``args`` from ``testpaths`` when
    no path is given, so an invocation with no arguments at all arrives here as
    ``['tests']``. Comparing against the rootdir instead made every run look
    narrowed, which is how this check spent its first hour never firing.
    """
    if config.option.keyword:
        return f"narrowed by -k {config.option.keyword!r}"
    default = {str(config.rootpath), *config.getini("testpaths")}
    chosen = [arg for arg in config.args if arg.split("::")[0].rstrip("/") not in default]
    if chosen:
        return f"narrowed to {chosen}"
    return None


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail a completed, otherwise-green session that left a documented refusal
    unproduced."""
    if exitstatus != 0 or session.testsfailed:
        return  # a red suite has a better message already
    reason = census_is_enforceable(session.config)
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
