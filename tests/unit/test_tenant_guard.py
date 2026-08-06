"""Named guard (RFC 0009 §5.6, `_bloomery-changes.md` D9): the package must
remain something you could open-source with no multi-tenancy showing through.
The word "tenant" may appear only in ``naming.py`` docstrings."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import bloomery

pytestmark = pytest.mark.unit

PACKAGE_DIR = Path(bloomery.__file__).resolve().parent
WORD = "tenant"


def _without_docstrings(source: str) -> str:
    """Blank out every module/class/function docstring in ``source``."""
    lines = source.splitlines()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            doc = body[0]
            end = doc.end_lineno if doc.end_lineno is not None else doc.lineno
            for lineno in range(doc.lineno - 1, end):
                lines[lineno] = ""
    return "\n".join(lines)


def test_no_tenant_leaks_into_src() -> None:
    offenders: list[str] = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        source = path.read_text()
        if WORD not in source.lower():
            continue
        if path.name == "naming.py":
            # tenant-scoped naming policies may *explain* themselves — the
            # word is allowed in naming.py docstrings only.
            if WORD in _without_docstrings(source).lower():
                offenders.append(str(path))
        else:
            offenders.append(str(path))
    assert not offenders, f"'{WORD}' found outside naming.py docstrings: {offenders}"
