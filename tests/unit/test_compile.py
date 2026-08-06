"""The compile orchestration (spec §8): target/dialect routing and the
public-signature contract."""

from __future__ import annotations

import pytest

from bloomery import Target, compile_project
from bloomery.errors import EmitError
from support.compiling import load_fixture

pytestmark = pytest.mark.unit


def test_target_enum_carries_sqlmesh() -> None:
    assert list(Target) == [Target.SQLMESH]
    assert Target.SQLMESH == "sqlmesh"


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
    with pytest.raises(EmitError, match="unknown target 'cube'"):
        compile_project(project, target="cube", dialect="duckdb")
