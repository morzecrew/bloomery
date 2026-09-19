"""The parse doors: every `sqlglot.parse_one` this project reaches that the
spec layer's `SqlText` validator does not stand in front of (S-0008).

Run it:

    just fuzz parse_doors 60

Three doors, and the third is the one reading cannot clear.

*Authored* — text spliced into a catalog recipe's `expr:`, which the validator
does guard, then re-parsed by the IR builder, the arithmetic and grain
guardrails and the advisory walk. The guard is a proof about the stack position
the validator ran from, and every one of those re-parses runs from a different
one.

*Registry* — a step body, which reaches `resolve/steps.py` having passed no
validator at all: a registry is assembled in Python rather than authored.

*Composed* — two fragments, each individually parseable, concatenated into one
expression that is then re-parsed. Validity is not closed under composition and
no per-field validator can see that, which is why this door exists separately
from the first.

**The known-catchable defect** (S-0008, `tests`): narrow either handler in
`src/bloomery/evidence.py` or `src/bloomery/resolve/steps.py` back to
`except SqlglotError`, or narrow `_parses_as_sql` in
`src/bloomery/spec/common.py` the same way, and this target must report inside
a bounded run. An oracle that does not catch the defect that motivated it is
not an oracle. Both were re-checked by hand against the seed corpus when this
target landed; see `pages/docs/contributing/fuzzing.md`.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parent))

with atheris.instrument_imports():
    import _harness
    from bloomery import (
        Target,
        build_project_ir,
        compile_project,
        evaluate,
        load_catalog,
        load_project,
    )
    from bloomery.errors import BloomeryError
    from bloomery.steps import StepManifest, StepRegistry

#: The recipe expression the authored doors replace. Chosen because it divides:
#: the advisory walk's `_divides` only re-parses an expression on its way to
#: deciding that, so a replacement that never looks like a division reaches one
#: door fewer.
_AUTHORED = '{id: from_total, requires: [line_total, quantity], expr: "line_total / quantity"}'

#: The registry door's project: one wired step whose body comes from the
#: fuzzer. Held here rather than read from a fixture because no fixture wires a
#: `sql_model` with a body the caller supplies, which is the shape of the door.
_STEPS_PROJECT = {
    "entity_model.yaml": "spec_version: 1\nentities: {}\n",
    "steps.yaml": "steps_version: 1\nsteps:\n  - use: s@1\n    outputs: {out: silver.a}\n",
}
_STEPS_MANIFEST = {
    "ref": "s",
    "version": 1,
    "kind": "sql_model",
    "determinism": "pure",
    "runtime_lock": "sha256:a91f",
    "inputs": {},
    "parameters": {},
    "outputs": {"out": {"grain": "g", "key": ["k"], "produces": {"k": {"type": "string"}}}},
}


def _authored(expr: str) -> None:
    """A catalog recipe carrying `expr`, compiled against the valid project."""

    recipe = json.dumps(expr)  # a JSON string is a YAML double-quoted scalar
    text = _harness.catalog_text()
    # The fixture is shared with the test tiers and may be edited by them. A
    # splice that silently matched nothing would leave this target fuzzing a
    # constant, which is the failure mode a green lane hides best.
    assert _AUTHORED in text, f"the fixture catalog no longer carries {_AUTHORED!r}"
    catalog = load_catalog(
        text.replace(
            _AUTHORED, f"{{id: from_total, requires: [line_total, quantity], expr: {recipe}}}"
        )
    )
    project = _harness.valid_project()

    # `evaluate` has the stronger contract of the two and gets the stronger
    # oracle: a spec-level problem comes back as a *value*, so a refusal
    # raised out of it is a finding even though a refusal raised out of
    # `compile_project` is the normal case. Re-raised as an `AssertionError`
    # rather than left to the handler below, which would file the finding
    # under "an input this lane expects to be refused".
    try:
        evaluate(project, catalog=catalog)
    except BloomeryError as refusal:
        msg = f"evaluate() raised {type(refusal).__name__} instead of returning it"
        raise AssertionError(msg) from refusal

    compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog)


def _registry(body: str) -> None:
    """A step body reaching `resolve/steps.py` past every validator."""

    build_project_ir(
        load_project(_STEPS_PROJECT),
        steps=StepRegistry(
            {("s", 1): StepManifest.model_validate(_STEPS_MANIFEST)},
            sql_bodies={("s", 1): body},
        ),
    )


def _text(fdp: atheris.FuzzedDataProvider, size: int) -> str:
    """Bytes as text, decoded here rather than by `ConsumeUnicodeNoSurrogates`.

    That helper spends the first byte choosing an encoding, which makes a seed
    file something other than the text it appears to be: a hand-written seed of
    four hundred parentheses arrived at the door as mojibake and the target ran
    for two thousand executions without reaching the nesting it was seeded
    with. A spec document is text, so the decode belongs here where a seed file
    reads as what it feeds.
    """

    return fdp.ConsumeBytes(size).decode("utf-8", errors="replace")


def _at_depth(frames: int, call: Callable[[], None]) -> None:
    """Run `call` with `frames` extra frames beneath it.

    The caller's own stack is an input bloomery does not control and cannot
    see, and SQLGlot's parser recurses per nesting level — so an expression the
    spec layer's validator accepted is re-parsed later from a different stack
    position, with fewer frames left than the proof was made at. Measured: 51
    nested levels survive from a shallow frame and 35 from 300 frames down.
    Fuzzing the depth alongside the text is what makes that band reachable
    rather than a paragraph in a design document.
    """

    if frames > 0:
        _at_depth(frames - 1, call)
    else:
        call()


def one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    door = fdp.ConsumeIntInRange(0, 2)
    # Bounded, and the bound is the honest part: a caller that has burned most
    # of the interpreter's stack before calling anything gets a
    # `RecursionError` out of any library, and reporting that as a bloomery
    # defect is harness noise. 200 frames leaves a compile — measured at 124
    # frames at its deepest across the fixture corpus — the budget an ordinary
    # caller leaves it, so what fails under this pad fails because of the
    # input.
    frames = fdp.ConsumeIntInRange(0, 200)

    try:
        if door == 0:
            text = _text(fdp, len(data))
            _at_depth(frames, lambda: _authored(text))
        elif door == 1:
            body = _text(fdp, len(data))
            _at_depth(frames, lambda: _registry(body))
        else:
            left = _text(fdp, len(data) // 2)
            right = _text(fdp, len(data))
            _at_depth(frames, lambda: _authored(f"({left}) / ({right})"))
    # The oracle is the narrowness of this handler, not an assertion: whatever
    # it does not name reaches Atheris, which reports it.
    except _harness.EXPECTED as refusal:
        _harness.check_refusal(refusal)


if __name__ == "__main__":
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()
