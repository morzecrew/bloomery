"""`load_project` takes strings, and that is the supported way in (RFC 0068).

Compiling a spec set that never touched this filesystem is not a feature — it
is the ordinary path, and it is what makes "reproduce March" two steps rather
than a subsystem. RFC 0063 proposed a history resolver, a git adapter and an
`--as-of` flag; RFC 0068 rejected all three, on the grounds that the caller
already holds the text and the compiler has no notion of time.

What that rejection leaves is a public signature with nothing holding it still.
`load_project(Mapping[str, str])` has been the entry point since RFC 0002 and
had no test asserting it stays one — so a refactor narrowing it to something
path-shaped would break every caller who assembles specs from a database, a
tarball or an object store, and would break them outside this repository where
no suite would notice.

These are that test. They are deliberately about the *shape* of the door rather
than about what is behind it: the compilers, emitters and guardrails have their
own suites.
"""

from __future__ import annotations

import builtins

import pytest

from bloomery import (
    build_project_ir,
    compile_project,
    load_catalog,
    load_project,
    plan,
)
from bloomery.cli import io
from bloomery.ir import project_fingerprint
from support.compiling import FIXTURES

pytestmark = pytest.mark.unit


def _sources(name: str = "ecom_basic") -> tuple[dict[str, str], str | None]:
    """A fixture as the strings a caller would have fetched.

    Read through the CLI's own door, which is the point: everything past this
    line is what a caller gets from a `SELECT`, a `git show` or a tarball, and
    the library cannot tell the difference.
    """

    return io.read_spec_directory(str(FIXTURES / name))


def test_a_project_assembled_from_strings_compiles() -> None:
    """The claim RFC 0068 §3 rests on, asserted rather than read."""
    sources, catalog_text = _sources()

    project = load_project(sources)
    catalog = load_catalog(catalog_text) if catalog_text else None
    artifacts = compile_project(project, target="sqlmesh", dialect="duckdb", catalog=catalog)

    assert artifacts
    assert project_fingerprint(build_project_ir(project, catalog)).startswith("blm1:")


def test_the_compile_half_opens_no_file() -> None:
    """RFC 0003's boundary, asserted at runtime rather than only by the lint rule.

    The ban on `os` and `pathlib` under `src/bloomery/` is static and catches
    the import; this catches the behaviour, including a read reached through a
    third-party package the import rule does not govern.

    The path is warmed first. A lazy import inside the compile would open a
    module file and fail this for a reason that has nothing to do with the
    claim — so the same work runs once unguarded, and only the second run is
    watched.
    """
    sources, catalog_text = _sources()
    catalog = load_catalog(catalog_text) if catalog_text else None
    compile_project(load_project(sources), target="sqlmesh", dialect="duckdb", catalog=catalog)

    opened: list[object] = []

    def _refuse(file: object, *args: object, **kwargs: object) -> object:
        opened.append(file)
        msg = f"the compile half opened {file!r}"
        raise AssertionError(msg)

    original = builtins.open
    builtins.open = _refuse  # type: ignore[assignment]
    try:
        project = load_project(sources)
        artifacts = compile_project(
            project, target="sqlmesh", dialect="duckdb", catalog=catalog
        )
        _ = project_fingerprint(build_project_ir(project, catalog))
    finally:
        builtins.open = original  # type: ignore[assignment]

    assert artifacts
    assert not opened


def test_two_string_sets_still_diff() -> None:
    """RFC 0063's P3 — "so a CI job can compare two instants" — shown to exist
    without the flag it proposed. `plan()` takes two IRs and asks nothing about
    where either came from.
    """
    sources, catalog_text = _sources()
    catalog = load_catalog(catalog_text) if catalog_text else None
    before = build_project_ir(load_project(sources), catalog)

    # A materialization change: classified, and it dangles no reference — a
    # rename would, and would fail in the resolver before `plan` ever ran,
    # which would make this a test of reference validation instead.
    edited = dict(sources)
    edited["marts"] = edited["marts"].replace(
        "    cost_hint: 2", "    materialization: full\n    cost_hint: 2", 1
    )
    assert edited["marts"] != sources["marts"], "the fixture moved; this edit changed nothing"
    after = build_project_ir(load_project(edited), catalog)

    report = plan(before, after)

    assert [change.subject for change in report.changes] == ["mart:order_items"]
    # And the control: the same strings on both sides are the empty plan, so the
    # assertion above is about the edit rather than about `plan` always talking.
    assert not plan(before, before).changes
