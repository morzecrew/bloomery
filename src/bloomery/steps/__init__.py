"""The step package (RFC 0017): referenced implementations.

The escape hatch for logic that cannot be declared — entity resolution, fuzzy
matching, ML scoring. RFC 0016's principle still governs and is what this
package is shaped by: **specs describe, specs reference implementations,
specs never contain implementations.**

Three things live here, and the split matters:

- :mod:`~bloomery.steps.manifest` — what a platform step *declares*: the
  frozen :class:`StepManifest` and the types it nests. Parsed by the caller,
  never read from disk by bloomery.
- :mod:`~bloomery.steps.registry` — :class:`StepRegistry`, the frozen compile
  **input**. There is no dynamic loading path anywhere in this package, which
  is precisely why an authored spec can never become an
  arbitrary-code-execution surface (§5.3, D3).
- :mod:`~bloomery.steps.contract` — the run-time assertion the generated
  wrapper carries. It is the **only** bloomery module intended for import
  outside compilation, and the only one that touches pandas — lazily, inside
  the wrapper's runtime path, so pandas never joins bloomery's own
  dependencies (D12).

Bloomery never imports or executes step code while compiling: it consumes
manifests and SQL text, nothing else (D13). The generated wrapper importing a
manifest's ``entrypoint`` at run time is the ordinary SQLMesh execution path,
not an exception to that rule.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — import-time typing only
    from bloomery.steps.contract import assert_step_contract
    from bloomery.steps.manifest import (
        DeterminismName,
        LineageName,
        StepInput,
        StepKindName,
        StepManifest,
        StepOutput,
        StepParameter,
        StepProduces,
    )
    from bloomery.steps.registry import EMPTY_REGISTRY, StepRegistry

# ----------------------- #

#: Which submodule each public name lives in — the table :func:`__getattr__`
#: resolves against.
_LAZY: dict[str, str] = {
    "DeterminismName": "manifest",
    "LineageName": "manifest",
    "StepInput": "manifest",
    "StepKindName": "manifest",
    "StepManifest": "manifest",
    "StepOutput": "manifest",
    "StepParameter": "manifest",
    "StepProduces": "manifest",
    "EMPTY_REGISTRY": "registry",
    "StepRegistry": "registry",
    "assert_step_contract": "contract",
}


def __dir__() -> list[str]:
    """Include the lazily-resolved names, which :func:`__getattr__` alone
    hides from ``dir()`` and every tool built on it."""

    return sorted({*globals(), *_LAZY})


# ....................... #


def __getattr__(name: str) -> Any:
    """Resolve a public name on first use (PEP 562).

    Lazy so that importing :mod:`bloomery.steps.contract` — which *generated
    code* does, in the step runtime — does not also pull in pydantic and the
    spec layer to run an assertion that needs neither.

    **On its own this saves nothing measurable, and the honest figure is the
    one to quote:** ``import bloomery.steps.contract`` still costs ~400 ms and
    ~1000 modules, because importing a submodule executes *every* parent
    package's ``__init__`` and bloomery's top-level one eagerly imports the
    compile surface. Making that one lazy too fixed it completely (6.5 ms, 55
    modules) and was reverted — ``plan`` and ``resolve`` are both public
    functions and submodule names, so the module attribute shadows the
    function and ``from bloomery import plan`` becomes import-order-dependent.

    So this is the collision-free half of a repair whose other half is unsafe;
    RFC 0017 D22 records the measurement and names §8's escape hatch
    (extracting ``contract`` into a micro-package) as the remaining route.
    """
    module = _LAZY.get(name)

    if module is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)

    import importlib

    return getattr(importlib.import_module(f"bloomery.steps.{module}"), name)


# ....................... #


__all__ = [
    "EMPTY_REGISTRY",
    "DeterminismName",
    "LineageName",
    "StepInput",
    "StepKindName",
    "StepManifest",
    "StepOutput",
    "StepParameter",
    "StepProduces",
    "StepRegistry",
    "assert_step_contract",
]
