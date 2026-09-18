"""Drive a standalone dbt Core against one semantic-corpus case.

No bloomery import, on purpose: the column measures what dbt Core does for a
dbt user, so the project is authored as YAML and SQL the way its documentation
describes and the only thing borrowed from this repository is the case's data.

    python comparisons/dbt/run.py <case-dir> <bundle-dir> [--probe <path>=<value>] <model>...

Prints what `dbt build` made of the project, what `dbt compile` renders for each
metric the project declares, the number each model returns against the case's
rows, and — where a bundle asks for one — what dbt's parser does with an
invented key on the first semantic model.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

import duckdb
import yaml

DBT = pathlib.Path(sys.executable).parent / "dbt"

#: dbt prints one summary line per run; these are the decisive ones.
_FOUND = re.compile(r"^.*(Found .*)$", re.MULTILINE)
_VERDICT = re.compile(r"^.*((?:Done\. PASS=|Nothing to do|Parsing Error|Compilation Error).*)$")


def load(case: pathlib.Path, database: pathlib.Path) -> None:
    """The case's own schema and rows, into the file the profile points at."""

    con = duckdb.connect(str(database))
    con.execute("CREATE SCHEMA bronze")
    con.execute((case / "schema" / "schema.sql").read_text(encoding="utf-8"))
    con.execute((case / "data" / "rows.sql").read_text(encoding="utf-8"))
    con.close()


def dbt(*args: str, project: pathlib.Path, env: dict[str, str], scratch: pathlib.Path) -> str:
    """One dbt invocation, its stdout returned whatever the exit status.

    A refusal is the measurement, so a non-zero exit is recorded rather than
    raised.
    """

    result = subprocess.run(
        [
            str(DBT),
            *args,
            "--no-use-colors",
            "--project-dir",
            str(project),
            "--profiles-dir",
            str(project),
            "--target-path",
            str(scratch / "target"),
            "--log-path",
            str(scratch / "logs"),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    # dbt logs to stdout; what reaches stderr is the failure that happened before
    # logging existed, and that is the one a reader most needs to see.
    return result.stdout + result.stderr


def verdict(output: str) -> str:
    """dbt's own last word on a run, or its first error."""

    lines = output.splitlines()
    for index, line in enumerate(lines):
        match = _VERDICT.match(line)
        if not match:
            continue
        if not match.group(1).endswith("Error"):
            return match.group(1)
        # An error's decisive sentence is on a following line, and a schema
        # refusal prints the whole rejected block before it.
        detail = next((text.strip() for text in lines[index + 1 :] if text.strip()), "")
        _, marker, tail = detail.partition("at path ")
        return f"{match.group(1)}: {marker + tail if marker else detail}"
    return output.strip().splitlines()[-1] if output.strip() else "(no output)"


def probe(bundle: pathlib.Path, spec: str, env: dict[str, str], scratch: pathlib.Path) -> str:
    """Parse a copy of the project carrying one invented key.

    `<dotted-path>=<value>`, from the root of the semantic YAML document — so
    `semantic_models.0.measures.0.already_aggregated=true` asks dbt what it does
    with a measure key stating that a column is already an aggregate. What comes
    back is the difference between "no key was found" and "the vocabulary has no
    slot".
    """

    path, _, value = spec.partition("=")
    copy = pathlib.Path(tempfile.mkdtemp(prefix="probe-", dir=scratch))
    for source in sorted((bundle / "config").rglob("*")):
        target = copy / source.relative_to(bundle / "config")
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            target.write_bytes(source.read_bytes())

    edited = next(p for p in copy.rglob("*.yml") if "semantic_models" in p.read_text("utf-8"))
    node = document = yaml.safe_load(edited.read_text(encoding="utf-8"))
    *steps, key = path.split(".")
    for step in steps:
        node = node[int(step)] if step.isdigit() else node[step]
    node[key] = yaml.safe_load(value)
    edited.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    run_dir = copy.with_name(copy.name + "-run")
    return verdict(dbt("parse", "--no-partial-parse", project=copy, env=env, scratch=run_dir))


def main() -> int:
    case, bundle = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    rest, probes, models = iter(sys.argv[3:]), [], []
    for arg in rest:
        (probes if arg == "--probe" else models).append(next(rest) if arg == "--probe" else arg)

    with tempfile.TemporaryDirectory() as tmp:
        scratch = pathlib.Path(tmp)
        database = scratch / "case.duckdb"
        load(case, database)
        project = bundle / "config"
        env = {
            **os.environ,
            "CORPUS_DUCKDB": str(database),
            # Otherwise dbt drops a `.user.yml` with a fresh id beside the
            # profile, inside the bundle.
            "DBT_SEND_ANONYMOUS_USAGE_STATS": "False",
        }

        built = dbt("build", project=project, env=env, scratch=scratch)
        found = _FOUND.search(built)
        print("### dbt build")
        print(f"  {found.group(1) if found else '(no summary)'}")
        print(f"  {verdict(built)}")

        listed = dbt(
            "list", "--resource-type", "metric", project=project, env=env, scratch=scratch
        )
        declared = (line.split(".")[-1] for line in listed.splitlines() if "metric:" in line)
        for metric in sorted(declared):
            compiled = dbt(
                "compile", "--select", f"metric:{metric}", project=project, env=env, scratch=scratch
            )
            print(f"### dbt compile --select metric:{metric}")
            print(f"  {verdict(compiled)}")

        con = duckdb.connect(str(database), read_only=True)
        for model in models:
            print(f"### model {model}")
            try:
                print(f"  -> {con.execute(f'SELECT * FROM bronze.{model}').fetchall()}")
            except Exception as exc:  # the refusal is the measurement
                print(f"  refused: {type(exc).__name__}: {exc}")
        con.close()

        for spec in probes:
            print(f"### probe {spec}")
            print(f"  {probe(bundle, spec, env, scratch)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
