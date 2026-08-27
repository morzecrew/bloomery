"""The command line (RFC 0020 §5.2, D4–D6, D9).

Three properties carry the section.

**Every command works on a real fixture.** Seven commands over the corpus, exit
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
import os
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import bloomery
from bloomery import (
    BackfillScope,
    Change,
    ChangeClass,
    LruManifestHydrator,
    MetricFlowPlanner,
    MetricRequest,
    Op,
    Plan,
    ReplayScope,
    RowPolicy,
    SpecEvidence,
    SpecKind,
    Stage,
    Target,
    all_spec_schemas,
    build_project_ir,
    compile_project,
    evaluate,
    plan,
    project_fingerprint,
)
from bloomery.cli import EXIT_OK, EXIT_REFUSED, EXIT_USAGE, build_parser, main
from bloomery.cli.io import CliIoError, read_spec_directory, write_files
from bloomery.cli.render import render_evidence, render_plan
from bloomery.cli.serialize import as_json_value
from bloomery.errors import BloomeryError
from bloomery.naming import DefaultNaming
from support.compiling import load_fixture

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ECOM = str(FIXTURES / "ecom_basic")
ROLE_PLAYING = str(FIXTURES / "role_playing_dates")


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
        evaluate(project, catalog=catalog)
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


FANOUT = str(FIXTURES / "fanout_trap")


# ....................... #
# RFC 0022 D8 — `resolve` reports reachability *and* refusals


def test_a_refused_spec_still_reports_what_was_reachable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The whole of the re-point, as output.

    Before this, a spec that refused anywhere printed nothing at all — the
    refusal propagated and `main` printed one message. A spec mid-draft is
    exactly when an author wants both halves, and the reachability was computed
    two stages before the refusal either way.
    """
    code, out, _err = run(capsys, "resolve", FANOUT)
    assert code == EXIT_REFUSED
    assert out.startswith("Stage: guardrails")
    assert "landed_revenue" in out  # reachable, computed before the refusal
    assert "marts: marts.order_items.measures.shipping_cost" in out  # and the refusal


def test_a_refused_spec_exits_one_rather_than_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reporting a refusal instead of raising it must not turn it into success:
    a pipeline branches on the code, and the spec is still refused."""
    assert run(capsys, "resolve", FANOUT)[0] == EXIT_REFUSED
    assert run(capsys, "resolve", ECOM)[0] == EXIT_OK


def test_a_refused_spec_serializes_its_refusals_with_source_paths(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--format json` on the specs the command exists for.

    A refusal is not a dataclass, so the structural converter has to know what
    one looks like or this fails on exactly those specs. Each arrives with its
    own `source_path` rather than as one aggregate message to re-parse.
    """
    code, out, err = run(capsys, "resolve", FANOUT, "--format", "json")
    assert code == EXIT_REFUSED, err
    payload = json.loads(out)
    assert payload["stage_reached"] == "guardrails"
    assert payload["fingerprint"] is None
    refusals = payload["refusals"]
    assert len(refusals) > 1
    assert all(refusal["source_path"] and refusal["type"] for refusal in refusals)


def test_a_structured_fix_suggestion_reaches_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """RFC 0020's suggestions are values on the error. The converter reads them
    off `vars()` rather than from a per-class list, so one added to a sixth
    error arrives in the same commit that adds it."""
    code, out, _err = run(capsys, "resolve", FANOUT, "--format", "json")
    assert code == EXIT_REFUSED
    violations = [r for r in json.loads(out)["refusals"] if r["type"] == "GrainViolation"]
    assert violations
    assert violations[0]["offending_measures"] == [{"grain": "order", "measure": "shipping_cost"}]


def test_a_step_wiring_project_reports_the_unwired_step(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The one project shape whose answer changed.

    The CLI offers no `--steps` — a `StepRegistry` is a caller-assembled
    compile input — and `resolve()` never looked at steps, so this printed
    reachability as though the wiring were not there. `compile` on the same
    project already refused; now the two agree.
    """
    code, out, _err = run(capsys, "resolve", str(FIXTURES / "step_resolution"))
    assert code == EXIT_REFUSED
    assert "Stage: lower" in out
    assert "UnknownStep" in out
    assert "steps: steps.resolve_customers@3" in out


def test_resolve_json_carries_fields_the_table_does_not_print(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The concrete meaning of "not a lossier surface": the entity list and the
    marts\' measures and dimensions are on the returned value and off the
    table, and a script should not have to drop to Python for them."""
    payload = _json(capsys, "resolve", ECOM, "--format", "json")
    assert isinstance(payload, dict)
    assert payload["entities"]
    marts = payload["marts"]
    assert isinstance(marts, list)
    assert all(mart["measures"] and mart["dimensions"] for mart in marts)


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


@pytest.mark.parametrize(
    "argv",
    [
        ("explain", ECOM, "--metrics", "gross_revenue", "--limit", "notanint"),
        ("compile", ECOM, "--nonsuch-flag"),
        ("nonsuch-command",),
    ],
    ids=["bad-int", "unknown-flag", "unknown-command"],
)
def test_a_parser_level_usage_error_is_returned_not_raised(
    capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]
) -> None:
    """``main``'s docstring invites calling it as a function and reading the
    code. ``argparse.parse_args`` writes its message and *raises* ``SystemExit``,
    so these three escaped instead of coming back as ``2`` — the shell saw the
    right code, a programmatic caller saw an exception."""
    code, _out, _err = run(capsys, *argv)
    assert code == EXIT_USAGE


def test_help_returns_zero_rather_than_raising(capsys: pytest.CaptureFixture[str]) -> None:
    """The other ``SystemExit`` argparse raises. Passing the code through
    rather than flattening every parser exit to ``2`` is what keeps this ``0``."""
    code, out, _err = run(capsys, "--help")
    assert code == EXIT_OK
    assert "compile" in out


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (("compile", ECOM, "--target", "sqlmehs"), "unknown target"),
        (("compile", ECOM, "--dialect", "ducdkb"), "unknown dialect"),
        (
            ("explain", ECOM, "--metrics", "gross_revenue", "--dialect", "ducdkb"),
            "unknown dialect",
        ),
    ],
    ids=["target", "compile-dialect", "explain-dialect"],
)
def test_a_mistyped_target_or_dialect_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], argv: tuple[str, ...], expected: str
) -> None:
    """Both resolve through the library and raised `EmitError`, so a typo came
    back as `1` — "bloomery read your spec and said no" — for a spec it never
    opened. `--grain` and `--policy` already get this treatment; these two were
    the inconsistency."""
    code, _out, err = run(capsys, *argv)
    assert code == EXIT_USAGE
    assert expected in err


def test_a_known_target_is_not_caught_by_the_name_check(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The nearest non-trigger. A check that refused everything would pass every
    assertion above."""
    code, _out, err = run(capsys, "compile", ECOM, "--target", "cube", "--out", str(tmp_path))
    assert code == EXIT_OK, err


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
# The renderer and the serializer, on the branches the corpus does not reach


def test_an_empty_plan_says_so_rather_than_printing_a_header() -> None:
    """`plan(ir, ir)` is the empty plan (RFC 0007 D2). A table with a zero count
    and no rows would read as "something happened and I lost it"."""
    empty = Plan(changes=(), backfill_scope=BackfillScope(entities=(), restates_history=False), downstream_impact=())
    assert render_plan(empty) == "No changes."


def test_the_plan_table_carries_replay_and_downstream_sections() -> None:
    """Two sections nothing in the fixture corpus produces together. Both are
    conditional, so both are a branch that can silently stop rendering."""
    rendered = render_plan(
        Plan(
            changes=(
                Change(
                    entity="order",
                    subject="quality:total_positive",
                    change_class=ChangeClass.RESTATING,
                    detail="rule relaxed",
                ),
            ),
            backfill_scope=BackfillScope(entities=("order",), restates_history=True),
            downstream_impact=("gross_revenue",),
            replay_scope=ReplayScope(entities=("order",)),
        )
    )
    assert "1 breaking" not in rendered
    assert "Quarantine replay scope" in rendered
    assert "Downstream metrics" in rendered
    assert "gross_revenue" in rendered
    # Padded to the widest cell per column, and never with trailing whitespace:
    # invisible in a terminal, very visible in a diff of captured output.
    assert not any(line != line.rstrip() for line in rendered.splitlines())


def test_an_empty_evaluation_renders_the_stage_and_both_headers() -> None:
    """A project with nothing reachable is a legitimate state — a catalog-free
    bring-up — and the zero counts are the answer, not an empty page.

    The stage leads, which is the point: at ``COMPLETE`` these zeros mean
    "nothing unreachable", and at any other stage they mean "never computed"
    (RFC 0022 D5). The same three lines without the first would be ambiguous.
    """
    rendered = render_evidence(SpecEvidence(stage_reached=Stage.COMPLETE))
    assert rendered.splitlines() == [
        "Stage: complete",
        "",
        "Reachable (0)",
        "",
        "Unreachable (0)",
    ]


def test_an_errors_own_attribute_cannot_redefine_the_type_discriminator() -> None:
    """`type` names the error class and `message` is `str(exc)` — that is the
    contract a consumer branches on.

    Attributes are read off `vars()`, so an error carrying its own `type` used
    to overwrite the class name and every `payload["type"] == "GrainViolation"`
    silently stopped matching. No error in this package assigns one, but the
    hierarchy is public and extensible, and nothing downstream can detect a
    corrupted discriminator. The reserved keys are written last now, so they
    win; the shadowed attribute is what is lost, which is the smaller harm.
    """

    class VendorError(BloomeryError):
        def __init__(self, message: str) -> None:
            super().__init__(message, source_path="specs/x.yaml")
            self.type = "vendor-code-42"
            self.message = "not the message"

    payload = as_json_value(VendorError("boom"))
    assert isinstance(payload, dict)
    assert payload["type"] == "VendorError"
    assert payload["message"] == "boom"
    assert payload["source_path"] == "specs/x.yaml"


def test_a_decimal_serializes_as_a_string_never_a_float() -> None:
    """The core invariant, at the one seam that could break it (RFC 0003 D5).

    `json.dumps` would turn a float into a lossy decimal literal, and a caller
    reading a tolerance or a measure back as `0.1 + 0.2` is the whole reason
    floats are banned from the package.
    """
    assert as_json_value(Decimal("0.01")) == "0.01"
    assert as_json_value((Decimal("1.10"),)) == ["1.10"]
    assert json.dumps(as_json_value(Decimal("0.01"))) == '"0.01"'


def test_a_mapping_serializes_with_string_keys() -> None:
    """JSON objects are keyed by strings; a returned mapping keyed by an enum
    would otherwise reach `json.dumps` and fail there instead of here."""
    assert as_json_value({SpecKind.METRICS: (1, 2)}) == {"metrics": [1, 2]}


# ....................... #
# io.py's own edges


def test_a_non_utf8_document_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """`Path.read_text` raises `UnicodeDecodeError`, which `main` does not
    catch — so a latin-1 spec printed a traceback."""
    (tmp_path / "entity_model.yaml").write_bytes("spec_version: 1  # caf\xe9\n".encode("latin-1"))
    code, _out, err = run(capsys, "resolve", str(tmp_path))
    assert code == EXIT_USAGE
    assert "not UTF-8 text" in err


def test_an_unreadable_document_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The other half: `is_file()` says it is a file, and the read still fails.
    Skipped when the suite runs as root, for whom the mode bits do nothing."""
    if os.geteuid() == 0:  # pragma: no cover — CI runs unprivileged
        pytest.skip("root ignores the permission bits this test sets")
    document = tmp_path / "entity_model.yaml"
    document.write_text("spec_version: 1\nentities: {}\n")
    document.chmod(0o000)
    try:
        code, _out, err = run(capsys, "resolve", str(tmp_path))
    finally:
        document.chmod(0o644)
    assert code == EXIT_USAGE
    assert "entity_model.yaml" in err


def test_an_unwritable_output_directory_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """`write_files` creates parents and writes; both can fail on a read-only
    destination, and neither failure was named."""
    if os.geteuid() == 0:  # pragma: no cover — CI runs unprivileged
        pytest.skip("root ignores the permission bits this test sets")
    out = tmp_path / "out"
    out.mkdir(mode=0o500)
    try:
        code, _stdout, err = run(capsys, "compile", ECOM, "--out", str(out))
    finally:
        out.chmod(0o755)
    assert code == EXIT_USAGE
    assert str(out) in err


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


def test_an_unlistable_directory_is_a_usage_error(tmp_path: Path) -> None:
    """`is_dir()` says the path is a directory, not that it can be listed."""
    if os.geteuid() == 0:  # pragma: no cover — CI runs unprivileged
        pytest.skip("root ignores the permission bits this test sets")
    directory = tmp_path / "specs"
    directory.mkdir()
    (directory / "entity_model.yaml").write_text("spec_version: 1\n")
    directory.chmod(0o000)
    try:
        with pytest.raises(CliIoError):
            read_spec_directory(str(directory))
    finally:
        directory.chmod(0o755)


def test_an_explicit_catalog_inside_the_directory_is_not_also_a_document(
    tmp_path: Path,
) -> None:
    """`--catalog` pointing at a file in the scanned directory: it has to come
    back as the catalog *and* leave the project, or `load_project` would refuse
    the document it was just handed separately."""
    (tmp_path / "entity_model.yaml").write_text("spec_version: 1\n")
    (tmp_path / "shared.yaml").write_text("catalog_version: 1\n")
    sources, catalog = read_spec_directory(str(tmp_path), catalog=str(tmp_path / "shared.yaml"))
    assert catalog == "catalog_version: 1\n"
    assert set(sources) == {"entity_model"}


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
    assert commands == {
        "compile",
        "plan",
        "resolve",
        "lineage",
        "explain",
        "schema",
        "fingerprint",
    }
    for forbidden in ("run", "init", "new", "watch", "serve"):
        assert forbidden not in commands


def test_version_is_reachable_without_a_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``bloomery --version`` answers the question the bug-report template asks.

    The subparser is ``required=True``, so a flag that only worked *after* a
    command would be a flag nobody could use to identify a broken install —
    which is the one moment a version string is worth having. argparse exits
    while consuming the option, before the required-command check, and ``main``
    turns that into the ``0`` a shell reads.
    """
    assert main(["--version"]) == EXIT_OK
    printed = capsys.readouterr().out.strip()
    assert printed == f"bloomery {bloomery.__version__}"
    assert printed != "bloomery "  # an empty version reads as success and is not


def test_the_reported_version_is_the_installed_one() -> None:
    """``__version__`` comes from the build, not from a string in the tree.

    ``hatch-vcs`` writes ``_version.py`` from the git tag, so a hand-maintained
    constant here would be a second version that drifts from the wheel's the
    first time someone forgets it. The fallback is deliberately unmistakable:
    a bug report quoting ``0.0.0+unknown`` says "unbuilt checkout" rather than
    naming a release that exists.
    """
    assert bloomery.__version__
    assert bloomery.__version__ != "0.0.0+unknown", (
        "the test environment is built by `uv sync`, so the generated "
        "_version.py must be present — an unbuilt tree is the only fallback case"
    )


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


# ....................... #
# `lineage` (RFC 0031 §5.5, P2)


def test_lineage_walks_upstream_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "lineage", ECOM, "--node", "metric.gross_revenue")

    assert code == EXIT_OK, err
    assert "metric.gross_revenue  (upstream)" in out
    # The whole chain, source column through recipe to metric — the §2 question.
    assert "source.shopify__order_lines.$.total  --recipe:from_total-->" in out
    assert "canonical.unit_price                 --requires-->" in out


def test_lineage_downstream_answers_what_a_change_would_reach(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = run(
        capsys,
        "lineage",
        ECOM,
        "--node",
        "source.shopify__order_lines.$.total",
        "--direction",
        "downstream",
    )

    assert code == EXIT_OK, err
    for reached in ("metric.gross_revenue", "metric.margin", "metric.average_order_value"):
        assert reached in out


def test_lineage_both_merges_the_two_walks(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(
        capsys, "lineage", ECOM, "--node", "order_item.unit_price", "--direction", "both"
    )

    assert code == EXIT_OK, err
    assert "(both)" in out
    assert "source.shopify__order_lines.$.total" in out  # upstream side
    assert "metric.gross_revenue" in out  # downstream side


def test_lineage_json_matches_the_python_call(capsys: pytest.CaptureFixture[str]) -> None:
    """The JSON surface is the value, not a rendering of it."""
    project, catalog = load_fixture("ecom_basic")
    resolution = bloomery.resolve(project, catalog)
    expected = as_json_value(
        bloomery.lineage(
            resolution.graph,
            bloomery.Node(kind=bloomery.NodeKind.METRIC, name="metric.gross_revenue"),
            bloomery.Direction.UPSTREAM,
        )
    )
    assert (
        _json(capsys, "lineage", ECOM, "--node", "metric.gross_revenue", "--format", "json")
        == expected
    )


def test_lineage_of_a_leaf_says_so_rather_than_printing_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`order_count` is `agg: count` with no `requires`, so it has no upstream.

    An empty stdout reads as a command that failed. The reader asked a question
    and needs to see it came back empty — which is an answer, not a miss.
    """
    code, out, err = run(capsys, "lineage", ECOM, "--node", "metric.order_count")

    assert code == EXIT_OK, err
    assert "no upstream lineage" in out
    assert "leaf in that direction" in out


def test_lineage_says_when_max_depth_truncated_the_walk(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bounded answer that does not say it is bounded is the failure
    RFC 0022 D5 names."""
    code, bounded, err = run(
        capsys, "lineage", ECOM, "--node", "metric.average_order_value", "--max-depth", "1"
    )
    assert code == EXIT_OK, err
    assert "truncated:" in bounded

    code, whole, err = run(capsys, "lineage", ECOM, "--node", "metric.average_order_value")
    assert code == EXIT_OK, err
    assert "truncated:" not in whole


def test_a_mistyped_node_is_refused_with_the_spelling_it_meant(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The ids are long and dotted, and the graph holds the right spelling —
    so "not found" alone would be withholding the answer (RFC 0031 §5.5)."""
    code, _out, err = run(capsys, "lineage", ECOM, "--node", "metric.gross_revenu")

    assert code == EXIT_REFUSED
    assert "did you mean: metric.gross_revenue" in err


def test_a_node_with_no_near_miss_is_taught_the_id_scheme(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The branch a happy-path check never reaches.

    `difflib` has a cutoff, so "no suggestions" is reachable — and a bare "not
    found" there is exactly the message §5.5 argues against. The fallback names
    the kinds, so a reader who mistyped the *scheme* learns the scheme.
    """
    code, _out, err = run(capsys, "lineage", ECOM, "--node", "zzzzzzzz")

    assert code == EXIT_REFUSED
    assert "did you mean" not in err
    assert "entity field is spelled '<entity>.<field>' with no prefix" in err
    for kind in ("metric", "canonical_field", "source_column", "entity_field"):
        assert kind in err


def test_lineage_suggestions_are_bounded_and_deterministic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Bounded because a large graph must not print a guess per node; identical
    across runs because the message reaches stdout and RFC 0003 binds it."""
    first = run(capsys, "lineage", ECOM, "--node", "metric.")[2]
    again = run(capsys, "lineage", ECOM, "--node", "metric.")[2]

    assert first == again
    assert first.count("did you mean") <= 1
    suggestions = first.split("did you mean: ")[-1]
    assert len(suggestions.split(", ")) <= 5


def test_lineage_rejects_a_bad_direction_as_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A wrong flag value is `2`, not `1` — the invocation was wrong, and a
    pipeline must not treat it as a spec that was refused."""
    code, _out, _err = run(capsys, "lineage", ECOM, "--node", "metric.margin", "--direction", "up")

    assert code == EXIT_USAGE


def test_lineage_rejects_a_negative_max_depth_as_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A wrong flag *value* is `2`, exactly as `--direction up` is.

    The library raises `ValueError` for a negative depth, which is right for a
    caller in Python and wrong to let reach a shell: `main` catches
    `BloomeryError`, so a bare `ValueError` escaped as a traceback — neither
    the `1` that means refused nor the `2` that means the invocation was wrong.
    """
    code, _out, err = run(
        capsys, "lineage", ECOM, "--node", "metric.margin", "--max-depth", "-1"
    )

    assert code == EXIT_USAGE
    assert "max-depth" in err


def test_lineage_rejects_a_non_integer_max_depth_with_its_own_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The detection branch inside the `--max-depth` type.

    Without it argparse still refuses — but with "invalid _depth value", naming
    a private function the reader cannot act on. It exists for the message, so
    the message is what is asserted.
    """
    code, _out, err = run(
        capsys, "lineage", ECOM, "--node", "metric.margin", "--max-depth", "abc"
    )

    assert code == EXIT_USAGE
    assert "--max-depth must be an integer, got 'abc'" in err
    assert "_depth" not in err


def test_lineage_max_depth_zero_is_accepted(capsys: pytest.CaptureFixture[str]) -> None:
    """Zero is a bound, not an error — the root alone, and the walk says it was cut."""
    code, out, err = run(
        capsys, "lineage", ECOM, "--node", "metric.margin", "--max-depth", "0"
    )

    assert code == EXIT_OK, err
    assert "stopped the walk before its first edge" in out


def test_a_walk_bounded_to_nothing_never_calls_its_root_a_leaf(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--max-depth 0` on a node with lineage returns no edges *and* truncated.

    Rendering the two independently printed "this node is a leaf in that
    direction" and then "there is more beyond this" — both halves of a
    contradiction, and the half a reader acts on is the false one. The how-to
    states the distinction the output collapsed: bounding to nothing and
    finding nothing are different facts.
    """
    code, bounded, err = run(
        capsys, "lineage", ECOM, "--node", "metric.average_order_value", "--max-depth", "0"
    )

    assert code == EXIT_OK, err
    assert "leaf" not in bounded
    assert "--max-depth stopped the walk before its first edge" in bounded

    # The genuine leaf is still called one — the fix must not cost the other case.
    code, leaf, err = run(capsys, "lineage", ECOM, "--node", "metric.order_count")
    assert code == EXIT_OK, err
    assert "leaf in that direction" in leaf
    assert "--max-depth" not in leaf


def test_both_never_describes_itself_as_a_direction(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every empty-walk sentence names its direction, and "both" is not one.

    Interpolated, they read "no both lineage" and "this node has both
    lineage" — ungrammatical, and the leaf line is also *false*: a merged walk
    has two directions, so there is no "that direction" to be a leaf in.
    `role_playing_dates` carries a metric nothing feeds and nothing composes,
    which is the only shape that reaches the first sentence under `both`.
    """
    code, isolated, err = run(
        capsys, "lineage", ROLE_PLAYING, "--node", "metric.revenue", "--direction", "both"
    )
    assert code == EXIT_OK, err
    assert "no lineage in either direction" in isolated
    assert "both lineage" not in isolated
    assert "that direction" not in isolated

    code, bounded, err = run(
        capsys,
        "lineage",
        ECOM,
        "--node",
        "metric.average_order_value",
        "--direction",
        "both",
        "--max-depth",
        "0",
    )
    assert code == EXIT_OK, err
    assert "stopped the walk before its first edge" in bounded
    assert "both lineage" not in bounded

    # The single-direction wording is unchanged — it was already grammatical.
    code, one_way, err = run(
        capsys, "lineage", ROLE_PLAYING, "--node", "metric.revenue", "--direction", "upstream"
    )
    assert code == EXIT_OK, err
    assert "no upstream lineage" in one_way
    assert "leaf in that direction" in one_way


def test_lineage_help_explains_every_direction_it_accepts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`both` is offered in `choices` and was the one the help text did not gloss."""
    _code, out, _err = run(capsys, "lineage", "--help")

    for direction in ("upstream:", "downstream:", "both:"):
        assert direction in out, out


def test_a_project_with_an_empty_graph_refuses_readably(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An entity model with no mappings loads, resolves, and has no nodes.

    That is a draft spec — exactly the state someone runs `lineage` in to
    explore — and the kinds fallback then joined an empty set, printing
    "its ids are of kinds  — an entity field is spelled...".
    """
    (tmp_path / "entity_model.yaml").write_text(
        "spec_version: 1\n"
        "entities:\n"
        "  customer:\n"
        "    grain: one row per customer\n"
        "    key: [customer_id]\n"
        "    fields:\n"
        "      customer_id: {type: string}\n"
    )
    code, _out, err = run(capsys, "lineage", str(tmp_path), "--node", "customer.customer_id")

    assert code == EXIT_REFUSED
    assert "kinds  —" not in err, "the kind list was empty and joined into a gap"
    assert "dependency graph is empty" in err
    assert "nothing maps a source into an entity yet" in err

