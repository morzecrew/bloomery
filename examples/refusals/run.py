"""Six specs that look right and cannot be right, and the refusals they get.

    uv run python examples/refusals/run.py

No infrastructure: every case here is decided at compile time, which is the
point. Four of them would produce a *wrong number* in a hand-written project —
one that runs, returns rows, and is silently inflated. The other two would
produce SQL that no engine can execute.

Each case is a complete, tiny project under `cases/`. Read the YAML, then read
what bloomery says about it. Every message names the reason and the fix; if one
ever stops doing that, it is a defect in the message rather than a detail of
this example.

A case that *compiles* fails the run. An example claiming a refusal that no
longer happens is worse than no example, so the runner refuses to be quietly
wrong about its own subject.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from bloomery import Target, compile_project, load_catalog, load_project
from bloomery.errors import BloomeryError

HERE = Path(__file__).parent
CASES = HERE / "cases"

#: The module docstring minus its usage line — printed as the runner's preamble
#: so the file and the output say the same thing exactly once.
INTRO = (__doc__ or "").split("\n\n", 2)[2].strip()

#: (directory, headline, what a hand-written project would have done instead).
#: Order is narrative: the wrong numbers first, then the things that cannot run.
CASE_NOTES: tuple[tuple[str, str, str], ...] = (
    (
        "scd2-flatten",
        "Flattening a dimension that keeps history",
        "Every order joins every *version* of its customer. Revenue is "
        "multiplied by each customer's revision count, and every guardrail "
        "that reads the declared cardinality stays green — because "
        "many_to_one is a true claim about the domain and a false one about "
        "the table.",
    ),
    (
        "wrong-grain",
        "An order-grain measure on a line-grain mart",
        "Shipping is charged once per order and duplicated once per line. "
        "SUM(shipping) overstates by the line count — the defect bloomery's "
        "introduction opens on.",
    ),
    (
        "fanout",
        "Flattening across a one_to_many relationship",
        "The mart's own rows multiply once per matched row on the far side. "
        "Same failure as the first case, reached through the relationship "
        "rather than through history.",
    ),
    (
        "mixed-currency",
        "Adding EUR to USD",
        "A number that is the sum of two different things. It typechecks — "
        "both sides are decimal(12,2) — and nothing about the arithmetic is "
        "malformed.",
    ),
    (
        "unimplemented-convert",
        "A transform with no lowering anywhere",
        "`convert` typechecks decimal -> decimal and passes every guardrail, "
        "then emits a CONVERT_CURRENCY(...) call that exists in no engine. "
        "Refused at emit rather than shipped as SQL that fails at run time.",
    ),
    (
        "merged-on-dbt",
        "A union merge, compiled for dbt",
        "This one is not wrong — it is unsupported, and the distinction "
        "matters. It compiles for SQLMesh. dbt has no artifact for the "
        "blocking collision audit the merge needs, and a merge without that "
        "check double-counts in silence, so the target says so instead.",
    ),
)


def refuse(case: str) -> tuple[str, str]:
    """Compile one case and return (error class, message). Compiling cleanly is
    itself a failure here: the example would be claiming a refusal that no
    longer happens."""
    directory = CASES / case
    # A `.dbt` marker picks the target, because one case is about the target
    # rather than about the specs.
    target = Target.DBT if (directory / ".dbt").exists() else Target.SQLMESH
    catalog_path = directory / "catalog.yaml"
    catalog = load_catalog(catalog_path.read_text()) if catalog_path.exists() else None
    documents = {
        path.name: path.read_text()
        for path in sorted(directory.glob("*.yaml"))
        if path.name != "catalog.yaml"
    }
    try:
        compile_project(
            load_project(documents), target=target, dialect="duckdb", catalog=catalog
        )
    except BloomeryError as refusal:
        return type(refusal).__name__, str(refusal)
    message = f"{case} compiled — the refusal this case exists to show did not happen"
    raise SystemExit(message)


def main() -> None:
    print(INTRO)
    for case, headline, would_have in CASE_NOTES:
        print(f"\n{'─' * 78}\n{headline}  ({case}/)\n")
        wrapped = textwrap.fill(
            would_have, width=76, initial_indent="  ", subsequent_indent="  "
        )
        print(f"  Without the refusal —\n{wrapped}\n")
        error, message = refuse(case)
        target = " for dbt" if (CASES / case / ".dbt").exists() else ""
        print(f"  $ bloomery compile{target}")
        print(f"  {error}:")
        for line in message.splitlines():
            print(
                textwrap.fill(
                    line.strip(), width=76, initial_indent="    ", subsequent_indent="      "
                )
            )
    print(f"\n{'─' * 78}")
    print(f"{len(CASE_NOTES)} specs, {len(CASE_NOTES)} refusals, no warehouse touched.")


if __name__ == "__main__":
    main()
