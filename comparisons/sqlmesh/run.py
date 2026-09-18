"""Drive a standalone SQLMesh against one semantic-corpus case.

No bloomery import, on purpose: the column measures what SQLMesh does for a
SQLMesh user, so the project is authored as `MODEL (...)` and `METRIC (...)`
DDL the way its documentation describes and the only thing borrowed from this
repository is the case's data.

    python comparisons/sqlmesh/run.py <case-dir> <bundle-dir> \
        [--probe <ddl-name>.<key>=<value>] <metric>...

Prints what `sqlmesh info` and `sqlmesh plan` made of the project, what
`sqlmesh audit` did with the audits it declares, the SQL `sqlmesh rewrite`
renders for each metric named on the command line, the number that SQL returns
against the case's rows, and — where a bundle asks for one — what SQLMesh's
loader does with an invented key on one of its DDL blocks.

The project is copied to a scratch directory before anything runs, because
SQLMesh writes `.cache/` and `logs/` beside the configuration it is pointed at
and a bundle is evidence rather than a working directory. The rendered SQL is
executed against the same DuckDB file directly rather than through `sqlmesh
fetchdf`, which prints through pandas and reformats a `DECIMAL` into a float.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import duckdb

SQLMESH = pathlib.Path(sys.executable).parent / "sqlmesh"

#: The scratch directory the project is copied to, so a refusal that quotes the
#: file it refused is recorded as evidence rather than as one run's temp path.
SCRATCH = "<scratch>"

#: SQLMesh's last word on a run, or its first error.
_VERDICT = re.compile(
    r"^\s*((?:Virtual layer updated|Models: |Found \d+ audit|Error: |.*Error:).*)$", re.MULTILINE
)


def load(case: pathlib.Path, database: pathlib.Path) -> None:
    """The case's own schema and rows, into the file the gateway points at."""

    con = duckdb.connect(str(database))
    con.execute("CREATE SCHEMA bronze")
    con.execute((case / "schema" / "schema.sql").read_text(encoding="utf-8"))
    con.execute((case / "data" / "rows.sql").read_text(encoding="utf-8"))
    con.close()


def sqlmesh(*args: str, project: pathlib.Path, env: dict[str, str]) -> str:
    """One `sqlmesh` invocation, its output returned whatever the exit status.

    A refusal is the measurement, so a non-zero exit is recorded rather than
    raised, and stderr is kept because that is where a refusal is printed.
    """

    result = subprocess.run(
        [str(SQLMESH), "-p", str(project), *args],
        capture_output=True,
        text=True,
        env=env,
    )
    output = (result.stdout + result.stderr).replace(str(project.parent), SCRATCH)
    return "\n".join(line.rstrip() for line in output.splitlines())


def verdict(output: str) -> str:
    """The decisive line of a run: what SQLMesh finished with, or refused on."""

    lines = [match.group(1).strip() for match in _VERDICT.finditer(output)]
    if lines:
        return lines[-1] if "rror" not in lines[-1] else f"{lines[-1]}: {_detail(output, lines[-1])}"
    body = [line.strip() for line in output.splitlines() if line.strip()]
    return body[-1] if body else "(no output)"


def _detail(output: str, last: str) -> str:
    """An error's decisive sentences, which SQLMesh prints on following lines.

    Pydantic prints the refused key and the reason on two lines below the
    count, and a documentation URL below those — which is not evidence and is
    where the quotation stops.
    """

    rest = output.split(last, 1)[-1].splitlines()
    detail = (line.strip() for line in rest if line.strip())
    return " ".join(
        line for line, _ in zip(detail, range(2), strict=False) if "errors.pydantic.dev" not in line
    )


def probe(project: pathlib.Path, spec: str) -> None:
    """Add one invented key to a named DDL block, in place.

    `<ddl-name>.<key>=<value>`, so `average_item_price_naive.already_aggregated=true`
    asks SQLMesh what it does with a metric key stating that a column is already
    an aggregate. What comes back is the difference between "no key was found"
    and "the vocabulary has no slot".
    """

    path, _, value = spec.partition("=")
    name, _, key = path.rpartition(".")

    edited = next(
        file
        for file in sorted(project.rglob("*.sql"))
        if re.search(rf"^\s*name {re.escape(name)}\s*,", file.read_text("utf-8"), re.MULTILINE)
    )
    edited.write_text(
        re.sub(
            rf"^(\s*)name {re.escape(name)}\s*,",
            rf"\1name {name},\n\1{key} {value},",
            edited.read_text(encoding="utf-8"),
            count=1,
            flags=re.MULTILINE,
        ),
        encoding="utf-8",
    )


def main() -> int:
    case, bundle = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    rest, probes, metrics = iter(sys.argv[3:]), [], []
    for arg in rest:
        (probes if arg == "--probe" else metrics).append(next(rest) if arg == "--probe" else arg)

    with tempfile.TemporaryDirectory() as tmp:
        scratch = pathlib.Path(tmp)
        database = scratch / "case.duckdb"
        load(case, database)
        project = scratch / "project"
        shutil.copytree(bundle / "config", project)
        env = {
            **os.environ,
            "CORPUS_DUCKDB": str(database),
            # Otherwise every rendered query is wrapped at the terminal width
            # this happened to run under.
            "COLUMNS": "200",
        }

        print("### sqlmesh info")
        print(f"  {verdict(sqlmesh('info', project=project, env=env))}")

        planned = sqlmesh("plan", "--auto-apply", "--no-prompts", project=project, env=env)
        print("### sqlmesh plan --auto-apply --no-prompts")
        for line in planned.splitlines():
            if "audits failed" in line or "audit warning" in line:
                print(f"  {line.strip()}")
        print(f"  {verdict(planned)}")

        audited = sqlmesh("audit", project=project, env=env)
        print("### sqlmesh audit")
        for line in audited.splitlines():
            if "audit(s)" in line or "FAIL" in line or "audit error" in line:
                print(f"  {line.strip()}")

        con = duckdb.connect(str(database), read_only=True)
        for metric in metrics:
            rendered = sqlmesh(
                "rewrite",
                f"SELECT METRIC({metric}) FROM __semantic.__table",
                project=project,
                env=env,
            )
            print(f"### sqlmesh rewrite metric:{metric}")
            for line in rendered.splitlines():
                print(f"  {line}")
            print(f"### metric {metric}")
            try:
                print(f"  -> {con.execute(rendered).fetchall()}")
            except Exception as exc:  # the refusal is the measurement
                print(f"  refused: {type(exc).__name__}: {exc}")
        con.close()

        for spec in probes:
            copy = scratch / "probe"
            shutil.rmtree(copy, ignore_errors=True)
            shutil.copytree(bundle / "config", copy)
            probe(copy, spec)
            print(f"### probe {spec}")
            print(f"  {verdict(sqlmesh('info', project=copy, env=env))}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
