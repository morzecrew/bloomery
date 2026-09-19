"""One instrumented run: how deep the stack already is at every
``sqlglot.parse_one`` site under a real compile (S-0008 Q-1).

The `SqlText` validator (`src/bloomery/spec/common.py`) proves an expression
parses *at the stack position Pydantic runs it from*, which is shallow. Every
site that re-parses the same string runs deeper, and `RecursionError` is a
function of the remaining stack rather than of the expression — so a value
cleared by the type is not thereby cleared at the sites downstream of it.

This script measures the gap. It wraps `parse_one`, rebinds the wrapper into
every module that imported it, compiles every fixture project in the tree, and
reports per call site the deepest stack observed and the frames left under
`sys.getrecursionlimit()`.

Run from the repository root::

    uv run python fuzz/measure_parse_depth.py

It is a measurement, not a test: nothing asserts, and a fixture that refuses is
counted and skipped like any other.
"""

from __future__ import annotations

import sys
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

import sqlglot

from bloomery import Target, compile_project, load_catalog, load_project
from bloomery.evidence import evaluate

ROOT = Path(__file__).resolve().parent.parent

# The step registries live with the fixtures that wire them, and without one
# `resolve/steps.py` never parses a body — one of the two sites D-7 names.
sys.path.insert(0, str(ROOT / "tests"))
import contextlib

from support.steps import registry_for  # noqa: E402

#: Every module that does `from sqlglot import parse_one` or calls it through
#: the package. A name bound at import time is not reached by patching the
#: package attribute alone, so each binding is replaced by name.
SITES = (
    "bloomery.evidence",
    "bloomery.quality.pattern",
    "bloomery.resolve.steps",
    "bloomery.ir.nodes",
    "bloomery.emit.lower.marts",
    "bloomery.resolve.build",
    "bloomery.guardrails.arithmetic",
    "bloomery.guardrails.grain",
    "bloomery.guardrails.quality",
    "bloomery.spec.common",
)


def _stack_depth() -> int:
    depth = 0
    frame: Any = sys._getframe()
    while frame is not None:
        depth += 1
        frame = frame.f_back
    return depth


def _instrument() -> dict[str, list[int]]:
    """Wrap `parse_one` and rebind it everywhere it is already bound."""
    observed: dict[str, list[int]] = defaultdict(list)
    original = sqlglot.parse_one

    def recording(*args: Any, **kwargs: Any) -> Any:
        caller = traceback.extract_stack(limit=2)[0]
        where = Path(caller.filename)
        with contextlib.suppress(ValueError):
            where = where.relative_to(ROOT)
        observed[f"{where}:{caller.lineno}"].append(_stack_depth())
        return original(*args, **kwargs)

    sqlglot.parse_one = recording  # type: ignore[assignment]
    for name in SITES:
        __import__(name)
        module = sys.modules[name]
        if getattr(module, "parse_one", None) is original:
            module.parse_one = recording  # type: ignore[attr-defined]
    return observed


def _parses(nesting: int) -> bool:
    try:
        sqlglot.parse_one("(" * nesting + "1" + ")" * nesting)
    except RecursionError:
        return False
    except Exception:
        return True
    return True


def _max_nesting(extra_frames: int) -> tuple[int, int]:
    """The deepest expression `parse_one` accepts `extra_frames` deeper down,
    beside the stack depth the call was actually made from."""
    if extra_frames:
        return _max_nesting(extra_frames - 1)
    depth = _stack_depth()
    low, high = 0, 256
    while low < high:
        middle = (low + high + 1) // 2
        if _parses(middle):
            low = middle
        else:
            high = middle - 1
    return depth, low


def _projects() -> list[tuple[str, str, dict[str, str], str | None]]:
    """Every fixture and example directory holding project documents."""
    found: list[tuple[str, str, dict[str, str], str | None]] = []
    roots = [ROOT / "fuzz" / "fixtures", ROOT / "examples" / "quickstart"]
    roots += sorted(p for p in (ROOT / "tests" / "fixtures").iterdir() if p.is_dir())
    for directory in roots:
        documents = {
            path.name: path.read_text()
            for path in sorted(directory.glob("*.yaml"))
            if path.name != "catalog.yaml"
        }
        if not documents:
            continue
        catalog = directory / "catalog.yaml"
        found.append(
            (
                str(directory.relative_to(ROOT)),
                directory.name,
                documents,
                catalog.read_text() if catalog.exists() else None,
            )
        )
    return found


def main() -> None:
    observed = _instrument()
    compiled = refused = 0

    for _name, fixture, documents, catalog_text in _projects():
        catalog = load_catalog(catalog_text) if catalog_text else None
        steps = registry_for(fixture)
        try:
            project = load_project(documents)
            compile_project(
                project,
                target=Target.SQLMESH,
                dialect="duckdb",
                catalog=catalog,
                steps=steps,
            )
        except Exception:
            refused += 1
        else:
            compiled += 1
        # `evaluate` re-walks the same project and parses recipe expressions
        # from a different stack position than the compile does.
        with contextlib.suppress(Exception):
            evaluate(load_project(documents), catalog=catalog, steps=steps)

    sys.getrecursionlimit()
    for _site, _depths in sorted(observed.items(), key=lambda kv: -max(kv[1])):
        pass

    for extra in (0, 4, 8, 16, 32):
        _depth, _levels = _max_nesting(extra)


if __name__ == "__main__":
    main()
