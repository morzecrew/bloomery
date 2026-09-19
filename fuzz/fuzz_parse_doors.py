"""The parse-door target: authored SQL text at the doors `SqlText` does not
guard (S-0008, phase 1).

`src/bloomery/spec/common.py` parses the four authored `expr:` fields once, at
load, and that is a proof about one stack position and one string. It is not a
proof about the dozen `parse_one` calls downstream of it, for two reasons this
target exercises:

*Direct* — text that reaches a site without passing `_parses_as_sql` at all. A
step body comes from the registry, which is assembled in Python; a catalog
recipe the IR builder never selects is still walked by the sites that read
every recipe.

*Composed* — two individually valid fragments templated into one larger
expression which is then re-parsed. Validity is not closed under composition,
and no per-field validator can see that.

Run it through the lane rather than directly::

    just fuzz parse_doors 60

Its own known-catchable defects, for the sabotage check the lane owes every
target (S-0008/tests). Narrow either handler back to `except SqlglotError` and
replay the seed that drives its door::

    just fuzz-repro parse_doors fuzz/fuzz_parse_doors_seed_corpus/band-recipe-expr
    just fuzz-repro parse_doors fuzz/fuzz_parse_doors_seed_corpus/band-step-body

The first reaches `src/bloomery/evidence.py`, the second
`src/bloomery/resolve/steps.py`; in both cases the `RecursionError` crosses the
compile boundary and the target reports it. Both seeds nest 51 deep, which is
measured, not arbitrary: sqlglot spends roughly 20 frames per nesting level, so
the window between what the load-time validator accepts and what a site a few
frames deeper can parse is about one level wide. A seed one level either side
of it proves nothing.

**One open finding, deferred rather than fixed.** A 45-second run on the
step-body door reaches `src/bloomery/ir/nodes.py:428` (`_parse_sql`, through
`SqlExpr.ast` at emit) with a body that `resolve/steps.py` parsed happily one
stage earlier — the same asymmetry again, one stack position deeper. That file
is outside this phase's allow list and the fix belongs to a follow-up task, so
the lane currently stops on it. Until then a run is read as: *this* crash is
the known one, anything else is new. The crash file is reproducible from any
seed corpus run; it is not checked in, because a corpus entry is not a
regression test (S-0008/D-4).
"""

from __future__ import annotations

import json
import sys

import atheris

with atheris.instrument_imports():
    import _harness

    from bloomery.steps import StepManifest, StepRegistry

#: The literals the fixture set is anchored on. A target that silently stopped
#: substituting would fuzz nothing and stay green forever, which is the
#: dominant failure mode of a fuzzing setup — so a drifted fixture is an
#: immediate, loud failure rather than a quiet one.
RECIPE_EXPR = '{id: unselected, requires: [amount], expr: "amount / 1"}'
TEMPLATE_EXPR = 'expr: "amount"'
METRIC_EXPR = 'expr: "order_id"'

#: How two fragments are put together. The first is the direct shape; the rest
#: are the composed one, where each fragment may be valid and the whole not.
SHAPES = (
    "{a}",
    "{a} / {b}",
    "CASE WHEN {a} THEN {b} ELSE NULL END",
    "SUM({a}) OVER (PARTITION BY {b})",
    "CAST({a} AS {b})",
)

#: A Tier 2 step whose body is the fuzzed text. The wiring names no inputs, so
#: the body is the only thing under test at this door.
STEP_MANIFEST: dict[str, object] = {
    "ref": "scored",
    "version": 1,
    "kind": "sql_model",
    "determinism": "pure",
    "runtime_lock": "sha256:x",
    "outputs": {"out": {"grain": "g", "key": ["k"], "produces": {"k": {"type": "string"}}}},
}

STEP_WIRING = "steps_version: 1\nsteps:\n  - use: scored@1\n    outputs: {out: silver.scored}\n"


def _fragment(fdp: atheris.FuzzedDataProvider, size: int) -> str:
    return fdp.ConsumeUnicodeNoSurrogates(size)


def _expression(fdp: atheris.FuzzedDataProvider) -> str:
    shape = SHAPES[fdp.ConsumeIntInRange(0, len(SHAPES) - 1)]
    half = max(1, fdp.remaining_bytes() // 2)
    return shape.format(a=_fragment(fdp, half), b=_fragment(fdp, half))


def _scalar(text: str) -> str:
    """The expression as a YAML double-quoted scalar.

    JSON's string grammar is a subset of YAML's flow scalar grammar, so this
    keeps the *document* valid however hostile the expression is — which is the
    point: the target is about the SQL door, and a mutation that only breaks
    YAML never reaches one.
    """
    return json.dumps(text)


def one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    door = fdp.ConsumeIntInRange(0, 3)
    expression = _expression(fdp)

    sources = _harness.documents()
    catalog = _harness.catalog_text()
    steps = _harness.EMPTY_REGISTRY

    if door == 0:
        replacement = RECIPE_EXPR.replace('"amount / 1"', _scalar(expression))
        catalog = catalog.replace(RECIPE_EXPR, replacement)
    elif door == 1:
        catalog = catalog.replace(TEMPLATE_EXPR, f"expr: {_scalar(expression)}")
    elif door == 2:
        sources["metrics.yaml"] = sources["metrics.yaml"].replace(
            METRIC_EXPR, f"expr: {_scalar(expression)}"
        )
    else:
        sources["steps.yaml"] = STEP_WIRING
        steps = StepRegistry(
            {("scored", 1): StepManifest.model_validate(STEP_MANIFEST)},
            sql_bodies={("scored", 1): expression},
        )

    _harness.compile_or_refuse(sources, catalog, steps)


def _check_anchors() -> None:
    catalog = _harness.catalog_text()
    sources = _harness.documents()
    for anchor, text, where in (
        (RECIPE_EXPR, catalog, "catalog.yaml"),
        (TEMPLATE_EXPR, catalog, "catalog.yaml"),
        (METRIC_EXPR, sources["metrics.yaml"], "metrics.yaml"),
    ):
        if anchor not in text:
            msg = f"fuzz/fixtures/{where} no longer contains {anchor!r}: this target fuzzes nothing"
            raise SystemExit(msg)


if __name__ == "__main__":
    _check_anchors()
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()
