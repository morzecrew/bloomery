"""The cross-dialect target: one spec compiled on each shipped dialect
(S-0008, phase 3).

Every port claims the same two things about any spec: it either compiles, or it
is refused with a **named** reason. That is the oracle, per dialect, and it is
deliberately weaker than "the three agree". Dialects differ in capability —
DuckDB normalizes to NFC and nothing else, Trino's cast takes neither ISO
separator, Postgres has no ``regexp_extract`` — so a spec one port refuses and
another compiles is the design working (S-0025/D-3), and a target that compared
verdicts would report the design as a defect. What it does not tolerate is an
exception outside `_harness.EXPECTED` escaping a dialect-specific path, or a
refusal a caller cannot act on: the bare `BloomeryError` base, which names no
taxonomy, or one that renders empty.

Three compiles on **one** `Project`, in one process, which buys a second thing
for free: the ports share ASTs by design (S-0025/D-1), so a port that rewrote in
place instead of on a copy would surface here as a later dialect's verdict
changing because an earlier one ran first. The determinism claim proper is
`fuzz_compile_determinism.py`'s.

The emit target is fixed: an emitter is dialect-neutral by construction, so
target breadth multiplies executions without adding doors, and SQLMesh is the
one every dialect's rendering reaches.

The dictionary is `fuzz_load_project.dict` — the input space is the same one
document out of six, so it is symlinked rather than copied, which is also how it
stays in step with the spec language it spells.

Run it through the lane rather than directly::

    just fuzz cross_dialect 60

**Its own known-catchable defect** — for the sabotage check the lane owes every
target (S-0008/D-9) — is an *injected* one, and the reason it has to be is worth
recording rather than hiding. The defect this oracle is shaped for exists in the
tree and is currently **unreachable**: ``_nfc_normalize`` in
`src/bloomery/dialects/duckdb.py` raises a bare ``ValueError`` for a normal form
that is not NFC, which is outside the expectation tuple and would be caught on
duckdb while Postgres and Trino compiled the same spec — exactly what a
cross-dialect target is for. Reaching it means widening ``NormalFormName`` in
`src/bloomery/spec/quality.py` from ``Literal["nfc"]`` (the plausible
mistake S-0033/D-86 argues against) **and** a spec carrying a column quality
rule at all — which this fixture set cannot express: a mapping-level rule pulls
in the implicit ``coercible`` rule's quarantine disposition, which needs
``quarantine:`` on the entity, which needs the ingestion metadata contract in
the mapping. Three documents, and one execution replaces one. Until the fixture
set carries that surface, the sabotage proof is a raise added to one port::

    # in the render of src/bloomery/dialects/trino.py
    raise ValueError("sabotage")

and then any of the six valid seeds::

    just fuzz-repro cross_dialect fuzz/fuzz_cross_dialect_seed_corpus/mapping_orders

The target reports it from the trino leg with duckdb already compiled — which is
what it would do for the ``_nfc_normalize`` escape, on the leg that owns it. A
confirmed finding from a real run becomes a checked-in test under
`tests/unit/test_dialects/` rather than a corpus entry (S-0008/D-4).
"""

from __future__ import annotations

import sys

import atheris

with atheris.instrument_imports():
    import _harness

    from bloomery import Target, compile_project, load_catalog, load_project
    from bloomery.errors import BloomeryError

#: The shipped ports (S-0025/D-5), spelled here rather than read from the
#: registry: a registered extension dialect must not be able to change what this
#: target fuzzes, and the same three are what `PATTERN_TARGET_DIALECTS` names.
DIALECTS: tuple[str, ...] = ("duckdb", "trino", "postgres")

#: Fixed, not fuzzed — see the module docstring.
TARGET = Target.SQLMESH


def compile_on_every_dialect(sources: dict[str, str], catalog_source: str) -> tuple[str, ...]:
    """Load once, compile on each dialect, and return each leg's verdict.

    The verdicts are returned rather than compared: differing refusals are
    legitimate, and the assertions are about each leg on its own.
    """
    try:
        catalog = load_catalog(catalog_source)
        project = load_project(sources)
    except _harness.EXPECTED as exc:
        _harness.check_refusal(exc)
        return ()

    verdicts: list[str] = []

    for dialect in DIALECTS:
        try:
            compile_project(project, target=TARGET, dialect=dialect, catalog=catalog)
        except _harness.EXPECTED as exc:
            _harness.check_refusal(exc)
            # `BloomeryError` itself names no reason: a caller can tell that
            # bloomery refused and nothing about what to fix, and every refusal
            # the taxonomy covers has a class of its own
            # (`pages/docs/reference/errors.md`).
            assert type(exc) is not BloomeryError, (
                f"dialect {dialect!r} refused with no named reason: {exc}"
            )
            verdicts.append(f"{dialect}:{type(exc).__name__}")
        else:
            verdicts.append(f"{dialect}:compiled")

    return tuple(verdicts)


def one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    sources, catalog_source = _harness.fuzzed_sources(fdp)
    compile_on_every_dialect(sources, catalog_source)


def _check_fixtures() -> None:
    """The unmutated fixture set compiles on all three ports.

    A fixture set that drifted into being refused makes every execution stop at
    the same refusal, so the target would fuzz the loader, reach no port, and
    stay green forever — the dominant failure mode of a fuzzing setup. A drifted
    fixture is a loud failure here rather than a quiet one out there.
    """
    verdicts = compile_on_every_dialect(_harness.documents(), _harness.catalog_text())
    refused = [verdict for verdict in verdicts if not verdict.endswith(":compiled")]

    if len(verdicts) != len(DIALECTS) or refused:
        msg = f"fuzz/fixtures does not compile on every dialect ({verdicts}): this target fuzzes nothing"
        raise SystemExit(msg)


if __name__ == "__main__":
    _check_fixtures()
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()
