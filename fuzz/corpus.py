"""The shared fuzz corpus: what the cache round-trips, and what a crash left.

Two questions the batch job asks, and nothing else:

``count``
    How many entries each target's corpus holds. The job asks before the fuzz
    run and again after it, because a corpus in ``actions/cache`` (S-0009/D-3)
    that has stopped round-tripping — an evicted key, a rename, a save that
    never ran — looks exactly like a healthy one from the job's colour alone.
    ``--min-total`` is what turns the after-count from a printed number into a
    check: a run that ends with nothing to keep is a run that explored nothing.

``crashes``
    Whether the run left an artifact behind. This is the batch job's red: the
    fuzz step itself tolerates libFuzzer's non-zero exit so the corpus is still
    saved, and the colour of the job is decided here.

Run it::

    $ uv run python fuzz/corpus.py count --label before
    $ uv run python fuzz/corpus.py count --label after --min-total 1
    $ uv run python fuzz/corpus.py crashes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

FUZZ_DIR = Path(__file__).resolve().parent
DEFAULT_CORPUS = FUZZ_DIR / "corpus"
DEFAULT_CRASHES = FUZZ_DIR / "crashes"


def count(root: Path) -> dict[str, int]:
    """Entries per target. Dot-prefixed directories are working state — the
    generated seeds live in one — and are not corpus entries."""
    if not root.exists():
        return {}
    return {
        directory.name: sum(1 for path in directory.rglob("*") if path.is_file())
        for directory in sorted(root.iterdir())
        if directory.is_dir() and not directory.name.startswith(".")
    }


def crashes(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file()) if root.exists() else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the fuzz corpus.")
    commands = parser.add_subparsers(dest="command", required=True)

    counting = commands.add_parser("count", help="print the entry count per target")
    counting.add_argument("--root", type=Path, default=DEFAULT_CORPUS)
    counting.add_argument("--label", default="corpus", help="what the numbers are")
    counting.add_argument("--min-total", type=int, default=0, help="fail below this total")

    crashing = commands.add_parser("crashes", help="fail when a crash artifact exists")
    crashing.add_argument("--root", type=Path, default=DEFAULT_CRASHES)

    args = parser.parse_args(argv)

    if args.command == "count":
        counts = count(args.root)
        total = sum(counts.values())
        entries = " ".join(f"{target}={counts[target]}" for target in sorted(counts))
        print(f"{args.label}: {entries} (total {total})" if entries else f"{args.label}: empty")
        if total < args.min_total:
            print(f"{args.label}: {total} entries, expected at least {args.min_total}", file=sys.stderr)
            return 1
        return 0

    found = crashes(args.root)
    for path in found:
        print(f"crash: {path}")
    if found:
        print(f"crashes: {len(found)} artifact(s) under {args.root}", file=sys.stderr)
        return 1
    print(f"crashes: none under {args.root}")
    return 0


if __name__ == "__main__":  # pragma: no cover - the script entry point
    raise SystemExit(main())
