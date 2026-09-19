"""The CLI target: fuzzed argv through `main` in process (S-0008, phase 2).

`main` is the one entry point whose contract is a number. It returns the exit
code rather than raising, and it wraps parser construction, parsing and every
command body in a single boundary — so a defect anywhere under it surfaces as
`EXIT_INTERNAL` rather than as a traceback the shell never sees. That is what
this target reads.

**The oracle is exactly one assertion** (S-0008/D-2): `main(argv)` never
returns `EXIT_INTERNAL`. Not that it returns one of ok, refused or usage — a
command body may legitimately hand back anything argparse hands it, and a check
that enumerates the acceptable codes reports a *genuine* internal error as a
generic out-of-range code, which is a worse sentence to read from a crash file
than "bloomery said it was its own bug".

`main` is called **in process**, not as a subprocess. A subprocess per execution
loses coverage feedback entirely: libFuzzer's instrumentation lives in this
interpreter, so a fork that does the work leaves the fuzzer guiding itself by a
constant, at which point the mutation engine is a random byte generator.

Run it through the lane rather than directly::

    just fuzz cli 60

Its own known-catchable defect, for the sabotage check the lane owes every
target (S-0008/D-9). Delete the negative-depth arm of `_depth` in
`src/bloomery/cli/__init__.py` — the three lines raising
`ArgumentTypeError` for a depth below zero — and replay::

    just fuzz-repro cli fuzz/fuzz_cli_seed_corpus/lineage-negative-depth

Without that arm `-1` parses as an int, reaches the library, and comes back as
a bare `ValueError`: not a `BloomeryError`, so the catch-all claims it and
`main` returns `EXIT_INTERNAL`. The target reports the assertion, and the
checked-in regression for the same defect is
`test_lineage_rejects_a_negative_max_depth_as_a_usage_error` (S-0008/D-4).
"""

from __future__ import annotations

import contextlib
import os
import sys

import atheris

with atheris.instrument_imports():
    import _harness

    from bloomery.cli import EXIT_INTERNAL, EXIT_OK, main

#: The fixture set as a spec directory. `catalog.yaml` sits in it, so the
#: convention picks the catalog up and no invocation needs `--catalog` to reach
#: past loading.
SPECS = str(_harness.FIXTURES)

#: Argv prefixes that reach past the parser, one per command, each carrying the
#: flags argparse requires. The fuzzed tokens are appended to one of these, so
#: a mutation spends its bytes on the flag values and the command bodies rather
#: than on rediscovering that `lineage` needs a `--node`.
#:
#: The empty prefix is the parser's own door: argv is then entirely fuzzed, and
#: `build_parser` and `parse_args` are as capable of a bloomery bug as any
#: command body — which is why `main` wraps them too.
PREFIXES: tuple[tuple[str, ...], ...] = (
    (),
    ("resolve", SPECS),
    ("check", SPECS),
    ("compile", SPECS),
    ("fingerprint", SPECS),
    ("schema",),
    ("plan", SPECS, SPECS),
    ("lineage", SPECS, "--node", "metric.revenue"),
    ("timeline", SPECS, SPECS, "--node", "metric.revenue"),
    ("explain", SPECS, "--metrics", "revenue"),
)

#: How the fuzzed text becomes several argv words. A NUL cannot appear in a
#: real argv, so it is free to use as the separator, and one flag per mutation
#: is not what breaks a command line — a flag beside the flag it contradicts is.
SEPARATOR = "\x00"

#: `--out` is the only flag any command uses to write — `compile` and `schema`
#: declare it and nothing else reaches `write_files` — and its value would be a
#: fuzzer-chosen path. Those write paths are covered by `tests/unit/test_cli.py`
#: (`write_files` refuses a path escaping the output directory, an unwritable
#: directory is a usage error); what this target would add is a corpus run that
#: scatters files across whatever directory a mutation spells.
#:
#: `--o` rather than `--out`, because argparse accepts any unambiguous prefix
#: of a flag and `--o` is unambiguous for both commands that declare it.
WRITES_FILES = "--o"


def _tokens(fdp: atheris.FuzzedDataProvider) -> list[str]:
    raw = fdp.ConsumeBytes(fdp.remaining_bytes())
    if not raw:
        return []
    text = raw.decode("utf-8", "replace")
    return [word for word in text.split(SEPARATOR) if not word.startswith(WRITES_FILES)]


def one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    prefix = PREFIXES[fdp.ConsumeIntInRange(0, len(PREFIXES) - 1)]
    argv = [*prefix, *_tokens(fdp)]

    # The command bodies print, and a corpus run would otherwise bury
    # libFuzzer's own output under a few hundred thousand rendered tables.
    # A real file rather than a `StringIO`: the broken-pipe and failed-flush
    # arms of `main` call `silence_stdout`, which asks stdout for its
    # descriptor. The redirect is per execution so that the traceback atheris
    # prints for a finding still reaches a terminal.
    with open(os.devnull, "w") as quiet:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            code = main(argv)

    assert code != EXIT_INTERNAL, f"main({argv!r}) returned EXIT_INTERNAL"


def _check_prefixes() -> None:
    """Every prefix is a complete, succeeding invocation.

    A target whose every execution is a usage error fuzzes the argument parser
    and nothing behind it, and stays green forever — the dominant failure mode
    of a fuzzing setup. A drifted fixture is a loud failure here rather than a
    quiet one out there.
    """
    for prefix in PREFIXES:
        if not prefix:
            continue
        with open(os.devnull, "w") as quiet:
            with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
                code = main(list(prefix))
        if code != EXIT_OK:
            msg = f"`bloomery {' '.join(prefix)}` exits {code}: this target fuzzes nothing"
            raise SystemExit(msg)


if __name__ == "__main__":
    _check_prefixes()
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()
