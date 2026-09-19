"""What every fuzz target shares: the expectation tuple, the valid document
set the targets mutate one document of, and the calls the oracle is about.

Read :data:`EXPECTED` before anything else. It is the error reference
(`pages/docs/reference/errors.md`) restated as code: `except BloomeryError` is
claimed to be sufficient for a caller of this library, so any other exception
crossing `load_project`, `compile_project` or the planner is a finding.

**The tuple never grows to make a run green** (S-0008/D-1). A tuple that grows
is a finding about the error taxonomy, not about the fuzzer, and widening it
carries the same review bar as editing the error reference (S-0008/D-3): each
addition arrives with either a fix translating the exception into a
`BloomeryError`, or a recorded decision in the reference that the escape is
intended. What stays out and why is written beside the tuple.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from bloomery import Target, compile_project, load_catalog, load_project
from bloomery.errors import BloomeryError
from bloomery.evidence import evaluate
from bloomery.steps import EMPTY_REGISTRY

if TYPE_CHECKING:
    from bloomery.steps import StepRegistry

#: The boundary claim, as a tuple. Deliberately absent, each for its own
#: reason: `yaml.YAMLError`, because the loader owns YAML and a raw parser
#: error reaching a caller is a leaked abstraction; `SqlglotError` and
#: `TokenError`, which are PR #111; `RecursionError`, because catching it hides
#: unbounded recursion — if depth should be bounded the fix is a limit raising
#: a named error, which is what `FilterTooComplex` already is; `KeyError`,
#: `AttributeError` and `TypeError`, the signature of a spec field read without
#: validation; `UnicodeDecodeError`, `MemoryError`, `OverflowError`; and
#: `AssertionError`, because a harness never catches its own oracle.
EXPECTED: tuple[type[BaseException], ...] = (BloomeryError,)

FIXTURES = Path(__file__).parent / "fixtures"

#: The catalog is not a project document — it is loaded separately and passed
#: in — so it is named apart from the five `load_project` reads.
CATALOG = "catalog.yaml"


def documents() -> dict[str, str]:
    """The five valid project documents, freshly read each call so a target
    that mutates one cannot leak the mutation into the next execution."""
    return {
        path.name: path.read_text()
        for path in sorted(FIXTURES.glob("*.yaml"))
        if path.name != CATALOG
    }


def catalog_text() -> str:
    return (FIXTURES / CATALOG).read_text()


def check_refusal(exc: BloomeryError) -> None:
    """A refusal a caller cannot read is a finding of its own.

    The batched aggregates are where message formatting breaks — the first
    refusal renders fine and the twelfth in a batch is the one that does not —
    so rendering is asserted rather than assumed.
    """
    rendered = str(exc)
    assert rendered, f"{type(exc).__name__} rendered as the empty string"


def compile_or_refuse(
    sources: dict[str, str],
    catalog: str | None = None,
    steps: StepRegistry = EMPTY_REGISTRY,
) -> None:
    """Load, compile and evaluate one project.

    The oracle is implemented by *not catching* the wrong things: atheris
    reports an uncaught exception by itself, so everything outside
    :data:`EXPECTED` escapes on purpose.
    """
    try:
        parsed_catalog = load_catalog(catalog) if catalog is not None else None
        project = load_project(sources)
    except EXPECTED as exc:
        check_refusal(exc)
        return

    # `evaluate` carries the stronger promise — a spec-level problem comes back
    # as a value rather than as an exception — so it is called unguarded, on
    # every project that loaded, refused or not. Anything at all from here is a
    # finding, including a `BloomeryError`.
    evaluate(project, catalog=parsed_catalog, steps=steps)

    try:
        compile_project(
            project,
            target=Target.SQLMESH,
            dialect="duckdb",
            catalog=parsed_catalog,
            steps=steps,
        )
    except EXPECTED as exc:
        check_refusal(exc)
