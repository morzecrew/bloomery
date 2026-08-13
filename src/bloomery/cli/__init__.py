"""The command line: six commands, each a shell over one public function
(RFC 0020 §5.2, D4–D6).

``bloomery compile|plan|resolve|explain|schema|fingerprint``. Every command is
*read files → call the public API → write stdout or a directory*. None of them
adds logic: what they add is that the most useful thing bloomery knows — which
metrics are computable, and which specific leaf is missing for the ones that
are not — stops requiring a Python script to ask.

**Exit codes**, because a script has to be able to tell these apart:

* ``0`` — success.
* ``1`` — a refusal. A :class:`~bloomery.BloomeryError` is a *correct* outcome:
  bloomery looked at the spec and said no, with a reason. Conflating it with a
  crash is what makes a pipeline retry a spec error.
* ``2`` — a usage error: a path that is not there, a flag that is not a flag.

``--format json`` on ``plan``, ``resolve`` and ``explain`` emits the same
values the Python API returns, so the CLI is not a second, lossier surface
(:mod:`bloomery.cli.serialize`).

**What is deliberately absent.** No ``run`` and no engine connection, ever
(D9) — ``explain`` prints SQL and the consumer executes it, which is what keeps
the test suite infrastructure-free and the library a compiler. No config file,
profile, or credentials. No scaffolding, watch mode or daemon: each implies
state or an opinion about project layout that bloomery does not hold.

Argument parsing is :mod:`argparse` and table rendering is hand-rolled — no new
runtime dependency (D6). Only :mod:`bloomery.cli.io` touches a filesystem
(D5/D12), and the import contract makes ``bloomery.cli`` the top layer, so no
library module can import any of this.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING

from bloomery import (
    BloomeryError,
    LruManifestHydrator,
    MetricFlowPlanner,
    MetricRequest,
    Op,
    RowPolicy,
    SpecKind,
    Target,
    TimeGrain,
    all_spec_schemas,
    build_project_ir,
    compile_project,
    load_catalog,
    load_project,
    plan,
    project_fingerprint,
    resolve,
    spec_json_schema,
)
from bloomery.cli import io, render, serialize
from bloomery.naming import DefaultNaming
from bloomery.planner import parse_filter_json

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bloomery import Catalog, Project, ProjectIR

__all__ = ["main"]

#: Success, refusal, usage error (§5.2). Named rather than spelled inline so
#: the docs page and the tests can cite the same three constants.
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2


class _Usage(Exception):
    """A usage error raised after parsing — a value argparse accepted but that
    cannot be used (an unknown dialect spelling, a malformed ``--policy``).

    Separate from ``parser.error`` so it can be raised from a command body,
    where the parser is no longer in scope, and still exit ``2``.
    """


# ....................... #
# Loading — the same three lines every command starts with.


def _load(arguments: argparse.Namespace) -> tuple[Project, Catalog | None]:
    sources, catalog_text = io.read_spec_directory(
        arguments.directory, catalog=getattr(arguments, "catalog", None)
    )
    catalog = load_catalog(catalog_text) if catalog_text is not None else None
    return load_project(sources), catalog


def _load_ir(arguments: argparse.Namespace) -> ProjectIR:
    project, catalog = _load(arguments)
    return build_project_ir(project, catalog=catalog)


def _emit(payload: object, *, as_json: bool) -> None:
    """One place that writes to stdout, so every command agrees on the shape.

    JSON is indented and sorted: a CLI's JSON is read by people at least as
    often as by programs, and a sorted document diffs.
    """
    text = json.dumps(payload, indent=2, sort_keys=True) if as_json else str(payload)
    sys.stdout.write(text + "\n")


# ....................... #
# Commands


def _compile(arguments: argparse.Namespace) -> int:
    project, catalog = _load(arguments)
    artifacts = compile_project(
        project, target=arguments.target, dialect=arguments.dialect, catalog=catalog
    )
    if arguments.out is not None:
        written = io.write_files(
            arguments.out, {artifact.path: artifact.content for artifact in artifacts}
        )
        for path in written:
            sys.stdout.write(f"{path}\n")
        return EXIT_OK
    _emit(serialize.artifacts_as_json(artifacts), as_json=True)
    return EXIT_OK


def _plan(arguments: argparse.Namespace) -> int:
    old = _load_ir(argparse.Namespace(directory=arguments.old, catalog=arguments.catalog))
    new = _load_ir(argparse.Namespace(directory=arguments.new, catalog=arguments.catalog))
    result = plan(old, new)
    if arguments.format == "json":
        _emit(serialize.as_json_value(result), as_json=True)
    else:
        _emit(render.render_plan(result), as_json=False)
    return EXIT_OK


def _resolve(arguments: argparse.Namespace) -> int:
    project, catalog = _load(arguments)
    resolution = resolve(project, catalog)
    if arguments.format == "json":
        _emit(serialize.as_json_value(resolution), as_json=True)
    else:
        _emit(render.render_resolution(resolution), as_json=False)
    return EXIT_OK


def _parse_policy(spelling: str | None) -> RowPolicy | None:
    """``--policy 'region eq EU'`` → a :class:`~bloomery.RowPolicy`.

    Three whitespace-separated tokens, the last comma-split for the multi-value
    operators. RFC 0020 §10 question 2, answered yes: making row scoping
    inspectable without Python is most of its debugging value, and
    :class:`~bloomery.RowPolicy` is a plain dimension/operator/value triple, so
    exposing it puts nothing on the surface that the public type does not
    already carry.

    The spelling stays neutral for the reason the type is: deciding *whose*
    policy applies is upstream work bloomery must not know about. This flag
    takes a filter, not an identity, and nothing about a caller reaches it.
    """
    if spelling is None:
        return None
    parts = spelling.split(maxsplit=2)
    if len(parts) != 3:
        msg = f"--policy takes 'dimension op value', got {spelling!r}"
        raise _Usage(msg)
    dimension, operator, raw = parts
    try:
        op = Op(operator)
    except ValueError as exc:
        known = ", ".join(sorted(member.value for member in Op))
        msg = f"--policy operator {operator!r} is not one of: {known}"
        raise _Usage(msg) from exc
    value = tuple(raw.split(",")) if op in (Op.IN, Op.NOT_IN) else raw
    return RowPolicy(dimension=dimension, op=op, value=value)


def _explain(arguments: argparse.Namespace) -> int:
    ir = _load_ir(arguments)
    filters = parse_filter_json(json.loads(arguments.where)) if arguments.where else ()
    request = MetricRequest(
        metrics=tuple(arguments.metrics.split(",")),
        dimensions=tuple(arguments.by.split(",")) if arguments.by else (),
        filters=filters,
        time_grain=TimeGrain(arguments.grain) if arguments.grain else None,
        limit=arguments.limit,
    )
    naming = DefaultNaming()
    planner = MetricFlowPlanner(LruManifestHydrator(naming), naming=naming)
    query = planner.plan(
        ir, request, dialect=arguments.dialect, policy=_parse_policy(arguments.policy)
    )
    if arguments.format == "json":
        _emit(serialize.as_json_value(query), as_json=True)
    else:
        _emit(query.sql + "\n\n" + query.explanation.render(), as_json=False)
    return EXIT_OK


def _schema(arguments: argparse.Namespace) -> int:
    # `--kind` is the single-document case and is kept a separate branch rather
    # than a one-entry mapping fished back out: stdout gets the schema itself,
    # so it can be piped straight into a validator, while the no-flag form gets
    # the six keyed by kind.
    if arguments.kind:
        kind = SpecKind(arguments.kind)
        schemas = {kind: spec_json_schema(kind)}
        payload: object = schemas[kind]
    else:
        schemas = dict(all_spec_schemas())
        payload = {each.value: schema for each, schema in schemas.items()}
    if arguments.out is not None:
        written = io.write_files(
            arguments.out,
            {
                f"{each.value}.json": json.dumps(schema, indent=2) + "\n"
                for each, schema in schemas.items()
            },
        )
        for path in written:
            sys.stdout.write(f"{path}\n")
        return EXIT_OK
    _emit(payload, as_json=True)
    return EXIT_OK


def _fingerprint(arguments: argparse.Namespace) -> int:
    _emit(project_fingerprint(_load_ir(arguments)), as_json=False)
    return EXIT_OK


# ....................... #
# Parser


def _add_spec_directory(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("directory", help="directory of spec documents")
    parser.add_argument(
        "--catalog",
        help="catalog document (default: catalog.yaml in the directory, if present)",
    )


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="output format (json emits the same values the Python API returns)",
    )


def build_parser() -> argparse.ArgumentParser:
    """The whole command line, as data.

    Exposed rather than private so the docs page and the tests read the same
    definition — a usage string transcribed by hand is a usage string that goes
    stale.
    """
    parser = argparse.ArgumentParser(
        prog="bloomery",
        description="Compile, plan and inspect bloomery specs. Reads files; executes nothing.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    compile_parser = commands.add_parser("compile", help="compile specs to target artifacts")
    _add_spec_directory(compile_parser)
    compile_parser.add_argument(
        "--target",
        default=Target.SQLMESH.value,
        help="emit target (sqlmesh, cube, dbt, or a registered name)",
    )
    compile_parser.add_argument("--dialect", default="duckdb", help="SQL dialect")
    compile_parser.add_argument("--out", help="write artifacts here (default: JSON on stdout)")
    compile_parser.set_defaults(run=_compile)

    plan_parser = commands.add_parser(
        "plan", help="diff two spec directories into a migration plan"
    )
    plan_parser.add_argument("old", help="the deployed spec directory")
    plan_parser.add_argument("new", help="the proposed spec directory")
    plan_parser.add_argument("--catalog", help="catalog document used for both sides")
    _add_format(plan_parser)
    plan_parser.set_defaults(run=_plan)

    resolve_parser = commands.add_parser(
        "resolve", help="which metrics are computable, and what is missing for the rest"
    )
    _add_spec_directory(resolve_parser)
    _add_format(resolve_parser)
    resolve_parser.set_defaults(run=_resolve)

    explain_parser = commands.add_parser("explain", help="plan one metric request; print SQL")
    _add_spec_directory(explain_parser)
    explain_parser.add_argument("--metrics", required=True, help="comma-separated metric names")
    explain_parser.add_argument("--by", help="comma-separated dimension names")
    explain_parser.add_argument("--where", help="filter document, as JSON")
    explain_parser.add_argument("--grain", help="time grain to group date-role dimensions by")
    explain_parser.add_argument("--limit", type=int, help="row limit")
    explain_parser.add_argument("--policy", help="row policy, as 'dimension op value'")
    explain_parser.add_argument("--dialect", default="duckdb", help="SQL dialect")
    _add_format(explain_parser)
    explain_parser.set_defaults(run=_explain)

    schema_parser = commands.add_parser("schema", help="emit the JSON Schema for the spec kinds")
    schema_parser.add_argument(
        "--kind", choices=[kind.value for kind in SpecKind], help="one kind (default: all six)"
    )
    schema_parser.add_argument("--out", help="write one file per kind here")
    schema_parser.set_defaults(run=_schema)

    fingerprint_parser = commands.add_parser(
        "fingerprint", help="the project's deterministic IR fingerprint"
    )
    _add_spec_directory(fingerprint_parser)
    fingerprint_parser.set_defaults(run=_fingerprint)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``bloomery`` console script.

    Returns the exit code rather than calling ``sys.exit``, so a test can
    invoke it as a function and read the code — which is the only way the
    refusal-vs-usage split gets tested rather than asserted.
    """
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        exit_code: int = arguments.run(arguments)
    except BloomeryError as error:
        # A refusal, not a crash: bloomery read the spec and said no.
        #
        # The source path is prepended here because a *single* error carries it
        # as an attribute and not in its message — only the batched aggregate
        # renders paths inline (RFC 0002 D6). Printing the message alone turns
        # "the type string is wrong" into a sentence with no file, no key and
        # nothing to act on, which is the one thing RFC 0002 §5.3 exists to
        # prevent.
        location = f"{error.source_path}: " if error.source_path else ""
        sys.stderr.write(f"{location}{error}\n")
        return EXIT_REFUSED
    except (io.CliIoError, _Usage) as error:
        sys.stderr.write(f"{parser.prog}: {error}\n")
        return EXIT_USAGE
    return exit_code


def _run() -> None:  # pragma: no cover — console-script shim
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    _run()
