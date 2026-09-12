"""The deprecation channel (RFC 0033 D8) — the only use of Python's
``warnings`` module under ``src/``.

Three channels, and they do not blur: a log record is telemetry, an
:class:`~bloomery.Advisory` is a compile-time finding carried on a value, and
this is the interpreter-level signal a test suite run with ``-W error`` sees a
release before a spelling disappears.

Nothing in the current release is deprecated (``stability.md``), so there is no
call site to exercise. That is the state the RFC describes — "recorded before
it is needed rather than invented mid-removal" — and it is exactly why the
mechanism is tested directly: the first real deprecation must not be the run
that discovers this does not work.
"""

from __future__ import annotations

import threading
import warnings

import pytest

from bloomery.errors import BloomeryDeprecationWarning, BloomeryError, warn_deprecated
from bloomery.errors import _WARNED  # pyright: ignore[reportPrivateUsage]

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _forget() -> object:
    """The guard is process-global by design, so a test that left an entry
    behind would silence the next one — and the silence would read as a pass.
    """
    before = set(_WARNED)
    _WARNED.clear()
    yield
    _WARNED.clear()
    _WARNED.update(before)


def test_it_warns_under_its_own_category() -> None:
    """Its own category so `filterwarnings` can target bloomery precisely. A
    suite wanting bloomery's deprecations as errors, while leaving its other
    dependencies' alone, cannot express that against bare
    `DeprecationWarning`."""
    with pytest.warns(BloomeryDeprecationWarning) as caught:
        warn_deprecated("thing:", replacement="other:", removed_in="0.9.0")

    assert len(caught) == 1
    assert issubclass(caught[0].category, DeprecationWarning)


def test_the_message_names_the_replacement_and_the_release() -> None:
    """The exact text `stability.md` promises: what to write instead, and the
    release that removes the old spelling."""
    with pytest.warns(BloomeryDeprecationWarning) as caught:
        warn_deprecated("old_key:", replacement="new_key:", removed_in="0.9.0")

    message = str(caught[0].message)
    assert "old_key:" in message
    assert "new_key:" in message
    assert "0.9.0" in message


def test_it_is_not_a_bloomery_error() -> None:
    """A warning that also derived from `BloomeryError` would be caught by
    every `except BloomeryError` in every caller — turning a notice about the
    *next* release into this release's failure."""
    assert not issubclass(BloomeryDeprecationWarning, BloomeryError)


def test_a_second_call_for_one_spelling_is_silent() -> None:
    """The explicit guard, and why it is not the warnings machinery's default
    filter: that filter is caller-overridable in both directions, and an
    `always` filter would repeat this on every call."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_deprecated("thing:", replacement="other:", removed_in="0.9.0")
        warn_deprecated("thing:", replacement="other:", removed_in="0.9.0")

    assert len(caught) == 1


def test_a_different_spelling_still_warns() -> None:
    """Per spelling, not per process. A guard keyed on nothing would announce
    one deprecation and hide every later one."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_deprecated("first:", replacement="a:", removed_in="0.9.0")
        warn_deprecated("second:", replacement="b:", removed_in="0.9.0")

    assert len(caught) == 2


def test_every_call_site_fails_under_warnings_as_errors() -> None:
    """The spelling is recorded **after** the warning, and the order matters
    here and nowhere else (PR #110 review).

    Under `-W error` `warnings.warn` raises. Recording first counted a warning
    that had been converted into an exception as delivered, so a suite whose
    second test hit the same spelling got silence — one failing test pointing
    at one call site, where every deprecated call site should fail. That is the
    whole reason a `-W error` suite exists.
    """
    raised = 0

    with warnings.catch_warnings():
        warnings.simplefilter("error", BloomeryDeprecationWarning)
        for _ in range(3):
            try:
                warn_deprecated("thing:", replacement="other:", removed_in="0.9.0")
            except BloomeryDeprecationWarning:
                raised += 1

    assert raised == 3


def test_the_guard_still_bounds_a_delivered_warning() -> None:
    """The other side of the same order, and the one it must not have cost.

    Under an ordinary filter the warning is delivered rather than raised, the
    spelling is recorded, and the second call is silent — which is the whole
    point of the guard.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for _ in range(3):
            warn_deprecated("thing:", replacement="other:", removed_in="0.9.0")

    assert len(caught) == 1


def test_a_callers_ignore_filter_wins() -> None:
    """The half of the contract bloomery does not control, stated as a test.

    The guard bounds how often bloomery *emits*; it cannot show a warning a
    caller has filtered out. Documenting that without pinning it would leave
    the boundary to be discovered.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("ignore", BloomeryDeprecationWarning)
        warn_deprecated("thing:", replacement="other:", removed_in="0.9.0")

    assert caught == []


def test_best_effort_is_the_whole_contract_under_a_race() -> None:
    """"Best-effort once per process" pinned rather than assumed, the way the
    hydrator's duplicate fetch on a cold key already is.

    The guard is an unsynchronized `set`, so threads reaching a spelling's
    *first* use concurrently may each emit. This asserts the tolerated range —
    at least one — rather than exactly one, because asserting exactly one would
    make the suite flaky against behaviour the RFC deliberately allows, and
    asserting two would demand a race that usually does not happen.

    **One `catch_warnings`, in the main thread, before any worker starts.**
    `catch_warnings` replaces `warnings.showwarning` and the filter list, both
    of which are process-global, and the stdlib documents it as not
    thread-safe: eight nested managers in eight threads restore each other's
    state, so the capture itself — not the code under test — is what would
    flake (PR #110 review). Appending to the recorded list from several threads
    is fine; installing eight capturers is not.
    """
    start = threading.Barrier(8)

    def race() -> None:
        start.wait()
        warn_deprecated("racy:", replacement="other:", removed_in="0.9.0")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        threads = [threading.Thread(target=race) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert len(caught) >= 1
    assert all(issubclass(entry.category, BloomeryDeprecationWarning) for entry in caught)
