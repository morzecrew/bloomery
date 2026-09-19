"""Seed generation for the fuzz lane (S-0009/D-7).

The seeds are the example projects and the golden tier's spec documents,
copied into each target's seed directory at build time rather than committed a
second time under `fuzz/`. The corpus floor then tracks the examples instead of
drifting from them: a new example is a new seed without anyone copying it.

The destination lives under `fuzz/corpus/`, which is gitignored: what this
writes is a build artifact like the corpus beside it, and a generated tree that
shows up in `git status` is one somebody eventually commits.

Every target gets the same YAML set. The targets differ in how they read their
input — argv bytes, one document spliced into five valid ones — but a seed a
target cannot use costs one execution and teaches the corpus nothing, while a
per-target split costs a mapping that has to be kept right.

    python fuzz/seeds.py                 # every target
    python fuzz/seeds.py --target cli    # one
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FUZZ_DIR = REPO_ROOT / "fuzz"

#: What D-7 names, and nothing else: the examples and the golden tier's inputs.
SOURCE_ROOTS = (REPO_ROOT / "examples", REPO_ROOT / "tests" / "golden")

#: Under the ignored corpus root, beside the per-target working corpora rather
#: than inside them: the count the batch job prints is the corpus the cache
#: round-trips, and seeds mixed into it would hide an empty restore.
DEFAULT_DEST = FUZZ_DIR / "corpus" / "_seeds"


def targets(fuzz_dir: Path = FUZZ_DIR) -> list[str]:
    """Every fuzz target, by the name `just fuzz` takes."""
    return sorted(path.stem.removeprefix("fuzz_") for path in fuzz_dir.glob("fuzz_*.py"))


def seed_sources(roots: tuple[Path, ...] = SOURCE_ROOTS) -> list[Path]:
    return [path for root in roots if root.exists() for path in sorted(root.rglob("*.yaml"))]


def seed_name(path: Path) -> str:
    """The repo-relative path flattened, so two `catalog.yaml` files under
    different projects cannot land on one name and so the name says where the
    seed came from when it turns up in a crash report."""
    relative = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
    return "-".join(relative.parts)


def generate(
    dest_root: Path = DEFAULT_DEST,
    roots: tuple[Path, ...] = SOURCE_ROOTS,
    names: list[str] | None = None,
) -> dict[str, int]:
    """Copy the seeds into each target's seed directory. Returns the count
    written per target."""
    sources = seed_sources(roots)
    written = {}

    for target in names if names is not None else targets():
        dest = dest_root / target
        dest.mkdir(parents=True, exist_ok=True)
        for path in sources:
            shutil.copyfile(path, dest / seed_name(path))
        written[target] = len(sources)

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the fuzz seed corpora.")
    parser.add_argument("--target", action="append", help="a target name (default: all)")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="the seed root")
    parser.add_argument("--source", action="append", type=Path, help="a seed source root")
    args = parser.parse_args(argv)

    roots = tuple(args.source) if args.source else SOURCE_ROOTS
    written = generate(args.dest, roots=roots, names=args.target)
    if not written or not any(written.values()):
        # An empty seed set is a generator that copied nothing — the one
        # outcome a green run and a broken source root look identical from.
        print("no seeds generated", file=sys.stderr)
        return 1

    for target, count in written.items():
        print(f"{target}\t{count} seeds\t{args.dest / target}")
    return 0


if __name__ == "__main__":  # pragma: no cover - the lane's entry point
    raise SystemExit(main())
