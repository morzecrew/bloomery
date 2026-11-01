"""E2E (S-0026/tier-contracts): a naming policy that names a catalog, built by
the frameworks themselves (#389, S-0025/D-23).

Bronze is in one attached DuckDB database and silver and gold in another, and
neither is the connection's default: SQLMesh plans the project against a
gateway with three catalogs, and dbt builds it with two attached. The
execution tier proves the SQL; this proves SQLMesh reads a three-part model
name and dbt honours `+database`, a source's `database` and the replay macro's
column check against a relation in another catalog.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
from dataclasses import dataclass
from datetime import date

import duckdb
import pytest
from support.compiling import fixture_sources, load_fixture

from bloomery import Target, compile_project, load_project
from bloomery.emit import EmittedArtifact
from bloomery.ir import Layer
from bloomery.naming import DefaultNaming

pytestmark = pytest.mark.e2e

_TIMEOUT = 300

_BY_SHIPPED = "SELECT shipped_month, SUM(amount) FROM gold.mart_orders GROUP BY 1 ORDER BY 1"

_SHIPPED = [(date(2024, 1, 1), 100), (date(2024, 2, 1), 50)]


@dataclass(frozen=True, slots=True)
class AttachedNaming:
    def relation(self, entity: str, layer: Layer) -> tuple[str, str, str]:
        namespace, relation = DefaultNaming().relation(entity, layer)
        return ("pg" if layer is Layer.BRONZE else "lake", namespace, relation)


def _write(root: pathlib.Path, artifacts: tuple[EmittedArtifact, ...]) -> None:
    for artifact in artifacts:
        path = root / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(artifact.content, encoding="utf-8")


def _execute(database: pathlib.Path, *statements: str) -> None:
    connection = duckdb.connect(str(database))
    try:
        for statement in statements:
            connection.execute(statement)
    finally:
        connection.close()


def _rows(database: pathlib.Path, sql: str) -> list[tuple[object, ...]]:
    connection = duckdb.connect(str(database), read_only=True)
    try:
        return [tuple(row) for row in connection.execute(sql).fetchall()]
    finally:
        connection.close()


def _orders(root: pathlib.Path) -> None:
    _execute(
        root / "pg.duckdb",
        "CREATE SCHEMA bronze",
        "CREATE TABLE bronze.oms__orders ("
        "id VARCHAR, amount DECIMAL(12, 4), order_date VARCHAR, ship_date VARCHAR)",
        "INSERT INTO bronze.oms__orders VALUES "
        "('o1', 100, '2024-01-15', '2024-01-20'), ('o2', 50, '2024-01-31', '2024-02-02')",
    )


def _role_playing(target: Target) -> tuple[EmittedArtifact, ...]:
    project, catalog = load_fixture("role_playing_dates")
    return compile_project(
        project, target=target, dialect="duckdb", catalog=catalog, naming=AttachedNaming()
    )


# ....................... #
# SQLMesh


def test_sqlmesh_plans_the_project_across_three_catalogs(tmp_path: pathlib.Path) -> None:
    """The gateway is the operator's, so it lives in the personal config the
    emitted `config.yaml` leaves room for. Its first catalog is the default,
    and neither layer is in it."""
    _write(tmp_path, _role_playing(Target.SQLMESH))
    _orders(tmp_path)
    (tmp_path / ".sqlmesh").mkdir()
    catalogs = "".join(
        f"        {name}: {tmp_path / f'{name}.duckdb'}\n" for name in ("warehouse", "pg", "lake")
    )
    (tmp_path / ".sqlmesh" / "config.yaml").write_text(
        "gateways:\n  local:\n    connection:\n      type: duckdb\n      catalogs:\n"
        f"{catalogs}default_gateway: local\n",
        encoding="utf-8",
    )
    result = _run("sqlmesh", tmp_path, "plan", "--no-prompts", "--auto-apply")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _rows(tmp_path / "lake.duckdb", _BY_SHIPPED) == _SHIPPED


# ....................... #
# dbt

_PROFILES = """\
bloomery:
  target: local
  outputs:
    local:
      type: duckdb
      path: '{root}/warehouse.duckdb'
      schema: main
      attach:
        - path: '{root}/pg.duckdb'
          alias: pg
        - path: '{root}/lake.duckdb'
          alias: lake
"""


def _run(binary: str, root: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One framework command in its own process, as an operator runs it.
    Through `dbtRunner` in this process, a first `dbt build` refused to attach
    `lake` as already attached (dbt-core 1.12.6, dbt-duckdb), where the same
    project builds from the command line."""
    path = pathlib.Path(sys.executable).parent / binary
    if not path.exists():  # pragma: no cover — the dev environment installs both
        pytest.skip(f"{binary} is not installed at {path}")
    return subprocess.run(  # noqa: S603 — a fixed binary path and literal arguments
        [str(path), *args],
        cwd=root,
        env={"PATH": "/usr/bin:/bin", "HOME": str(root)},
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def _dbt(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    (root / "profiles.yml").write_text(_PROFILES.format(root=root), encoding="utf-8")
    result = _run("dbt", root, *args, "--project-dir", str(root), "--profiles-dir", str(root))
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_dbt_builds_the_project_across_attached_catalogs(tmp_path: pathlib.Path) -> None:
    _write(tmp_path, _role_playing(Target.DBT))
    _orders(tmp_path)
    _dbt(tmp_path, "build")

    assert _rows(tmp_path / "lake.duckdb", _BY_SHIPPED) == _SHIPPED


def test_dbt_replays_a_quarantined_row_within_the_lake(tmp_path: pathlib.Path) -> None:
    """The macro reads the columns of a relation in another catalog before it
    writes, and names it there."""
    _execute(
        tmp_path / "pg.duckdb",
        "CREATE SCHEMA bronze",
        """
        CREATE TABLE bronze.shopify__order_lines (
          "order" JSON, position VARCHAR, variant JSON, quantity VARCHAR,
          properties JSON, created_at VARCHAR, financial_status VARCHAR,
          _load_id VARCHAR, _ingested_at VARCHAR, _source_row_id VARCHAR
        )
        """,
        """
        CREATE TABLE bronze.woo__order_lines (
          order_number VARCHAR, item_index VARCHAR, product_sku VARCHAR, qty VARCHAR,
          created VARCHAR, state VARCHAR,
          _load_id VARCHAR, _ingested_at VARCHAR, _source_row_id VARCHAR
        )
        """,
        "INSERT INTO bronze.shopify__order_lines VALUES (json_object('id', 'B-1'), '1', "
        "json_object('sku', 'SKU-1'), '2', json_object('gift_note', NULL), "
        "'2024-03-01T00:00:00', 'paid', 'load-1', '2024-03-10T00:00:00', 's1')",
        "INSERT INTO bronze.woo__order_lines VALUES ('B-3', '1', 'SKU-7', '1', "
        "'2024-03-03T00:00:00', 'reversed', 'load-1', '2024-03-10T00:00:00', 'w3')",
    )
    sources = fixture_sources("multi_source_quality")

    def compiled() -> tuple[EmittedArtifact, ...]:
        return compile_project(
            load_project(sources), target=Target.DBT, dialect="duckdb", naming=AttachedNaming()
        )

    _write(tmp_path, compiled())
    _dbt(tmp_path, "run")
    lake = tmp_path / "lake.duckdb"
    assert _rows(lake, "SELECT _source_row_id FROM silver.order_line__reject") == [("w3",)]

    anchor = "{enum_map: [PROCESSING, open, COMPLETE, closed]}"
    assert sources["mapping_legacy"].count(anchor) == 1
    sources["mapping_legacy"] = sources["mapping_legacy"].replace(
        anchor, "{enum_map: [PROCESSING, open, COMPLETE, closed, reversed, closed]}"
    )
    # Bronze's window has moved past `w3`, so only replay can admit it.
    _execute(tmp_path / "pg.duckdb", "DELETE FROM bronze.woo__order_lines")
    _write(tmp_path, compiled())
    _dbt(tmp_path, "run")
    assert _rows(lake, "SELECT order_id FROM silver.order_line") == [("B-1",)]
    _dbt(tmp_path, "run-operation", "replay_order_line")

    assert _rows(lake, "SELECT order_id FROM silver.order_line ORDER BY 1") == [("B-1",), ("B-3",)]
