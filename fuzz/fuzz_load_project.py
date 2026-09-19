"""The spec-layer target: one document fuzzed against five held valid
(S-0008, phase 2).

A document fuzzed on its own reaches the YAML parser and its own model, and
almost nothing else: a project of one document has nothing to resolve against,
so the cross-document layer — a mapping's `canonical:` reaching a catalog field,
a metric's `template:` reaching a catalog recipe, a mart's `base:` reaching an
entity, an exposure's `depends_on:` reaching both — is never entered, and no
mutation can produce a guardrail violation because there are no real entities
to violate anything against.

So the fixture set holds one document of every kind, and each execution
replaces exactly one of the six with the fuzzed bytes. The other five stay
valid and stay *real*: whatever the mutation says, it is said to a project that
otherwise loads, compiles and evaluates to completion.

The slot comes from the fuzzer's own bytes rather than from a target per kind.
One corpus, one coverage map: an input that taught the fuzzer something about
the YAML door in `marts.yaml` is a mutation away from teaching it the same
about `metrics.yaml`, and six targets would each have to learn it alone.

Run it through the lane rather than directly::

    just fuzz load_project 60

Its own known-catchable defect, for the sabotage check the lane owes every
target (S-0008/D-9). Delete the depth cap from
`src/bloomery/spec/common.py` — the `if self._depth > _MAX_DEPTH` arm of
`compose_node` — and replay::

    just fuzz-repro load_project fuzz/fuzz_load_project_seed_corpus/deep-nesting

Without the cap PyYAML's composer recurses once per nesting level and the seed's
1200 levels exhaust the stack: a `RecursionError`, which is deliberately outside
`_harness.EXPECTED` (S-0008/D-1), crosses `load_project` and the target reports
it. The checked-in regression for the same defect is
`test_a_too_deep_document_is_refused_not_a_recursion_error` in
`tests/unit/test_spec/test_common.py` (S-0008/D-4).
"""

from __future__ import annotations

import sys

import atheris

with atheris.instrument_imports():
    import _harness

    from bloomery import Stage, load_catalog, load_project
    from bloomery.evidence import evaluate

#: Every document the fixture set holds, catalog included. The catalog is not
#: loaded by `load_project` — it is parsed separately and passed in — but it is
#: half of what the cross-document layer resolves *against*, so a target that
#: could not fuzz it would leave the canonical-field and recipe doors shut.
SLOTS: tuple[str, ...] = (
    _harness.CATALOG,
    "entity_model.yaml",
    "exposures.yaml",
    "mapping_orders.yaml",
    "marts.yaml",
    "metrics.yaml",
)


def one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    slot = SLOTS[fdp.ConsumeIntInRange(0, len(SLOTS) - 1)]
    # The raw bytes as text, not `ConsumeUnicode*`: the seed corpus is the six
    # real documents, and a provider that re-encodes what it reads would hand
    # the first mutation a mangled document instead of a valid one with one
    # byte changed.
    document = fdp.ConsumeBytes(fdp.remaining_bytes()).decode("utf-8", "replace")

    sources = _harness.documents()
    catalog = _harness.catalog_text()
    if slot == _harness.CATALOG:
        catalog = document
    else:
        sources[slot] = document

    _harness.compile_or_refuse(sources, catalog)


def _check_fixtures() -> None:
    """The five held valid are valid, and the six slots are the six files.

    Both failures are silent ones. A fixture set that drifted into being
    refused makes every execution stop at the same refusal, so the target fuzzes
    the loader and nothing behind it and stays green forever. A slot naming a
    file the directory no longer has makes the mutation an *added* seventh
    document rather than a replaced one, which is a weaker input that looks
    identical from the outside.
    """
    sources = _harness.documents()
    if set(SLOTS) != {*sources, _harness.CATALOG}:
        msg = f"fuzz/fixtures holds {sorted({*sources, _harness.CATALOG})}, SLOTS names {sorted(SLOTS)}"
        raise SystemExit(msg)

    evidence = evaluate(load_project(sources), catalog=load_catalog(_harness.catalog_text()))
    if evidence.stage_reached is not Stage.COMPLETE:
        msg = (
            f"fuzz/fixtures stops at {evidence.stage_reached}: the five held valid"
            " are not valid, and this target fuzzes nothing past the loader"
        )
        raise SystemExit(msg)


if __name__ == "__main__":
    _check_fixtures()
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()
