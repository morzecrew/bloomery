"""Cross-process determinism replay (S-0009/D-2).

An ordinary script: no instrumentation, no libFuzzer, no atheris. It compiles
every corpus entry in separate processes under different ``PYTHONHASHSEED``
values and diffs the artifacts byte for byte, across all three emit targets
and all three dialects, and it compiles the corpus a third time in the
opposite order to assert that artifact ordering does not depend on compile
order.

``tests/unit/test_determinism_guard.py`` is the one-fixture version of the
same claim (S-0020: same specs in ⇒ byte-identical artifacts out, across
processes and hash seeds). This is that claim at corpus scale.

The corpus needs no fuzzing to exist: on day one it is the example projects
and the spec fixtures behind the golden tier (S-0009/D-7 — the seeds are
derived from ``examples/**`` and ``tests/golden/**`` rather than committed a
second time). Whatever a fuzzing job later leaves under ``fuzz/corpus/`` is
picked up as well, each blob spliced into the valid fixture set the fuzz
targets mutate.

Run it::

    $ uv run python fuzz/replay.py
    $ uv run python fuzz/replay.py --list
    $ uv run python fuzz/replay.py --root tests/fixtures/minimal

METRICFLOW is deliberately absent from the target list: it emits a manifest
rather than models, and its bytes already ride the named guard's hash-seed
pair.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FUZZ_FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: The day-one corpus: the example projects, and the spec documents the golden
#: tier compiles (the goldens themselves are outputs — their inputs live in
#: ``tests/fixtures/``, which is what a golden fixture name resolves to).
DEFAULT_ROOTS = (REPO_ROOT / "examples", REPO_ROOT / "tests" / "fixtures")

#: Where a fuzzing job leaves what it found worth keeping. Absent until one
#: runs, which is why nothing here requires it.
DEFAULT_CORPUS_ROOTS = (REPO_ROOT / "fuzz" / "corpus",)

#: A directory is a project when it carries an entity model; that is the one
#: document no bloomery project is without.
MARKER = "entity_model.yaml"
CATALOG = "catalog.yaml"

TARGETS = ("sqlmesh", "cube", "dbt")
DIALECTS = ("duckdb", "postgres", "trino")

#: The deliberately broken twin (S-0002/D-2, ratchet-what-you-build): a check
#: never observed to fail is indistinguishable from one that never fires.
#: ``seed`` perturbs a compile under a non-zero hash seed, ``order`` perturbs
#: one under the reversed compile order; both must turn this script red.
#: ``tests/unit/test_fuzz_replay.py`` asserts each colour.
SABOTAGE = "BLOOMERY_REPLAY_SABOTAGE"


@dataclass(frozen=True)
class Entry:
    """One corpus entry: a project directory, or a fuzz corpus blob spliced
    into the fixture set the targets mutate one document of."""

    kind: str  # "project" or "blob"
    path: str

    @property
    def name(self) -> str:
        """Repo-relative where it can be — a key a reader can find — and the
        absolute path otherwise, since a root outside the tree is legal."""
        path = Path(self.path)
        return str(path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path)


# ....................... #


def discover(roots: tuple[Path, ...], corpus_roots: tuple[Path, ...]) -> list[Entry]:
    """Every project directory under `roots`, then every blob under
    `corpus_roots`. Sorted, because the reversed run below is only meaningful
    against an order that is itself stable."""
    entries = [
        Entry("project", str(marker.parent))
        for root in roots
        if root.exists()
        for marker in sorted(root.rglob(MARKER))
    ]
    entries += [
        Entry("blob", str(blob))
        for root in corpus_roots
        if root.exists()
        for blob in sorted(blob for blob in root.rglob("*") if blob.is_file())
    ]
    return sorted(entries, key=lambda entry: (entry.kind, entry.path))


def read_entry(entry: Entry) -> tuple[dict[str, str], str | None]:
    """The entry's project documents and its catalog text, if it has one."""
    if entry.kind == "project":
        directory = Path(entry.path)
        sources = {
            path.stem: path.read_text(encoding="utf-8", errors="replace")
            for path in sorted(directory.glob("*.yaml"))
            if path.name != CATALOG
        }
        catalog_path = directory / CATALOG
        catalog = catalog_path.read_text() if catalog_path.exists() else None
        return sources, catalog

    # A blob is raw fuzzer bytes. The slot it replaces is the trailing byte,
    # which is the seed layout `fuzz/_harness.fuzzed_sources` documents —
    # spelled out here rather than reused, because reconstructing it exactly
    # would mean importing atheris into a script that deliberately has no
    # instrumentation. Replay is about two processes agreeing, so which valid
    # document the blob displaces matters less than that both agree on it.
    data = Path(entry.path).read_bytes()
    sources = {
        path.stem: path.read_text()
        for path in sorted(FUZZ_FIXTURES.glob("*.yaml"))
        if path.name != CATALOG
    }
    catalog = (FUZZ_FIXTURES / CATALOG).read_text()
    slots = sorted([*sources, Path(CATALOG).stem])
    slot = slots[data[-1] % len(slots)] if data else slots[0]
    document = data[:-1].decode("utf-8", "replace")
    if slot == Path(CATALOG).stem:
        return sources, document
    sources[slot] = document
    return sources, catalog


def compile_entries(
    entries: list[Entry], *, reverse: bool, sabotage: str | None
) -> dict[str, list[list[str]]]:
    """Compile every entry to every target and dialect, in the order given.

    A refusal is an outcome like any other and is recorded as one: a message
    that varies across hash seeds is the same defect as an artifact that does.
    `BloomeryError` and nothing else is caught, which is the expectation
    `fuzz/_harness.py` states for the whole lane (S-0008/D-1).
    """
    from bloomery import Target, compile_project, load_catalog, load_project
    from bloomery.errors import BloomeryError

    perturb_seed = sabotage == "seed" and os.environ.get("PYTHONHASHSEED") not in (None, "0")
    results: dict[str, list[list[str]]] = {}

    for entry in entries:
        sources, catalog_text = read_entry(entry)
        for target in TARGETS:
            for dialect in DIALECTS:
                key = f"{entry.name}|{target}|{dialect}"
                try:
                    catalog = load_catalog(catalog_text) if catalog_text is not None else None
                    artifacts = compile_project(
                        load_project(sources),
                        target=Target(target),
                        dialect=dialect,
                        catalog=catalog,
                    )
                except BloomeryError as exc:
                    results[key] = [["refused", type(exc).__name__, str(exc)]]
                    continue
                rows = [[a.path, str(a.kind), a.checksum, a.content] for a in artifacts]
                if perturb_seed and rows:
                    rows[0][-1] += "-- sabotage\n"
                results[key] = rows

    if sabotage == "order" and reverse:
        results = {key: list(reversed(rows)) for key, rows in results.items()}

    return results


# ....................... #


def _run(entries: list[Entry], *, seed: str, reverse: bool) -> dict[str, list[list[str]]]:
    """One compile of the whole corpus, in its own process under `seed`."""
    plan = [[entry.kind, entry.path] for entry in entries]
    if reverse:
        plan.reverse()
    env = {**os.environ, "PYTHONHASHSEED": seed}
    process = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--compile", *(["--reverse"] if reverse else [])],
        input=json.dumps(plan),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=REPO_ROOT,
    )
    if process.returncode != 0:
        raise SystemExit(f"replay worker failed under PYTHONHASHSEED={seed}:\n{process.stderr}")
    return json.loads(process.stdout)


def _report(label: str, left: dict[str, list[list[str]]], right: dict[str, list[list[str]]]) -> int:
    """Print what differs between two runs. Returns the number of differing
    entries — the artifacts are compared by their full content, so "differs"
    means differing bytes, not a differing summary."""
    differing = 0
    for key in sorted(set(left) | set(right)):
        if left.get(key) == right.get(key):
            continue
        differing += 1
        print(f"{label}: {key} differs")
        diff = difflib.unified_diff(
            json.dumps(left.get(key), indent=2).splitlines(),
            json.dumps(right.get(key), indent=2).splitlines(),
            lineterm="",
            n=1,
        )
        # Bounded in both directions: an artifact is a whole file, and a
        # determinism report that prints two of them per cell is one nobody
        # reads. The corpus entry is named above; the bytes are one rerun away.
        for line in list(diff)[:40]:
            print(f"  {line[:200]}")
    return differing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", type=Path, help="a project-corpus root")
    parser.add_argument("--corpus", action="append", type=Path, help="a fuzz-corpus root")
    parser.add_argument("--seed", action="append", help="a PYTHONHASHSEED value (default 0, 1)")
    parser.add_argument("--list", action="store_true", help="print the corpus and stop")
    parser.add_argument("--compile", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--reverse", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.compile:
        plan = [Entry(kind, path) for kind, path in json.loads(sys.stdin.read())]
        results = compile_entries(
            plan, reverse=args.reverse, sabotage=os.environ.get(SABOTAGE)
        )
        print(json.dumps(results))
        return 0

    roots = tuple(args.root) if args.root else DEFAULT_ROOTS
    corpus_roots = tuple(args.corpus) if args.corpus else DEFAULT_CORPUS_ROOTS
    seeds = args.seed if args.seed else ["0", "1"]

    entries = discover(roots, corpus_roots)
    if args.list:
        for entry in entries:
            print(f"{entry.kind}\t{entry.name}")
        return 0

    # An empty corpus passes every comparison below and proves nothing, which
    # is the one outcome indistinguishable from a determinism claim that holds.
    if not entries:
        print("replay: no corpus entries found", file=sys.stderr)
        return 1

    # One seed answers the order question only, and the success line below
    # claims both: a run that cannot compare across hash seeds must not say
    # it did. The same vacuity as the empty corpus, refused the same way.
    if len(seeds) < 2:
        print("replay: at least two --seed values are needed to compare across hash seeds", file=sys.stderr)
        return 1

    print(f"replay: {len(entries)} entries x {len(TARGETS)} targets x {len(DIALECTS)} dialects")

    reference = _run(entries, seed=seeds[0], reverse=False)
    differing = 0
    for seed in seeds[1:]:
        differing += _report(
            f"PYTHONHASHSEED {seeds[0]} vs {seed}", reference, _run(entries, seed=seed, reverse=False)
        )
    differing += _report(
        "compile order", reference, _run(entries, seed=seeds[0], reverse=True)
    )

    if differing:
        print(f"replay: {differing} differing entries", file=sys.stderr)
        return 1

    print(f"replay: {len(reference)} compiles identical across processes, seeds and order")
    return 0


if __name__ == "__main__":  # pragma: no cover - the script entry point
    raise SystemExit(main())
