"""The in-process determinism target: one spec compiled three times
(S-0008, phase 3).

``compile_project`` is documented as a pure function of its inputs — same specs
in, byte-identical artifacts out. This target asserts the half of that claim a
single process can see, and it takes three compiles rather than two because the
two failures behind it are distinct:

*Compiler state* — anything carried between calls. Two compiles of the same
:class:`~bloomery.spec.Project` disagree, and the second call read something the
first left behind.

*Caching keyed on object identity* — a memo that answers by ``id()`` rather than
by value. Two compiles of one object agree perfectly and a freshly loaded object
built from the same bytes does not, which is why the third compile exists and
why it re-reads the documents instead of reusing the parsed project.

The full claim — across processes and across ``PYTHONHASHSEED`` — is not
assertable in process. It belongs to the replay job in
`rfcs/0072-continuous-fuzzing-in-ci.md`, which is what this target gives that
job a corpus for; the named guard over the *fixed* fixture is
`tests/unit/test_determinism_guard.py`, and what this adds is arbitrary spec
text rather than one spec.

The emit target and the dialect are fixed rather than fuzzed. The claim is about
repeated calls, not about breadth, and breadth across the three shipped dialects
is `fuzz_cross_dialect.py`'s.

A refusal is a verdict like any other and is compared like one: a spec that is
refused must be refused the same way all three times, by class and by rendered
message. The freshly loaded project, though, is loaded **unguarded** — these
exact bytes loaded a moment ago, so a refusal on the second reading is a
determinism finding in the loader rather than a verdict about the document, and
catching it would file it as the ordinary refusal it is not.

The dictionary is `fuzz_load_project.dict` — the input space is the same one
document out of six, so it is symlinked rather than copied, which is also how it
stays in step with the spec language it spells.

Run it through the lane rather than directly::

    just fuzz compile_determinism 60

**Its own known-catchable defect** — for the sabotage check the lane owes every
target (S-0008/D-9) — is an *injected* one, not a re-narrowed guard, and that is
worth stating plainly because the other targets' are re-narrowed guards. There
is no line in the current tree whose deletion this oracle catches: the purity is
structural (frozen dataclasses, tuples rather than sets in the fingerprint
stream, canonical text in the IR, a copy at every dialect port's door), and
removing *every* AST copy on the emit path — ``SqlExpr.ast``, ``capture_group``'s
``transform``, the ports' entry copies — leaves all four targets' artifacts
byte-identical across compiles on all three dialects. The fixture set is the
other half of the reason: it reaches no column quality rule, so
``physical_type`` is never called during a compile of it at all.

So the defect is added, at the one seam both legs pass through — the fingerprint
in ``src/bloomery/compile.py``'s ``EmitContext``, which every artifact but
MetricFlow's manifest carries into its content. Either half of the oracle can be
driven from that one line, which is the point of injecting it there::

    fingerprint=project_fingerprint(ir) + hex(id(project)),   # identity-keyed
    fingerprint=project_fingerprint(ir) + hex(len(_SEEN)),    # compiler state

Then replay any of the six valid seeds::

    just fuzz-repro compile_determinism fuzz/fuzz_compile_determinism_seed_corpus/marts

The first spelling is caught by the third compile only (twice on one project
agrees, the freshly loaded one does not); the second by the second compile.
Either way :func:`_check_fixtures` reaches it before the replay does, because it
runs the oracle on the clean fixture set first — which is the loudest place for a
defect that every input shares. A
confirmed finding from a real run becomes a checked-in test under
`tests/unit/test_determinism_guard.py` rather than a corpus entry (S-0008/D-4).
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import atheris

with atheris.instrument_imports():
    import _harness

    from bloomery import Target, compile_project, load_catalog, load_project

if TYPE_CHECKING:
    from bloomery.spec import Catalog, Project

#: Fixed, not fuzzed — see the module docstring. SQLMesh is the primary target
#: and duckdb the dialect the rest of the lane compiles on.
TARGET = Target.SQLMESH
DIALECT = "duckdb"


def _outcome(project: Project, catalog: Catalog) -> tuple[object, ...]:
    """One compile's verdict as short comparable data.

    The checksum is the content's SHA-256, so comparing it compares every byte
    of the artifact while leaving an assertion message a person can read in a
    crash file — a diff of two full artifact sets is megabytes, and the message
    is what gets read first.
    """
    try:
        artifacts = compile_project(project, target=TARGET, dialect=DIALECT, catalog=catalog)
    except _harness.EXPECTED as exc:
        _harness.check_refusal(exc)
        return ("refused", type(exc).__name__, str(exc))

    return ("compiled", *((art.path, art.kind.value, art.checksum) for art in artifacts))


def one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    sources, catalog_source = _harness.fuzzed_sources(fdp)

    try:
        catalog = load_catalog(catalog_source)
        project = load_project(sources)
    except _harness.EXPECTED as exc:
        _harness.check_refusal(exc)
        return

    first = _outcome(project, catalog)
    second = _outcome(project, catalog)

    assert first == second, f"one Project compiled twice disagreed:\n{first}\n{second}"

    # Unguarded on purpose: these bytes loaded a moment ago, so anything raised
    # here — `BloomeryError` included — is a finding rather than a verdict.
    fresh = _outcome(load_project(sources), load_catalog(catalog_source))

    assert first == fresh, f"a freshly loaded Project compiled differently:\n{first}\n{fresh}"


def _check_fixtures() -> None:
    """The unmutated fixture set compiles, and compiles identically three times.

    A fixture set that drifted into being refused makes every execution stop at
    the same refusal, so the target would fuzz the loader, never reach a
    compile, and stay green forever — the dominant failure mode of a fuzzing
    setup. Running the oracle itself on the clean set rules out both that and an
    oracle that cannot pass.
    """
    sources = _harness.documents()
    catalog_source = _harness.catalog_text()
    outcome = _outcome(load_project(sources), load_catalog(catalog_source))

    if outcome[0] != "compiled":
        msg = f"fuzz/fixtures does not compile ({outcome[1:]}): this target fuzzes nothing"
        raise SystemExit(msg)

    # The oracle itself, on a seed-shaped input whose "mutation" is the real
    # document: an oracle that cannot pass is as broken as one that cannot fail.
    slots = sorted([*sources, _harness.CATALOG])
    one_input(sources["marts.yaml"].encode() + bytes([slots.index("marts.yaml")]))


if __name__ == "__main__":
    _check_fixtures()
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()
