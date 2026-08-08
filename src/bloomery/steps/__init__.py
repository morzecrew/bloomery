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
]
