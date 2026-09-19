# Fuzzing

The fuzz lane runs one target against a corpus of mutated spec documents and reports any
exception that is not a `BloomeryError`. It is a contributor tool: no CI job runs it, no
acceptance command depends on it, and a target is time-boxed rather than pass-or-fail.

## What a crash means here

bloomery compiles specs to text. It executes nothing, reads no filesystem outside the CLI
and opens no network connection, so a finding is an **availability problem in someone's
build** — a compile that dies on a spec instead of refusing it — or a wrong number, which
is the failure the project exists to prevent. Neither is a vulnerability in the usual
sense, and neither needs private handling: file a finding as an ordinary issue.

`SECURITY.md` applies only if an authored spec escapes the pure-function boundary. That
would be surprising, and it would deserve a private report.

## Run a target

```console
$ just fuzz parse_doors 300
```

The target name is the suffix of `fuzz/fuzz_<name>.py`; the number is seconds. The lane
creates `fuzz/corpus/<target>/` and `fuzz/crashes/`, both gitignored, and passes the
target's seed corpus and dictionary. The corpus accumulates across runs on your machine,
which is how the next run starts further in than this one did — it is a build artifact,
not a test input, and nothing reviews it.

Output is libFuzzer's: `cov` is edges reached, `ft` features, `corp` the corpus it is
keeping. A run that ends on `Done` found nothing. A run that ends on a stack trace wrote
the input that caused it to `fuzz/crashes/<target>-<hash>`.

## Read a crash

Replay it:

```console
$ just fuzz-repro parse_doors fuzz/crashes/parse_doors-a1b2c3
```

This runs the single input once and prints the traceback. Shrink it before reading it
closely — libFuzzer's crashing input is whatever it happened to be holding, usually with
a few hundred irrelevant bytes attached:

```console
$ just fuzz-min parse_doors fuzz/crashes/parse_doors-a1b2c3
```

The minimised input lands at `fuzz/crashes/<target>-minimized`. Replay that one.

The input is bytes, not a document: each target consumes them through a
`FuzzedDataProvider`, so reading the crash means reading the target's `one_input` to see
which door the leading and trailing bytes selected. Print the document the target built
if the shape is not obvious.

## What to do with a finding

**Every confirmed finding becomes a checked-in test under an existing tier**, and the
crash file is deleted. A corpus entry is not a regression test: it is unnamed, unreviewed
and pruned. If the input is expressible as a Hypothesis strategy, the test belongs in the
property tier; otherwise it belongs in the tier that owns the code it crashes.

Then fix it. The fix is almost never to widen what the target accepts:

**The expectation tuple is `(BloomeryError,)`.** `fuzz/_harness.py` treats exactly one
exception type as a correct outcome. That is the same claim
[the errors reference](../reference/errors.md) makes to every caller — catch
`BloomeryError` and you have caught everything the compiler can raise. Widening the
tuple, or adding a caught exception to a target, silently narrows that claim, so it
carries the same review bar as editing the errors reference: it is a public contract
change, not a fuzzing detail.

A `RecursionError` crossing the boundary is a real finding, not a fuzzing artifact. It
reaches a caller who was told `BloomeryError` was total.

## Adding a target

A target is a module `fuzz/fuzz_<name>.py` exposing `one_input(data: bytes)`, with a seed
corpus directory `fuzz/fuzz_<name>_seed_corpus/` and a dictionary `fuzz/fuzz_<name>.dict`
beside it. Build the document in `one_input` and hand it to `_harness.compile_or_refuse`;
the harness owns the expectation, so a target never writes its own `except` clause.

**A target ships with a defect it is known to catch.** A target that has never been
observed to fail is indistinguishable from one that never fires. Name the defect in the
module docstring, along with the change that reintroduces it and the seed that drives it,
so the check is one revert and one `just fuzz-repro` away. `fuzz/fuzz_parse_doors.py`
carries two.
