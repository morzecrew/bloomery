"""The compile orchestration (spec §8): target/dialect routing, the
public-signature contract, and the extension-dialect pattern-transport check
(RFC 0016 D56's explicit-argument hatch)."""

from __future__ import annotations

import importlib

import pytest

from bloomery import Target, build_project_ir, compile_project
from bloomery.compile import _check_pattern_transport  # pyright: ignore[reportPrivateUsage]
from bloomery.dialects import DialectFeature, SQLGlotDialect, get_dialect, register_dialect
from bloomery.errors import EmitError, UnsupportedByTarget
from support.compiling import load_fixture

pytestmark = pytest.mark.unit


def test_target_enum_carries_the_shipped_targets() -> None:
    assert list(Target) == [Target.SQLMESH, Target.CUBE, Target.DBT]
    assert Target.SQLMESH == "sqlmesh"
    assert Target.CUBE == "cube"
    assert Target.DBT == "dbt"


def test_string_target_is_accepted() -> None:
    project, _ = load_fixture("minimal")
    by_enum = compile_project(project, target=Target.SQLMESH, dialect="duckdb")
    by_string = compile_project(project, target="sqlmesh", dialect="duckdb")
    assert by_enum == by_string


def test_unknown_dialect_is_an_emit_error() -> None:
    project, _ = load_fixture("minimal")
    with pytest.raises(EmitError, match="unknown dialect 'sqlite'"):
        compile_project(project, target=Target.SQLMESH, dialect="sqlite")


def test_unknown_target_is_an_emit_error() -> None:
    project, _ = load_fixture("minimal")
    with pytest.raises(EmitError, match="unknown target 'looker'"):
        compile_project(project, target="looker", dialect="duckdb")


# ....................... #
# Extension-dialect pattern transport (RFC 0016 D56's hatch, applied at the
# one seam where the dialect is a declared input rather than ambient state)


class _NoRegex(SQLGlotDialect):
    name = "noregex"
    sqlglot_dialect = "duckdb"

    def supports(self, feature: DialectFeature) -> bool:
        return feature is not DialectFeature.REGEXP_EXTRACT


class _FullPort(SQLGlotDialect):
    name = "fullport"
    sqlglot_dialect = "duckdb"


def test_pattern_rules_refuse_an_extension_dialect_with_no_regex_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guardrail stage vets patterns against the shipped ports only (D56);
    before this check an extension dialect had its patterns rendered with no
    transport check at all."""
    dialects_module = importlib.import_module("bloomery.dialects")
    monkeypatch.setattr(dialects_module, "_overlay", {})
    register_dialect(_NoRegex())
    project, catalog = load_fixture("dirty_corpus")
    with pytest.raises(UnsupportedByTarget) as excinfo:
        compile_project(project, target=Target.SQLMESH, dialect="noregex", catalog=catalog)
    message = str(excinfo.value)
    assert "'noregex'" in message
    assert "pattern" in message
    assert "Fix:" in message


def test_pattern_rules_pass_an_extension_dialect_that_carries_them() -> None:
    """The control: the check refuses the incapable port, not every extension
    port — a full-featured one transports the corpus's patterns clean."""
    project, catalog = load_fixture("dirty_corpus")
    ir = build_project_ir(project, catalog)
    _check_pattern_transport(ir, _FullPort())


def test_shipped_dialects_skip_the_transport_recheck() -> None:
    """The shipped three were vetted at the guardrail stage; re-checking them
    here would make the compile verdict depend on two call sites agreeing."""
    project, catalog = load_fixture("dirty_corpus")
    ir = build_project_ir(project, catalog)
    for name in ("duckdb", "postgres", "trino"):
        _check_pattern_transport(ir, get_dialect(name))
