"""Suite-wide pytest configuration.

Its one job is the chaos meta-test's entry point (RFC 0016 §6): when
``BLOOMERY_CHAOS_MUTATION`` names a mutation, the lowering is deformed *before
collection* — test modules compile fixtures at import time, so a hook that ran
any later would test the unmutated compiler.

Nothing else belongs here. The environment variable is read in the **test**
process only; ``src/bloomery/`` reads no environment at all (RFC 0003), and the
determinism guard enforces that.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

#: Set by ``tests/chaos/test_mutation_harness.py`` in a subprocess.
CHAOS_ENV = "BLOOMERY_CHAOS_MUTATION"


def pytest_configure(config: pytest.Config) -> None:
    del config
    mutation = os.environ.get(CHAOS_ENV)
    if not mutation:
        return
    from support.chaos import apply_mutation

    apply_mutation(mutation)
