# Fuzzing the compile boundary

A lane you run by hand, not a tier CI runs. It feeds mutated bytes to the
public API and tries to falsify one promise the project already makes: that
`except BloomeryError` is enough.

## What it is for

`pages/docs/reference/errors.md` tells a caller that every refusal is a
`BloomeryError`. The compiler reaches a dozen `sqlglot.parse_one` calls behind
that claim, under four different handler disciplines, and a total claim about a
boundary with a dozen doors is exactly what coverage-guided mutation is for.

The oracle is therefore not "did not crash". It is: **anything that is not a
`BloomeryError` leaving `load_project`, `compile_project` or the planner is a
finding** — a code bug or a documentation lie, with nothing in between. A
target implements that by catching `BloomeryError` and nothing else; Atheris
reports whatever is left.

The threat model is a data platform ingesting spec YAML from a wide authoring
surface, possibly machine-generated. bloomery executes nothing, reads no
filesystem outside the CLI and touches no network, so a crash here is an
availability problem in someone's build and a wrong number is the failure the
project exists to prevent. Neither is a vulnerability in the usual sense.
`SECURITY.md` applies only if an authored spec escapes the pure-function
boundary, which would be surprising and would deserve private handling.

## Running one

```console
$ just fuzz parse_doors 300
```

The target name is the file under `fuzz/` without its `fuzz_` prefix, and the
number is a time budget in seconds. The lane runs with the target's committed
dictionary and seed corpus, and accumulates new inputs under `fuzz/corpus/`,
which is gitignored: the corpus is a build artifact, and every run on a laptop
starts from the seeds plus whatever the last run left behind.

`atheris` is in the dev group, so `uv sync --all-groups` is all the setup there
is. It ships manylinux wheels and needs no local clang; a platform without a
wheel loses this lane and nothing else.

## Reading a crash

libFuzzer writes the offending bytes to `fuzz/crashes/crash-<hash>` and prints
the Python traceback above it. Replay it:

```console
$ just fuzz-repro parse_doors fuzz/crashes/crash-<hash>
```

A replay is deterministic. If the same input gives a different answer twice,
that is itself a finding — the target has ambient state.

Then shrink it, which usually turns eight hundred bytes into forty:

```console
$ just fuzz-min parse_doors fuzz/crashes/crash-<hash>
```

The input is not the document: a target reads its bytes through Atheris'
`FuzzedDataProvider`, which takes integers from the *back* of the buffer. For
`fuzz_parse_doors` an input is the expression text, then one byte choosing how
deep the caller's stack is, then one byte choosing the door. That is why the
seed files under `fuzz/fuzz_parse_doors_seed_corpus/` are named
`<text>.door<n>.pad<n>` — the name is the last two bytes, spelled out.

## Triage

Four buckets.

**Boundary escape.** Always a bug. The fix is a guard at the door, and the
template is to find every site sharing that type rather than the one reported —
the escape this lane descends from was found by hand at five sites and reported
at four.

**Contract gap.** The input is genuinely invalid and no named reason exists.
That is a design decision: choose the reason, write it into
`pages/docs/reference/errors.md`, and give it a document of its own if the
guardrail is new.

**Determinism or refusal-quality failure.** An assertion fired. It falsifies a
headline promise and blocks a release.

**Harness noise.** Fix the target — never the expectation tuple.

When a stack terminates inside SQLGlot with no bloomery frame at fault:
reproduce it against SQLGlot directly, report it upstream, and **guard it
locally anyway**. Catching a class of upstream failure at our own door is the
contract, not a workaround.

Every confirmed finding becomes a checked-in test under an existing tier before
the corpus is relied on to hold it. The deliverable of a fuzz run is a test in
`tests/`, not a file in a corpus directory: the corpus is unreviewed, unnamed
and gets pruned, so a finding living only there regresses silently.

## The one rule about the expectation tuple

`EXPECTED` in `fuzz/_harness.py` is `(BloomeryError,)`, with no exemptions.

Widening it is not a harness change. It is a change to the error taxonomy, and
it carries the same review bar as editing `pages/docs/reference/errors.md`: it
lands with a fix translating the exception into a `BloomeryError`, or with a
recorded decision that the escape is intended. A tuple that grows to fit the
last crash converts a falsifiable promise into a record of current behaviour,
which is how fuzzing setups become decorative.

## Proving a target can fail

A target that has never been observed to fail is indistinguishable from a
target that never fires. So each one ships with a known-catchable defect
recorded beside it, and the check is: reintroduce the defect, run the target,
watch it report.

For `fuzz_parse_doors`, both halves were run when it landed:

- Narrow `_parses_as_sql` in `src/bloomery/spec/common.py` back to
  `except SqlglotError` — the escape this lane descends from — and the target
  reports at `spec/common.py` on the first deeply nested seed.
- Narrow the handler in `src/bloomery/resolve/steps.py` the same way and the
  target reports through the registry door.

The clean tree passes the same seeds, which is the other half: a target that
cannot pass is as broken as one that cannot fail.

## Known open finding

`fuzz_parse_doors` reports on the shipped tree, from a committed seed, within
the first few executions. It is real and it is not yours:

> An authored expression of about fifty nested parentheses passes the spec
> layer's validator and then raises `RecursionError` out of `compile_project`
> at the unguarded `parse_one` in `src/bloomery/ir/nodes.py` — with a second
> reachable site at `src/bloomery/resolve/build.py`. SQLGlot's parser recurses
> per nesting level, so what the validator proved is that the expression parses
> *at the stack position the validator ran from*; these sites run several
> frames deeper, and a caller deep in its own stack moves the whole band.

Both sites are outside the scope of the change that landed this lane, so they
are reported rather than fixed here. Until they are guarded, expect a run to
stop on that finding first; `just fuzz-repro` on the crash file names the site
in its traceback, so a *different* traceback is a new finding and worth
chasing.

## What the lane does not do

Memory safety (this is pure Python), semantic correctness (a fuzzer knows the
compiler contradicted itself; it never knows the right number — that is the
execution and equivalence tiers), and fuzzing SQLGlot itself. It also does not
replace the property tier: that tier builds well-typed *model objects* inside
valid space, and this lane owns the text layer and the accept/refuse boundary.
A finding expressible as a Hypothesis strategy over model objects belongs
there, not here.
