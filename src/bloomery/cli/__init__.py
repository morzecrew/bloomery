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
import difflib
import json
import sys
from typing import TYPE_CHECKING, cast

from bloomery import (
    BloomeryError,
    Direction,
    Graph,
    LruManifestHydrator,
    MetricFlowPlanner,
    MetricRequest,
    Node,
    Op,
    RowPolicy,
    SpecKind,
    Stage,
    Target,
    TimeGrain,
    __version__,
    all_spec_schemas,
    build_project_ir,
    compile_project,
    evaluate,
    lineage,
    load_catalog,
    load_project,
    plan,
    project_fingerprint,
    resolve,
    spec_json_schema,
)
from bloomery.cli import io, render, serialize
from bloomery.dialects import get_dialect
from bloomery.emit import get_emitter
from bloomery.errors import EmitError, UnknownMember
from bloomery.naming import DefaultNaming
from bloomery.planner import parse_filter_json

if TYPE_CHECKING:
    from collections.abc import Mapping as AbcMapping
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


def _load(directory: str, catalog_path: str | None) -> tuple[Project, Catalog | None]:
    """The two values every command starts from.

    Takes the two strings rather than the parsed namespace: ``plan`` loads two
    directories against one catalog and would otherwise have to fake a
    namespace, and a command whose parser forgot ``--catalog`` fails at the
    call site instead of silently loading without one.
    """
    sources, catalog_text = io.read_spec_directory(directory, catalog=catalog_path)
    catalog = load_catalog(catalog_text) if catalog_text is not None else None
    return load_project(sources), catalog


def _load_ir(directory: str, catalog_path: str | None) -> ProjectIR:
    project, catalog = _load(directory, catalog_path)
    return build_project_ir(project, catalog=catalog)


def _emit(payload: object, *, as_json: bool) -> None:
    """One place that writes to stdout, so every command agrees on the shape.

    JSON is indented and sorted: a CLI's JSON is read by people at least as
    often as by programs, and a sorted document diffs.
    """
    text = (
        json.dumps(payload, indent=2, sort_keys=True, cls=serialize.SpecEncoder)
        if as_json
        else str(payload)
    )
    sys.stdout.write(text + "\n")


# ....................... #
# Commands


def _check_names(*, target: str | None = None, dialect: str | None = None) -> None:
    """Refuse a mistyped ``--target``/``--dialect`` as a usage error.

    Both resolve through the library, which raises :class:`EmitError` — so
    without this a typo came back as ``1``, the code that means "bloomery read
    your spec and said no", for a spec it never opened. A mistyped flag *value*
    is the invocation being wrong, which is what ``2`` is for, and it is the
    treatment ``--grain`` and ``--policy`` already get here.

    The registries are asked rather than a list written down: the target set is
    open (:func:`~bloomery.register_emitter`), so the library is the only thing
    that knows it, and its message already names what it does have.
    """
    try:
        if target is not None:
            get_emitter(target)
        if dialect is not None:
            get_dialect(dialect)
    except EmitError as exc:
        raise _Usage(str(exc)) from exc


def _compile(arguments: argparse.Namespace) -> int:
    _check_names(target=arguments.target, dialect=arguments.dialect)
    project, catalog = _load(arguments.directory, arguments.catalog)
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
    _emit(artifacts, as_json=True)
    return EXIT_OK


def _plan(arguments: argparse.Namespace) -> int:
    old = _load_ir(arguments.old, arguments.catalog)
    new = _load_ir(arguments.new, arguments.catalog)
    result = plan(old, new)
    if arguments.format == "json":
        _emit(result, as_json=True)
    else:
        _emit(render.render_plan(result), as_json=False)
    return EXIT_OK


def _resolve(arguments: argparse.Namespace) -> int:
    """``bloomery resolve`` — reachability *and* refusals (RFC 0022 D8).

    Re-pointed from :func:`~bloomery.resolve` to :func:`~bloomery.evaluate`,
    which is a strict gain for the one caller who matters here: a spec author
    mid-draft. Before, a spec that refused anywhere printed nothing and exited
    ``1`` with a message; now it prints how far analysis got, what was
    reachable at that point, and every refusal with its source path — and still
    exits ``1``, because the spec is still refused and a pipeline branching on
    the code must not start treating it as fine.

    **One project shape changes answer**: a spec wiring a ``steps:`` document
    now reports the unwired step instead of printing reachability. No registry
    is passed — the CLI offers no ``--steps``, because a ``StepRegistry`` is a
    caller-assembled compile input (RFC 0017 §5.3) — and ``resolve()`` never
    looked at steps at all, so it answered as though the wiring were not there.
    ``compile`` on the same project already refuses for the same reason; this
    makes the two agree rather than having the cheaper command quietly answer a
    question about a project the expensive one will not build.
    """
    project, catalog = _load(arguments.directory, arguments.catalog)
    evidence = evaluate(project, catalog=catalog)
    if arguments.format == "json":
        _emit(evidence, as_json=True)
    else:
        _emit(render.render_evidence(evidence), as_json=False)
    return EXIT_OK if evidence.stage_reached is Stage.COMPLETE else EXIT_REFUSED


def _lineage(arguments: argparse.Namespace) -> int:
    """``bloomery lineage`` — where a node comes from, or what it feeds.

    Reads the graph off the `Resolution` rather than rebuilding it (RFC 0031
    D2), so the answer describes the same graph the reachability report did.
    """
    project, catalog = _load(arguments.directory, arguments.catalog)
    resolution = resolve(project, catalog)
    root = _find_node(resolution.graph, arguments.node)
    walk = lineage(
        resolution.graph,
        root,
        Direction(arguments.direction),
        max_depth=arguments.max_depth,
    )
    if arguments.format == "json":
        _emit(walk, as_json=True)
    else:
        _emit(render.render_lineage(walk), as_json=False)
    return EXIT_OK


def _find_node(graph: Graph, wanted: str) -> Node:
    """The node named ``wanted``, or a refusal that helps the reader retype it.

    Node ids are long, dotted and easy to mistype, and the graph holding the
    right spelling is already in hand — so "not found" alone would be withholding
    the answer (RFC 0031 §5.5). Suggestions come from ``difflib`` at a fixed
    cutoff and are capped, which keeps the message both useful and *bounded*: a
    two-thousand-node graph must not print two thousand guesses, and the same
    spec must print the same bytes (RFC 0003). See ``logs/T-0006.md`` D-028.

    Where nothing is close enough, the fallback names the id *kinds* present.
    A reader who mistyped the scheme rather than the name learns the scheme —
    entity fields carry no prefix, everything else does.

    **An id can name two nodes**, and that is refused rather than resolved by
    picking. Entity-field ids carry no kind prefix, so an entity named
    ``metric`` with a field ``revenue`` produces ``metric.revenue`` and so does
    a metric named ``revenue``; the graph holds both, and this function is
    handed one string. Returning the first would walk one of two lineages with
    nothing in the output saying which — a silently wrong answer to a question
    that has two right ones. The refusal names both kinds, so a reader learns
    what their project collided rather than that their spelling was wrong.
    """
    matches = [node for node in graph.nodes if node.name == wanted]
    if len(matches) == 1:
        return matches[0]
    if matches:
        collided = ", ".join(sorted(node.kind.value for node in matches))
        msg = (
            f"{wanted!r} names {len(matches)} nodes in this project's dependency graph,"
            f" of kinds {collided}. An entity field is spelled '<entity>.<field>' with no"
            " kind prefix, so its id can collide with another kind's — rename the"
            " entity, the field, or whatever it collided with to walk this lineage"
        )
        raise UnknownMember(msg)
    names = [node.name for node in graph.nodes]
    close = difflib.get_close_matches(wanted, names, n=5, cutoff=0.6)
    kinds = sorted({node.kind.value for node in graph.nodes})
    if close:
        hint = "did you mean: " + ", ".join(close)
    elif not kinds:
        # A draft spec — an entity model with no mappings loads, resolves, and
        # has no nodes at all. Joining an empty kind list printed "of kinds  —",
        # which reads as a bug in bloomery rather than a fact about the project.
        hint = (
            "this project's dependency graph is empty — nothing maps a source"
            " into an entity yet, so there is no lineage to walk"
        )
    else:
        hint = (
            f"this project has no node by that name; its ids are of kinds {', '.join(kinds)}"
            " — an entity field is spelled '<entity>.<field>' with no prefix, and every"
            " other kind carries one"
        )
    msg = f"no node named {wanted!r} in this project's dependency graph. {hint}"
    raise UnknownMember(msg)


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


def _parse_where(payload: str | None) -> AbcMapping[str, object] | None:
    """``--where`` as a filter document, or a usage error naming the problem.

    ``json.loads`` raises ``JSONDecodeError``, which nothing above catches — so
    without this a mistyped quote exits on a traceback rather than on the ``2``
    a script branches on. A well-formed JSON value that is not an object is the
    same kind of mistake and gets the same code.

    The refusals *inside* the document are a different thing and stay
    refusals: ``$regex`` is a reviewed decision (RFC 0015), not a typo.
    """
    if payload is None:
        return None
    try:
        document: object = json.loads(payload)
    except json.JSONDecodeError as exc:
        msg = f"--where is not valid JSON: {exc}"
        raise _Usage(msg) from exc
    if not isinstance(document, dict):
        msg = f"--where takes a JSON object, got {type(document).__name__}"
        raise _Usage(msg)
    return cast("AbcMapping[str, object]", document)


def _parse_grain(spelling: str | None) -> TimeGrain | None:
    """``--grain`` as a :class:`~bloomery.TimeGrain`, or a usage error listing
    the six. Not ``choices=`` on the parser, so the message can name the flag
    the same way the other value checks here do."""
    if spelling is None:
        return None
    try:
        return TimeGrain(spelling)
    except ValueError as exc:
        known = ", ".join(member.value for member in TimeGrain)
        msg = f"--grain {spelling!r} is not one of: {known}"
        raise _Usage(msg) from exc


def _explain(arguments: argparse.Namespace) -> int:
    # Every flag is checked before the project is loaded. Both orders are
    # correct and one is kinder: a mistyped `--grain` is free to detect, while
    # loading is the slow part, and when the spec is *also* broken the reader
    # needs the invocation fixed first — a refusal about a spec they cannot
    # reach yet is not the next thing they should do.
    _check_names(dialect=arguments.dialect)
    where = _parse_where(arguments.where)
    policy = _parse_policy(arguments.policy)
    request = MetricRequest(
        metrics=tuple(arguments.metrics.split(",")),
        dimensions=tuple(arguments.by.split(",")) if arguments.by else (),
        filters=parse_filter_json(where) if where is not None else (),
        time_grain=_parse_grain(arguments.grain),
        limit=arguments.limit,
    )
    ir = _load_ir(arguments.directory, arguments.catalog)
    naming = DefaultNaming()
    planner = MetricFlowPlanner(LruManifestHydrator(naming), naming=naming)
    query = planner.plan(ir, request, dialect=arguments.dialect, policy=policy)
    if arguments.format == "json":
        _emit(query, as_json=True)
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
    _emit(project_fingerprint(_load_ir(arguments.directory, arguments.catalog)), as_json=False)
    return EXIT_OK


# ....................... #
# Parser


def _depth(spelling: str) -> int:
    """``--max-depth`` as a non-negative int, refused by argparse if it is not.

    The library raises :class:`ValueError` for a negative depth, which is right
    for a Python caller and wrong to let reach a shell: ``main`` catches
    :class:`~bloomery.BloomeryError`, so a bare ``ValueError`` would escape as a
    traceback — neither the ``1`` that means the spec was refused nor the ``2``
    that means the invocation was wrong. Validating here makes it the second,
    which is what a bad flag *value* is, exactly as ``--direction up`` already is.
    """
    try:
        depth = int(spelling)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--max-depth must be an integer, got {spelling!r}"
        ) from None
    if depth < 0:
        msg = f"--max-depth must be >= 0, got {depth}"
        raise argparse.ArgumentTypeError(msg)
    return depth


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
    # Not a command — a flag, so it needs no subcommand to reach. The bug
    # report template asks for a bloomery version, and until this existed the
    # only way to answer was to know the package name well enough to query the
    # installed metadata by hand.
    parser.add_argument(
        "--version",
        action="version",
        version=f"bloomery {__version__}",
        help="print the installed bloomery version and exit",
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

    lineage_parser = commands.add_parser(
        "lineage", help="where a node comes from, or what a change to it would reach"
    )
    _add_spec_directory(lineage_parser)
    lineage_parser.add_argument(
        "--node",
        required=True,
        help="node id, e.g. metric.gross_revenue or order_item.unit_price",
    )
    lineage_parser.add_argument(
        "--direction",
        choices=tuple(d.value for d in Direction),
        default=Direction.UPSTREAM.value,
        help=(
            "upstream: what it is built from; downstream: what it feeds;"
            " both: the two walks merged into one sub-DAG"
        ),
    )
    lineage_parser.add_argument(
        "--max-depth",
        type=_depth,
        help="stop the walk this many edges from the node (0 is the node alone)",
    )
    _add_format(lineage_parser)
    lineage_parser.set_defaults(run=_lineage)

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

    That promise covers argparse's own refusals too. ``parse_args`` writes its
    message and *raises* ``SystemExit``, so an unparseable flag value —
    ``--limit notanint`` — escaped this function instead of coming back as a
    number. The shell saw the right code either way; a caller using ``main`` as
    a function, which the paragraph above invites, did not.
    """
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as request:
        # argparse exits 2 for a usage error and 0 for `--help`; both are
        # already the code this function means to return, so pass them through
        # rather than flattening them to one.
        return request.code if isinstance(request.code, int) else EXIT_USAGE
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
