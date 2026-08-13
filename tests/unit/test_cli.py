"""The command line (RFC 0020 §5.2, D4–D6, D9).

Three properties carry the section.

**Every command works on a real fixture.** Six commands over the corpus, exit
code and output checked — the CLI is a shell, so the way it breaks is a wiring
mistake (a flag never read, a loader called with the wrong argument), and only
running it finds those.

**``--format json`` is not a second, lossier surface.** Each JSON command is
compared against the Python call it wraps, converted the same way. A CLI that
quietly drops a field is worse than one that has no JSON at all, because a
script built on it looks like it works.

**Exit codes distinguish a refusal from a usage error.** ``1`` means bloomery
read the spec and said no — a correct outcome a pipeline must not retry. ``2``
means the invocation was wrong. Collapsing them is the difference between a
build that stops and a build that loops.

``main`` is called as a function throughout, so the code is *read* rather than
asserted through a subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from bloomery import (
    LruManifestHydrator,
    MetricFlowPlanner,
    MetricRequest,
    Op,
    RowPolicy,
    SpecKind,
    Target,
    all_spec_schemas,
    build_project_ir,
    compile_project,
    plan,
    project_fingerprint,
    resolve,
)
from bloomery.cli import EXIT_OK, EXIT_REFUSED, EXIT_USAGE, build_parser, main
from bloomery.cli.io import CliIoError, read_spec_directory, write_files
from bloomery.cli.serialize import as_json_value
from bloomery.naming import DefaultNaming
from support.compiling import load_fixture

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ECOM = str(FIXTURES / "ecom_basic")


def run(
    capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, str, str]:
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _json(capsys: pytest.CaptureFixture[str], *argv: str) -> object:
    code, out, err = run(capsys, *argv)
    assert code == EXIT_OK, err
    return json.loads(out)


# ....................... #
# Every command, on a real fixture


@pytest.mark.parametrize(
    "argv",
    [
        ("resolve", ECOM),
        ("resolve", ECOM, "--format", "json"),
        ("fingerprint", ECOM),
        ("schema",),
        ("schema", "--kind", "metrics"),
        ("plan", str(FIXTURES / "evolution_v1"), str(FIXTURES / "evolution_v2")),
        ("explain", ECOM, "--metrics", "gross_revenue", "--by", "ordered_month"),
    ],
    ids=lambda argv: "-".join(part for part in argv if not part.startswith("/")),
)
def test_a_command_succeeds_and_writes_something(
    capsys: pytest.CaptureFixture[str], argv: Sequence[str]
) -> None:
    code, out, err = run(capsys, *argv)
    assert code == EXIT_OK, err
    assert out.strip()


def test_compile_writes_the_artifacts_the_api_returns(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    project, catalog = load_fixture("ecom_basic")
    expected = compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog)

    code, out, err = run(capsys, "compile", ECOM, "--out", str(tmp_path))
    assert code == EXIT_OK, err
    assert len(out.splitlines()) == len(expected)
    for artifact in expected:
        assert (tmp_path / artifact.path).read_text() == artifact.content


def test_compile_without_out_emits_the_artifacts_as_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    project, catalog = load_fixture("ecom_basic")
    expected = compile_project(project, target=Target.SQLMESH, dialect="duckdb", catalog=catalog)
    payload = _json(capsys, "compile", ECOM)
    assert payload == [as_json_value(artifact) for artifact in expected]
    # Content included: `--out` writes files, so `--format json` has to hand
    # over the same bytes or it is a manifest of files nobody received.
    assert all(entry["content"] for entry in payload)  # type: ignore[index, union-attr]


def test_schema_out_writes_one_file_per_kind(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, _out, err = run(capsys, "schema", "--out", str(tmp_path))
    assert code == EXIT_OK, err
    written = {path.stem: json.loads(path.read_text()) for path in tmp_path.glob("*.json")}
    assert written == {kind.value: schema for kind, schema in all_spec_schemas().items()}


# ....................... #
# D4 — the JSON is the same value the Python API returns


def test_resolve_json_matches_the_python_call(capsys: pytest.CaptureFixture[str]) -> None:
    project, catalog = load_fixture("ecom_basic")
    assert _json(capsys, "resolve", ECOM, "--format", "json") == as_json_value(
        resolve(project, catalog)
    )


def test_plan_json_matches_the_python_call(capsys: pytest.CaptureFixture[str]) -> None:
    old_project, old_catalog = load_fixture("evolution_v1")
    new_project, new_catalog = load_fixture("evolution_v2")
    expected = plan(
        build_project_ir(old_project, catalog=old_catalog),
        build_project_ir(new_project, catalog=new_catalog),
    )
    payload = _json(
        capsys,
        "plan",
        str(FIXTURES / "evolution_v1"),
        str(FIXTURES / "evolution_v2"),
        "--format",
        "json",
    )
    assert payload == as_json_value(expected)


def test_explain_json_matches_the_python_call(capsys: pytest.CaptureFixture[str]) -> None:
    project, catalog = load_fixture("ecom_basic")
    naming = DefaultNaming()
    planner = MetricFlowPlanner(LruManifestHydrator(naming), naming=naming)
    expected = planner.plan(
        build_project_ir(project, catalog=catalog),
        MetricRequest(metrics=("gross_revenue",), dimensions=("ordered_month",), limit=5),
        dialect="duckdb",
    )
    payload = _json(
        capsys,
        "explain",
        ECOM,
        "--metrics",
        "gross_revenue",
        "--by",
        "ordered_month",
        "--limit",
        "5",
        "--format",
        "json",
    )
    assert payload == as_json_value(expected)


def test_resolve_json_carries_fields_the_table_does_not_print(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The concrete meaning of "not a lossier surface": ``provenance`` and
    ``topo_order`` are on the returned value and off the table, and a script
    should not have to drop to Python for them."""
    payload = _json(capsys, "resolve", ECOM, "--format", "json")
    assert isinstance(payload, dict)
    assert payload["provenance"]
    assert payload["topo_order"]


def test_a_logical_type_serializes_as_the_string_a_spec_writes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``StringType()`` has no fields, so a structural dump renders it ``{}``
    and loses the type. The canonical spelling is what goes out — and it is
    what ``parse_type`` reads back."""
    payload = _json(
        capsys, "explain", ECOM, "--metrics", "gross_revenue", "--format", "json"
    )
    assert isinstance(payload, dict)
    types = {column["type"] for column in payload["columns"]}  # type: ignore[index, union-attr]
    assert types
    assert all(isinstance(rendered, str) and rendered for rendered in types)
    assert "{}" not in types


# ....................... #
# Exit codes (D4): refusal is 1, usage is 2, and they are not the same


def test_a_spec_refusal_exits_one_with_its_source_path(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (tmp_path / "entity_model.yaml").write_text(
        "spec_version: 1\nentities:\n  e:\n    grain: g\n    key: [k]\n"
        "    fields:\n      k: {type: nonsense}\n"
    )
    code, _out, err = run(capsys, "resolve", str(tmp_path))
    assert code == EXIT_REFUSED
    # A single error carries its path as an attribute, not in the message
    # (RFC 0002 D6 renders paths only in the batched aggregate), so the CLI
    # prepends it — without that the reader gets a sentence with no file.
    assert err.startswith("entity_model: entities.e.fields.k.type:")


def test_a_planner_refusal_exits_one(capsys: pytest.CaptureFixture[str]) -> None:
    code, _out, err = run(
        capsys,
        "explain",
        str(FIXTURES / "multi_mart_refusal"),
        "--metrics",
        "shipping_cost,line_discount",
    )
    assert code == EXIT_REFUSED
    assert "different grains" in err


def test_a_missing_directory_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    code, _out, err = run(capsys, "resolve", "/no/such/directory")
    assert code == EXIT_USAGE
    assert "not a directory" in err


def test_a_directory_with_no_specs_exits_two(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, _out, err = run(capsys, "resolve", str(tmp_path))
    assert code == EXIT_USAGE
    assert "no .yaml/.yml files" in err


@pytest.mark.parametrize(
    ("flag", "value", "expected"),
    [
        ("--where", "{not json", "not valid JSON"),
        ("--where", "[1, 2]", "takes a JSON object"),
        ("--grain", "fortnight", "--grain 'fortnight' is not one of"),
    ],
)
def test_a_malformed_flag_value_is_a_usage_error_not_a_traceback(
    capsys: pytest.CaptureFixture[str], flag: str, value: str, expected: str
) -> None:
    """``json.loads`` and ``TimeGrain()`` raise ``ValueError``, which nothing in
    ``main`` catches — so a mistyped quote would exit on a traceback and a
    script branching on the code would see neither ``1`` nor ``2``."""
    code, _out, err = run(capsys, "explain", ECOM, "--metrics", "gross_revenue", flag, value)
    assert code == EXIT_USAGE
    assert expected in err


def test_a_bad_flag_is_reported_before_a_bad_spec(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Both are wrong; the invocation is the one the reader has to fix first —
    a refusal about a spec they cannot reach yet is not the next step. It is
    also the cheap check, and loading is the slow one."""
    (tmp_path / "entity_model.yaml").write_text("spec_version: 1\nentities: {}\nbogus: 1\n")
    code, _out, err = run(
        capsys, "explain", str(tmp_path), "--metrics", "m", "--grain", "fortnight"
    )
    assert code == EXIT_USAGE
    assert "--grain" in err


def test_a_refused_filter_construct_stays_a_refusal(capsys: pytest.CaptureFixture[str]) -> None:
    """The other side of the line above. A *well-formed* document naming a
    construct the vocabulary reviewed and declined (RFC 0015) is a refusal, not
    a typo — so it exits `1` and carries the reason."""
    code, _out, err = run(
        capsys,
        "explain",
        ECOM,
        "--metrics",
        "gross_revenue",
        "--where",
        '{"ordered_month": {"$regex": "x"}}',
    )
    assert code == EXIT_REFUSED
    assert "use like/ilike" in err


def test_the_two_failure_codes_are_distinct() -> None:
    """Stated as a property, because the whole point of the split is that a
    script can branch on it."""
    assert EXIT_OK != EXIT_REFUSED != EXIT_USAGE
    assert EXIT_REFUSED != EXIT_USAGE


# ....................... #
# --policy (RFC 0020 §10 question 2)


def test_policy_reaches_the_plan(capsys: pytest.CaptureFixture[str]) -> None:
    project, catalog = load_fixture("ecom_basic")
    naming = DefaultNaming()
    planner = MetricFlowPlanner(LruManifestHydrator(naming), naming=naming)
    expected = planner.plan(
        build_project_ir(project, catalog=catalog),
        MetricRequest(metrics=("gross_revenue",)),
        dialect="duckdb",
        policy=RowPolicy(dimension="order_customer_id", op=Op.EQ, value="c1"),
    )
    payload = _json(
        capsys,
        "explain",
        ECOM,
        "--metrics",
        "gross_revenue",
        "--policy",
        "order_customer_id eq c1",
        "--format",
        "json",
    )
    assert payload == as_json_value(expected)
    assert isinstance(payload, dict)
    assert payload["explanation"]["policy_applied"] is True  # type: ignore[index, call-overload]


@pytest.mark.parametrize("spelling", ["bad", "a eq", "a nonsense_op b"])
def test_a_malformed_policy_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], spelling: str
) -> None:
    code, _out, err = run(
        capsys, "explain", ECOM, "--metrics", "gross_revenue", "--policy", spelling
    )
    assert code == EXIT_USAGE
    assert "--policy" in err


def test_a_multi_value_policy_splits_on_commas(capsys: pytest.CaptureFixture[str]) -> None:
    payload = _json(
        capsys,
        "explain",
        ECOM,
        "--metrics",
        "gross_revenue",
        "--policy",
        "order_customer_id in c1,c2",
        "--format",
        "json",
    )
    assert isinstance(payload, dict)
    assert "c1" in str(payload["sql"]) and "c2" in str(payload["sql"])


# ....................... #
# The catalog convention (§5.2's `--catalog`)


def test_a_catalog_yaml_in_the_directory_is_loaded_and_excluded() -> None:
    sources, catalog = read_spec_directory(str(FIXTURES / "ecom_basic"))
    assert catalog is not None
    assert "catalog" not in sources
    assert "catalog_version" in catalog


def test_an_explicit_catalog_overrides_the_convention(tmp_path: Path) -> None:
    """Pointing several projects at one shared catalog is the case that needs
    the flag; the convention alone cannot express it."""
    shared = tmp_path / "shared.yaml"
    shared.write_text((FIXTURES / "ecom_basic" / "catalog.yaml").read_text())
    sources, catalog = read_spec_directory(str(FIXTURES / "ecom_basic"), catalog=str(shared))
    assert catalog == shared.read_text()
    # The directory's own catalog.yaml is now an ordinary document, and
    # load_project refuses it by name with a message that says so — a loud
    # failure rather than two catalogs silently disagreeing.
    assert "catalog" in sources


def test_a_project_without_a_catalog_loads(capsys: pytest.CaptureFixture[str]) -> None:
    sources, catalog = read_spec_directory(str(FIXTURES / "minimal"))
    assert catalog is None
    assert sources
    code, _out, err = run(capsys, "fingerprint", str(FIXTURES / "minimal"))
    assert code == EXIT_OK, err


def test_a_missing_explicit_catalog_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    code, _out, err = run(capsys, "resolve", ECOM, "--catalog", "/no/such/catalog.yaml")
    assert code == EXIT_USAGE
    assert "not a file" in err


# ....................... #
# io.py's own edges


def test_write_files_creates_nested_parents(tmp_path: Path) -> None:
    written = write_files(str(tmp_path), {"models/gold/orders.sql": "SELECT 1\n"})
    assert (tmp_path / "models" / "gold" / "orders.sql").read_text() == "SELECT 1\n"
    assert written == [str(tmp_path / "models" / "gold" / "orders.sql")]


def test_write_files_refuses_a_path_that_escapes_the_output_directory(tmp_path: Path) -> None:
    """Artifact paths come from the emitters, so this cannot fire today —
    which is exactly the condition under which the check gets left out and
    then matters."""
    with pytest.raises(CliIoError, match="escapes"):
        write_files(str(tmp_path / "out"), {"../escaped.sql": "SELECT 1\n"})


def test_reading_a_directory_as_a_file_is_a_usage_error(tmp_path: Path) -> None:
    from bloomery.cli.io import read_text

    with pytest.raises(CliIoError, match="not a file"):
        read_text(str(tmp_path))


# ....................... #
# D9 — what is deliberately absent


def test_there_is_no_execution_command() -> None:
    """``explain`` prints SQL; ``run`` does not exist, and never will (D9).

    This is what keeps the test suite infrastructure-free and bloomery a
    compiler. Pinned because the pressure to add it is real and would arrive as
    a small, reasonable-looking patch.
    """
    parser = build_parser()
    actions = [
        action for action in parser._subparsers._group_actions  # type: ignore[union-attr] # noqa: SLF001
    ]
    commands = set(actions[0].choices)  # type: ignore[arg-type]
    assert commands == {"compile", "plan", "resolve", "explain", "schema", "fingerprint"}
    for forbidden in ("run", "init", "new", "watch", "serve"):
        assert forbidden not in commands


def test_no_command_takes_a_connection_or_a_profile() -> None:
    """The other half of D9: no credentials, no config file, no connection
    settings anywhere on the surface."""
    parser = build_parser()
    text = parser.format_help()
    subparsers = parser._subparsers._group_actions[0]  # type: ignore[union-attr] # noqa: SLF001
    for sub in subparsers.choices.values():  # type: ignore[attr-defined]
        text += sub.format_help()
    for forbidden in ("--profile", "--connection", "--password", "--token", "--config"):
        assert forbidden not in text


def test_the_schema_kind_flag_offers_exactly_the_spec_kinds() -> None:
    parser = build_parser()
    subparsers = parser._subparsers._group_actions[0]  # type: ignore[union-attr] # noqa: SLF001
    schema_parser = subparsers.choices["schema"]  # type: ignore[attr-defined]
    kinds = next(
        action.choices for action in schema_parser._actions if action.dest == "kind"  # noqa: SLF001
    )
    assert set(kinds) == {kind.value for kind in SpecKind}


def test_fingerprint_prints_the_projects_own_fingerprint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    project, catalog = load_fixture("ecom_basic")
    expected = project_fingerprint(build_project_ir(project, catalog=catalog))
    code, out, err = run(capsys, "fingerprint", ECOM)
    assert code == EXIT_OK, err
    assert out.strip() == expected
