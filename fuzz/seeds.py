"""Generate each fuzz target's seed corpus from the examples and the goldens.

S-0009/D-7: the seeds are *derived* from ``examples/**`` and ``tests/golden/**``
at build time rather than committed a second time under ``fuzz/``, so the corpus
floor tracks the examples instead of drifting from them — a new example is a new
seed without anyone copying it.

The checked-in ``fuzz/fuzz_<target>_seed_corpus`` directories stay what they are:
hand-written inputs that name a shape worth keeping (a deeply nested filter, a
bare ``--help``). This script adds the project documents the repository already
maintains, into a directory the batch job hands to libFuzzer alongside them.

Run it::

    $ uv run python fuzz/seeds.py
    $ uv run python fuzz/seeds.py --out /tmp/seeds --root examples
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FUZZ_DIR = Path(__file__).resolve().parent

#: Where the generated seeds land. Under ``fuzz/corpus/``, which the lane
#: already treats as a working directory and ``.gitignore`` already ignores;
#: dot-prefixed so it can never be mistaken for a target's corpus by
#: ``fuzz/corpus.py``, whose counts are what the batch job reads.
DEFAULT_OUT = FUZZ_DIR / "corpus" / ".seeds"

SOURCE_ROOTS = (REPO_ROOT / "examples", REPO_ROOT / "tests" / "golden")
SUFFIXES = (".yaml", ".yml")


def targets(fuzz_dir: Path = FUZZ_DIR) -> list[str]:
    """Every fuzz target, derived from the directory rather than written out —
    a target added without a seed directory is the failure this avoids."""
    return sorted(path.stem.removeprefix("fuzz_") for path in fuzz_dir.glob("fuzz_*.py"))


def seed_documents(roots: tuple[Path, ...] = SOURCE_ROOTS) -> dict[str, Path]:
    """Every YAML document under `roots`, keyed by its flattened repo-relative
    path: the corpus is one flat directory, and a dozen goldens each carrying a
    ``config.yaml`` would otherwise be one seed."""
    documents: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in SUFFIXES or not path.is_file():
                continue
            # Repo-relative where it can be — a seed name a reader can find —
            # and root-relative otherwise, since a root outside the tree is
            # legal and its anchor is not part of a file name.
            base = REPO_ROOT if path.is_relative_to(REPO_ROOT) else root
            documents["-".join(path.relative_to(base).parts)] = path
    return documents


def generate(
    out: Path,
    roots: tuple[Path, ...] = SOURCE_ROOTS,
    names: list[str] | None = None,
) -> dict[str, int]:
    """Copy the seed documents into each target's seed directory."""
    documents = seed_documents(roots)
    counts = {}
    for target in names if names is not None else targets():
        directory = out / target
        directory.mkdir(parents=True, exist_ok=True)
        for name, path in documents.items():
            shutil.copyfile(path, directory / name)
        counts[target] = len(documents)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the fuzz seed corpora.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="the seed root")
    parser.add_argument("--root", action="append", type=Path, help="a document root")
    parser.add_argument("--target", action="append", help="one target (default: all)")
    args = parser.parse_args(argv)

    roots = tuple(args.root) if args.root else SOURCE_ROOTS
    counts = generate(args.out, roots, args.target)

    # No documents means the roots moved and every target would be handed an
    # empty seed directory — a fuzzing run that starts from nothing and reports
    # the same green as one that started from the whole corpus.
    if not any(counts.values()):
        print(f"seeds: no YAML documents under {', '.join(str(r) for r in roots)}", file=sys.stderr)
        return 1

    for target in sorted(counts):
        print(f"seeds: {target}={counts[target]}")
    return 0


if __name__ == "__main__":  # pragma: no cover - the script entry point
    raise SystemExit(main())
