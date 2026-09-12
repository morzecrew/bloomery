"""The logger surface (RFC 0033 §4, D1-D4) — the posture, not the messages.

Message text is not API (§7); only the logger *names* are. So nothing here
asserts what a record says, and nothing anywhere asserts behaviour *through*
log output — D3 forbids it, and a suite that read a log to decide whether the
compiler worked would have made logging load-bearing by testing it.

What is asserted is the posture a library owes its embedder: one do-nothing
handler, no level, no format, and artifacts that do not move when someone
listens.
"""

from __future__ import annotations

import logging

import pytest

from bloomery import build_project_ir, compile_project
from support.compiling import load_fixture

pytestmark = pytest.mark.unit

#: The names §4 declares. The stable surface is this set — a caller tunes
#: against it — so it is pinned here rather than derived from whatever the
#: modules happen to call `getLogger` with.
DECLARED = (
    "bloomery",
    "bloomery.spec",
    "bloomery.resolve",
    "bloomery.guardrails",
    "bloomery.emit",
    "bloomery.runtime",
    "bloomery.planner",
)


def test_the_package_installs_exactly_one_null_handler() -> None:
    """D1, the library's only configuration act.

    Exactly one, and a `NullHandler`: a second handler would double every
    record for the caller, and any other kind would write somewhere the caller
    did not ask for.
    """
    handlers = logging.getLogger("bloomery").handlers

    assert len(handlers) == 1
    assert type(handlers[0]) is logging.NullHandler


def test_the_package_sets_no_level() -> None:
    """D1's other half, and the one that is easy to get wrong in the helpful
    direction.

    A level here would be a level chosen for every embedder in the process.
    `NOTSET` is what lets `logging.getLogger("bloomery").setLevel(DEBUG)` work
    from outside — a logger pinned to INFO by the library ignores it.
    """
    assert logging.getLogger("bloomery").level == logging.NOTSET


def test_the_package_leaves_propagation_alone() -> None:
    """Records reach the caller's root handlers, which is the whole point of
    attaching a `NullHandler` rather than silencing the tree."""
    assert logging.getLogger("bloomery").propagate is True


@pytest.mark.parametrize("name", DECLARED)
def test_every_declared_logger_hangs_off_the_package_root(name: str) -> None:
    """Tuning `bloomery` has to reach all of them, or §4's hierarchy is a list
    of unrelated names rather than a hierarchy."""
    logger = logging.getLogger(name)

    assert logger is logging.getLogger("bloomery") or logger.name.startswith("bloomery.")


def test_no_record_is_emitted_at_warning_or_above(caplog: pytest.LogCaptureFixture) -> None:
    """D4: there are no WARNING-level records at all.

    That severity belongs to the advisory channel (§5), and putting a finding
    in a log is exactly the "only logged" failure D5 forbids. Asserted over a
    real compile rather than by grepping for `.warning(` — a call reached
    through an alias would pass the grep.
    """
    project, catalog = load_fixture("ecom_basic")

    with caplog.at_level(logging.DEBUG, logger="bloomery"):
        compile_project(project, target="sqlmesh", dialect="duckdb", catalog=catalog)

    assert [record for record in caplog.records if record.levelno >= logging.WARNING] == []


def test_a_compile_narrates_every_stage(caplog: pytest.LogCaptureFixture) -> None:
    """§4's INFO budget: one record per stage per compile, bounded.

    This asserts the *count* and the *names*, never the text. A stage that
    stopped narrating would be invisible to a caller who turned INFO on for
    exactly that reason.
    """
    project, catalog = load_fixture("ecom_basic")

    with caplog.at_level(logging.INFO, logger="bloomery"):
        build_project_ir(project, catalog=catalog)

    assert {record.name for record in caplog.records} == {
        "bloomery.resolve",
        "bloomery.guardrails",
    }


def test_the_info_budget_does_not_scale_with_the_project(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """"Bounded, safe to leave on in production" is a claim about growth.

    A project with more entities and more mappings must not produce more INFO
    records than a minimal one — otherwise the level a caller leaves on in a
    scheduler grows with their spec.
    """
    counts = []

    for name in ("minimal", "ecom_basic"):
        project, catalog = load_fixture(name)
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="bloomery"):
            build_project_ir(project, catalog=catalog)
        counts.append(len(caplog.records))

    assert counts[0] == counts[1]


def test_a_hydration_miss_narrates_at_debug_and_not_at_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """§9 Q2, decided at DEBUG (`logs/T-0048.md`), asserted by provoking a miss
    rather than by grepping the module for `.info(`.

    A grep is what this test used to be, and it was wrong for the reason a
    sibling docstring here already gives about `WARNING`: a call reached
    through an alias passes the grep. The claim is about what a *caller* sees,
    so the test is a caller.

    A hydration miss is per-request, and §4's INFO budget is per compile — INFO
    here would break "bounded, safe to leave on" in exactly the hot service §9
    Q2 worries about.
    """
    from bloomery.naming import DefaultNaming
    from bloomery.runtime import LruManifestHydrator

    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog=catalog)
    hydrator = LruManifestHydrator(DefaultNaming())

    with caplog.at_level(logging.DEBUG, logger="bloomery"):
        hydrator.get(ir)

    runtime = [record for record in caplog.records if record.name == "bloomery.runtime"]

    assert len(runtime) == 1
    assert runtime[0].levelno == logging.DEBUG


def test_a_hydration_miss_is_silent_at_info(caplog: pytest.LogCaptureFixture) -> None:
    """The other half, and the one that makes the level a decision rather than
    an observation: at INFO the per-request seam says nothing at all."""
    from bloomery.naming import DefaultNaming
    from bloomery.runtime import LruManifestHydrator

    project, catalog = load_fixture("ecom_basic")
    ir = build_project_ir(project, catalog=catalog)
    hydrator = LruManifestHydrator(DefaultNaming())

    with caplog.at_level(logging.INFO, logger="bloomery"):
        hydrator.get(ir)

    assert [record for record in caplog.records if record.name == "bloomery.runtime"] == []
