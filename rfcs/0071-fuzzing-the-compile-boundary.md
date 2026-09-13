# RFC 0071 — Fuzzing the compile boundary

- **Status:** 📝 Draft
- **Scope:** A seventh test lane: coverage-guided fuzz targets under `fuzz/`, run
  locally through `just`, that feed mutated bytes to `load_project`,
  `compile_project` and `cli.main` and assert the two promises this project
  already makes about its boundary — only `BloomeryError` crosses it, and
  `EXIT_INTERNAL` never happens. Adds `atheris` as a dev dependency and one
  `justfile` lane. **No CI, no corpus storage, no container** — that is RFC 0072,
  and this document is deliberately executable and useful without it. No
  structure-aware generation — that is RFC 0073. No `src/bloomery/` change except
  the guard fixes findings force, each of which is an ordinary bug fix that would
  be made whether or not this lane exists.
- **Related:** [`src/bloomery/errors.py`](../src/bloomery/errors.py),
  [`src/bloomery/spec/common.py`](../src/bloomery/spec/common.py) (`_parses_as_sql`,
  `SqlText`), [`src/bloomery/cli/__init__.py`](../src/bloomery/cli/__init__.py)
  (`main`, the exit-code table),
  [`src/bloomery/resolve/steps.py`](../src/bloomery/resolve/steps.py) (`_parse_body`),
  [`tests/property/test_parse_properties.py`](../tests/property/test_parse_properties.py)
  (`KNOWN_UNSUPPORTED` — the same idiom, already shipped). RFC 0072 (CI),
  RFC 0073 (schema-directed generation). PR #111 is the precedent this argues from.
- **Origin:** An external design note proposing ClusterFuzzLite for this repo,
  written from the public README and PyPI metadata rather than the source. Its
  method survives; several of its premises did not (§3), and the corrections
  reorder its priorities rather than trimming them.

---

## 1. Summary

bloomery sells three falsifiable promises — deterministic, fail-closed,
reviewable — and a fuzzer is a machine for falsifying them. This adds targets
that mutate authored text and check the *strongest and cheapest* of the three:
the compile boundary is total over `BloomeryError`. Nothing else may cross it.

The lane is Atheris and libFuzzer over the public API, seeded from
`examples/` and `tests/golden/`, run by hand and in CI once RFC 0072 lands. It
adds a dev dependency, a `fuzz/` directory and a `just` lane; it changes no
shipped code.

## 2. Motivation

### The contract is machine-checkable, and only one of its doors has been checked

`bloomery.errors` holds 62 exception classes and every one of them descends from
`BloomeryError` (verified, §3). The error reference tells a caller that
`except BloomeryError` is sufficient. That is a **total** claim about a boundary
with a dozen parse sites behind it, and a claim of that shape is exactly what
coverage-guided mutation is for: any input producing something else is a
documentation lie or a code bug, with no judgement call in between.

PR #111 is the precedent. An authored `expr:` reached `sqlglot.parse_one`
unguarded and left the boundary as a raw SQLGlot exception, past the
`except BloomeryError` the reference promises. It was found by hand, across five
call sites, and the initial report named four — *"five doors, not the one
reported"*. A fuzzer does not miss doors; it finds whichever one is reachable.

### The precedent's fix was better than the report, which is why the premise needs restating

The external note treats the `expr:` sites as the highest-yield target on the
grounds that the door count is *"genuinely uncertain"*. It is not, and this is
the single most important correction in this document. #111 was fixed **at the
type**:

```python
SqlText = Annotated[str, AfterValidator(_parses_as_sql)]
```

`_parses_as_sql` catches `SqlglotError` **and** `RecursionError`, and all four
authored-SQL fields — `Recipe.expr`, `MetricTemplate.expr`, `Metric.expr`,
`DerivedSpec.expr` — carry that annotation, as would a fifth added tomorrow. A
guard at the type has no door count. Measured: ten hostile payloads through the
metric `expr:` door (unterminated string, 400-deep parens, 5000-term addition, a
statement, two statements, a NUL, a lone surrogate, a 200 KB identifier, empty,
whitespace) produce a `BloomeryError` or a clean compile, every one — and every
one of them also sits *outside* the band the next subsection measures, which is
the sense in which reading a guard is not testing it.

So the yield is not behind `SqlText`. It is behind the fact that **`SqlText` is
one of four different answers this codebase gives to the same question.**
Fifteen `parse_one` call sites exist, and their enclosing handlers are:

| Handler | Sites |
|---|---|
| `except (SqlglotError, RecursionError)` | 4 — `spec/common.py` ×2, `resolve/build.py` ×2 |
| `except SqlglotError` — no `RecursionError` | 2 — `evidence.py:824`, `resolve/steps.py:740` |
| `except Exception` | 2 — `quality/pattern.py:84`, `guardrails/quality.py:1209` |
| no enclosing handler | 7 |

`sqlglot.parse_one("(" * 200 + "1" + ")" * 200)` raises `RecursionError`, not a
`SqlglotError`, at every depth tested (200 / 500 / 1000 / 3000). So the second
row is a real gap, and the sharper of its two instances is `evidence.py:824` —
inside `_divides()` — whose own docstring records this exact lesson:

> `SqlglotError`, not `ParseError`. An unterminated string literal raises
> `TokenError`, which is a sibling of `ParseError` rather than a subclass — so
> the narrower catch let a third-party exception out of `evaluate`, whose whole
> contract is that a spec-level problem comes back as a value
> (`logs/T-0048.md`).

The same fix, from the same incident, applied at three sites at two different
widths — and the site with the **strongest** contract got the narrow one.
`evaluate()` does not merely promise the right exception type; it promises to
return a `SpecEvidence` rather than raise at all. A `RecursionError` there breaks
a stronger promise than #111 broke.

### The type-level guard is stack-position dependent, which is measured, not argued

The seven unguarded sites parse text that already passed `_parses_as_sql`, and
reading the annotations says that clears them. Running it says otherwise.

`RecursionError` depends on the *remaining* stack, not on the expression. A
validator running shallow — inside Pydantic, during parse — tolerates nesting
that the same `parse_one` on the same string rejects when it runs deeper in a
call chain. Measured at `sys.getrecursionlimit() == 1000`:

| Nesting depth | `_parses_as_sql` accepts | same expression, 300 frames deeper |
|---|---|---|
| 20 | yes | parses |
| **40** | **yes** | **`RecursionError`** |
| 60+ | no — refused at parse | — |

So there is a band of authored input that is *valid by the type* and unparseable
at the sites that re-parse it. A `SqlText` value is a proof about one stack
position, and every downstream `parse_one` runs at a different one.

This is the finding that decides the document. It cannot be found by reading —
the annotation is right there and says "guarded" — and it is exactly what a
fuzzer that runs full compiles over generated depth finds by accident. Whether
any *reachable* call chain is deep enough to turn the band into an escape is §10's
first question, and it is a question about call depth, which is what execution
measures rather than what this document asserts.

Beyond that band, the seven unguarded sites are mostly legitimate: they parse
text that already passed `_parses_as_sql` upstream, which is the type-level fix
working as intended. "Mostly" is the operative word, and nobody has checked
which. That question — *which parse site can receive text no validator cleared* — is what
§5.3 T1 automates, and it is not answerable by reading a type annotation, because
the dangerous case is **composition**: two individually valid fragments spliced
into one expression that is then re-parsed. `quality/pattern.py` renders and
re-parses; `resolve/build.py` splices recipe bodies. Validity is not closed under
composition, and no per-field validator can see that.


## 3. Current state

Verified against the tree at `813af02c`, not from memory. The external note
carried eight items marked **CONFIRM**; all but one are settled here, and three
of them came back different from what it assumed.

| Claim | Verified | Consequence |
|---|---|---|
| `BloomeryError` roots every refusal | **Yes** — 62 exception classes in `bloomery.errors`, zero outside the hierarchy | `EXPECTED = (BloomeryError,)` is exactly right, with no exemptions |
| The refusal's spec path attribute | `source_path`, not `path` or `spec_path` | The note's `check_refusal_quality` reads neither of its two guesses |
| `load_project` takes named documents | `load_project(sources: Mapping[str, str])`, sorted-name order, failures batched | One-fuzzed-document-of-six is directly expressible |
| A CLI `main(argv)` returning a code | **Already exists** — `main(argv: Sequence[str] \| None = None) -> int`, with argparse's own `SystemExit` caught and passed through | No refactor needed; the note budgets one |
| Exit codes | `0` ok, `1` refused, `2` usage, **`3` internal** | §2's oracle. A crash is already distinguishable |
| `bloomery schema` in a build container | Exists (`--out` writes one file per kind), **and `all_spec_schemas()` is a library call** | RFC 0073 needs no CLI step and no filesystem |
| `TypeString` / `PartitionSpecString` are grammars | **No** — both are `StringConstraints(pattern=...)`, plain regex | They earn no door of their own. `SqlText` is the only parser at the spec layer |
| `expr:` sites | Four, all `SqlText`; the guard is on the type, not the fields | §2 — the four are one door, not four |
| `parse_one` call sites | **15**, under four different handler disciplines (§2) | §5.3 T1's whole target list |
| The OSS-Fuzz base image's Python | Open — see RFC 0072 §3 | Does not block this document, which needs no container |

Two further facts shape the design:

**The `EXPECTED` idiom already ships here, under another name.**
`tests/property/test_parse_properties.py` asserts the filter parser is *total*:
any generated document either parses or refuses with a reason drawn from
`KNOWN_UNSUPPORTED`, and adversarial nesting must reach a `FilterTooComplex`
refusal — *"never a `RecursionError`"*, in the module docstring. That is this
document's oracle, one subsystem wide, written by this project, before this
document existed. The fuzz lane generalises an idiom the corpus already trusts
rather than importing a foreign one.

**Six tiers exist** (`unit`, `golden`, `property`, `execution`, `engine`, `e2e`),
plus a `chaos` mutation meta-test and a `bench` lane. The property tier
constructs *model objects* — well-typed values inside valid space. It cannot
produce an unterminated SQL string inside a YAML block scalar, because its
generators never emit text. That is the seam this lane occupies, and §5.6 states
it as a rule rather than a hope.

## 4. Goals / Non-goals

**Goals**

- Make the boundary claim mechanically falsifiable: a target that reports any
  non-`BloomeryError` escape from `load_project` or `compile_project`.
- Make the CLI's own internal-error contract enforceable: exit 3 is a finding.
- Cover the parse sites `SqlText` does not, which is where §2's evidence points.
- Fit the existing tier vocabulary — a marker, a `just` lane, seeds from
  `examples/`, findings that become ordinary tests.
- Be useful on a laptop with no CI, no container and no corpus repository.

**Non-goals**

- **Memory safety.** Pure Python. The sanitizer choice is a formality.
- **Semantic correctness.** A fuzzer knows the compiler contradicted itself; it
  never knows the right number. That is the execution and equivalence tiers.
- **Replacing the property tier.** Disjoint by construction (§5.6).
- **Fuzzing sqlglot.** We will find sqlglot bugs and report them (§5.7), but the
  targets check *our* boundary; fuzzing sqlglot properly means calling it directly.
- **A Scorecard `Fuzzing` check.** A real side effect of RFC 0072, and a bad
  motivation: a lane that exists for a badge grows an `EXPECTED` wide enough to
  never fail.

## 5. Design

### 5.1 Two oracles, and the order they earn their keep

An oracle decides whether an execution was a finding. *"Did not raise"* is the
weakest available and close to worthless on its own. Two are worth encoding
first, and both are contract restatements rather than inventions:

1. **Boundary totality.** `load_project`, `compile_project` and the planner may
   raise `BloomeryError` and nothing else. Atheris reports an uncaught exception
   automatically, so the oracle is implemented by *not catching* the wrong things.
2. **Exit-code discipline.** `cli.main(argv)` returns `0`, `1` or `2`. A `3` is
   the CLI reporting its own defect (§2) and is a finding by the code's own words.

Three more are cheap once a target exists, in descending order of what they
catch: **refusal quality** (every `BloomeryError` renders, and carries a
`source_path` — the batched aggregates are where message-formatting bugs live,
since the first refusal formats fine and the twelfth in a batch is what breaks),
**in-process determinism** (`compile_project` twice on one `Project`, and once
more on a freshly loaded one — the two failures are distinct: compiler state
versus caching keyed on object identity, and `LruManifestHydrator` makes the
concern live), and **cross-dialect consistency** (a spec is compiled or refused
with a named reason on each of duckdb / trino / postgres; differing *refusals*
are legitimate, since dialects differ in capability).

The full determinism claim — across processes and across `PYTHONHASHSEED` — is
not assertable in-process and is deliberately deferred to RFC 0072's replay job.

### 5.2 `EXPECTED` is the error reference, and it must not grow

```python
EXPECTED: tuple[type[BaseException], ...] = (BloomeryError,)
```

Full stop, with no exemptions — §3 confirms none are needed. What stays out and
why: `yaml.YAMLError` (the loader owns YAML; a raw parser error reaching a caller
is a leaked abstraction), `SqlglotError` and `TokenError` (exactly #111),
`RecursionError` (catching it hides an unbounded-recursion DoS — if depth should
be bounded, the fix is a limit raising a named error, which is what
`FilterTooComplex` already is), `KeyError` / `AttributeError` / `TypeError` (the
signature of a spec field read without validation), `UnicodeDecodeError`,
`MemoryError`, `OverflowError`, and `AssertionError` — never catch our own oracle.

**A tuple that grows is a finding about the error taxonomy, not about the
fuzzer.** Each addition must arrive with either a fix translating the exception
into a `BloomeryError`, or a recorded decision that the escape is intended —
recorded in the error reference, not in a tuple under `fuzz/`. D3 makes this a
review rule rather than a note: widening `EXPECTED` and editing the error
reference are the same change expressed in two places, and they carry the same bar.

### 5.3 The targets, in the order the evidence puts them

Build in this order; do not write them all before running any.

**T1 — `fuzz_parse_doors.py`.** §2's census generalised: the thirteen
`parse_one` sites outside `_parses_as_sql`, across `evidence.py`,
`quality/pattern.py`, `resolve/steps.py`, `ir/nodes.py`, `emit/lower/marts.py`,
`resolve/build.py` (×5), `guardrails/arithmetic.py`, `guardrails/grain.py` and
`guardrails/quality.py`. Two sub-shapes, and the second is the interesting one:

- *Direct* — text reaching a site without passing `_parses_as_sql`. The two
  narrow-handler sites are the known instances; §2 argues `evidence.py:824` is
  the sharper of them.
- *Composed* — two individually valid fragments concatenated or templated into a
  larger expression which is then re-parsed. `quality/pattern.py::_transports_literal`
  renders and re-parses; `resolve/build.py` splices recipe bodies. Validity is not
  closed under composition, and **no per-field validator can see this** — which is
  why the seven unguarded sites cannot be cleared by reading annotations.

**T2 — `fuzz_cli.py`.** One assertion, `main(argv) != 3`, over fuzzed argv,
called **in process** — a subprocess per execution drops throughput by orders of
magnitude and loses coverage feedback entirely.

**T3 — `fuzz_load_project.py`.** One fuzzed document against five held valid, the
kind chosen from the fuzzer's own bytes. Fuzzing all six at once means nearly
every input dies at the first document and cross-document resolution — where the
interesting guardrails live — is never reached. Holding five valid means a
mutation to `marts.yaml` can produce a real grain violation against real entities.

**T4 — `fuzz_compile_determinism.py`** and **T5 — `fuzz_cross_dialect.py`**, per
§5.1.

**T6 — `fuzz_metric_request.py`.** Fixed valid IR, fuzzed `MetricRequest`, names
drawn half from a known-good pool so the target gets past *"no such metric"*. It
carries one assertion worth more than it looks: a plan that renders valid SQL and
an empty or crashing `Explanation` is a real defect, and the explanation is
user-facing and generated deterministically.

### 5.4 Where the code lives, and how it runs

```
fuzz/
  _harness.py                  # EXPECTED, check_refusal_quality, fixture loading
  fixtures/                    # one valid six-document set, plus expr templates
  fuzz_<name>.py               # one target each
  fuzz_<name>_seed_corpus/
  fuzz_<name>.dict
```

`just fuzz <target> [seconds]` runs one target with its dictionary and seeds;
`just fuzz-repro` and `just fuzz-min` reproduce and minimise a crash.
`.fuzz-corpus/` and `.fuzz-crashes/` are gitignored. `atheris` joins the dev
group — it ships manylinux wheels for cp312/cp313/cp314 (verified, PyPI 3.1.0),
which is exactly this project's `requires-python` window and needs no local clang.

### 5.5 Seeds and dictionaries

Random bytes essentially never survive `yaml.safe_load`. Seeds are not an
optimisation; without them the lane does nothing.

`examples/quickstart`, `examples/targets` and `examples/lakehouse` are the
backbone. **`examples/refusals` matters most**: five specs that look right and
cannot be right, sitting exactly on the accept/refuse boundary — a seed that is
*just barely* refused is one mutation from being *just barely* accepted, which is
where guardrail bugs live. `tests/golden/` inputs and the numbered case corpus
come in for the same reason: those cases were chosen for sitting at awkward
semantic corners.

Hand-written pathological seeds cost nothing: empty and whitespace-only; a bare
scalar and a top-level list; 200 levels of nested mappings; a 1 MB scalar; every
key present and every value `null`; duplicate keys; a BOM, a lone surrogate, a NUL
inside a scalar; anchors and aliases including a self-referential one. For the SQL
targets, seed with SQL rather than YAML.

Dictionaries carry the project's own vocabulary — spec keys, `additivity`
members, transform names from `reference/transforms`. A dictionary entry naming a
real transform reaches code a random identifier never will.

### 5.6 The seam against the property tier, as a rule

| Tier | Input | Finds |
|---|---|---|
| `property` | Typed generators over the domain model | Invariant violations in **valid** space |
| `fuzz` | Mutated bytes | Behaviour in **invalid and near-valid** space |

**The fuzzer owns the text layer and the accept/refuse boundary; the property
tier owns the semantic layer inside valid space.** A finding expressible as a
Hypothesis strategy over model objects belongs in the property tier, and D5 says
to put it there. One coupling runs the other way: a minimised corpus entry that
is *valid* and structurally interesting is a free property-tier example.

### 5.7 Triage

Four buckets. **Boundary escape** — always a bug; the fix is a guard at the door
and #111 is the template: find every door sharing that type, not the reported one.
**Contract gap** — the input is genuinely invalid and no named reason exists;
that is a design decision, so choose the reason, write it into the error
reference, RFC it if the guardrail is new. **Determinism or refusal-quality
failure** — an assertion fired; it falsifies a headline promise and blocks a
release. **Harness noise** — fix the target, never `EXPECTED` (§5.2).

Upstream findings are expected as a steady trickle. When a stack terminates
inside sqlglot with no bloomery frame at fault: reproduce against sqlglot
directly, report it, and **guard it locally anyway**. Catching a class of upstream
failure at our door is the contract, not a workaround.

**Every finding becomes a test** (D4). The corpus is unreviewed, unnamed and gets
pruned; a finding living only there regresses silently.

### Alternatives considered

**Hypothesis instead of Atheris.** The property tier already runs Hypothesis, and
one tool is cheaper than two. Rejected: Hypothesis shrinks well but has no
coverage feedback, so it cannot *steer* toward an unexplored branch, and the
corpus — the accumulating asset that makes a fuzzer better next month than this
month — has no equivalent. Where a finding fits Hypothesis, §5.6 sends it there.

**Widening `EXPECTED` to whatever the first run reports.** The fastest way to a
green lane and the reason fuzzing setups become decorative. §5.2 forbids it.

**Fuzzing the emitters directly with hand-built IR.** Rejected: they receive
validated values from our own code, so findings there are unreachable states.
Reaching them through `compile_project` is the correct route.

## 6. Tests

The lane is test infrastructure, so the question is how we know its oracle works
rather than what it covers.

- **Sabotage before coverage.** Re-narrow `_parses_as_sql` to `except
  SqlglotError` and T1 must find it within a bounded run. An oracle that does not
  catch the reintroduced #111 is not an oracle. Each target ships with one such
  known-catchable defect recorded beside it.
- **The `_parse_body` finding becomes a unit test** the moment its guard is
  widened — a nested body, `pytest.raises(BloomeryError)`. That test is the
  deliverable; the target is what found it.
- **`just fuzz-repro` on a minimised input is deterministic**, or the target has
  ambient state and is itself a determinism finding.
- **Not tested:** that the corpus is any good. Only a coverage report answers
  that, and that is RFC 0072.

## 7. Docs

`pages/docs/contributing/fuzzing.md` — a new archetype directory; the docs tree
has `concepts`, `get-started`, `how-to` and `reference` today, and this is
contributor-facing rather than user-facing, so it does not belong in any of them.
A how-to in altitude terms: run one target, read a crash, minimise it, file it.

`CONTRIBUTING.md` gains the lane in its test-tier list. No user-facing page
changes: nothing here alters what bloomery does.

One wording caveat. The threat model is **a data platform ingesting spec YAML
from a wide authoring surface, possibly machine-generated**. bloomery executes
nothing, reads no filesystem outside the CLI and touches no network, so a crash
is an availability problem in someone's build and a wrong number is the failure
the project exists to prevent. Neither is a vulnerability in the usual sense, and
the page must not imply otherwise. `SECURITY.md` applies only if an authored spec
escapes the pure-function boundary — which would be surprising, and would deserve
private handling.

## 8. Out of scope

- **CI, corpus persistence, containers, coverage reports** — RFC 0072. Without
  persistent storage every run restarts from zero and never gets past the YAML
  parser, which is why the two documents are ordered this way rather than merged.
- **Schema-directed generation** — RFC 0073. §5.5's ceiling is how often random
  mutation produces schema-valid YAML, and that is a design question with its own
  answer, including the possibility that it is a property-tier feature.
- **The container-backed examples.** A container per execution destroys
  throughput, and the execution tier already covers engines running.
- **`Artifact` value objects, naming helpers, enum lowerings.** No untrusted input.
- **Anything needing a warehouse connection.** The library does not read one.

## 9. Risks

- **The oracle passes because it asserts nothing.** The dominant failure mode of
  fuzzing setups. Mitigated by §6's sabotage requirement and by D3.
- **Findings dry up after week one and the lane rots.** Likely, and survivable:
  the corpus keeps its value, and §5.3's ordering front-loads what pays. If
  targets must be cut, T1 alone retains most of the value.
- **`resolve/steps.py:740`'s narrow guard turns out to be deliberate.** Step
  manifests are declared *trusted* input — written by the platform team, never
  read from disk by bloomery — so that one may be hygiene rather than a defect.
  The argument does not transfer to `evidence.py:824`, which reads an authored
  `Project`, and D7 covers both rather than generalising from the weaker case.
- **Throughput disappoints.** Atheris on instrumented pure Python runs thousands
  of executions per second, not millions, and far fewer once each runs a full
  compile. You cannot brute-force past a bad corpus, which is why §5.5 is long.
- **Read as security theatre.** §7's wording caveat exists for this.
- **The dev dependency has a compiled extension.** `atheris` ships binary wheels;
  a contributor on an unusual platform may not get one. It is dev-group and
  lane-gated, so `just test` is unaffected.

## 10. Unresolved questions

- **Is any reachable call chain deep enough to turn §2's band into an escape?**
  The band is measured — depth 40 accepted by the validator, `RecursionError` 300
  frames deeper — and the two narrow handlers are proven at the source. What is
  *not* measured is the stack depth at each of the thirteen sites under a real
  compile. That is a number, obtainable in one instrumented run, and it settles
  D7 for every site at once, including whether the seven unguarded ones need
  anything at all. `evidence.py:824` sits in `_divides()`, reached from
  `evaluate()`, which takes an authored `Project`; `resolve/steps.py:740` needs a
  `StepRegistry`, declared *trusted* input.
- **Do the composed-fragment sites re-parse text that a fragment validator
  cleared?** §5.3's T1 second shape assumes yes for
  `quality/pattern.py::_transports_literal` and `resolve/build.py`. Reading them
  settles it, and a negative answer shrinks T1 rather than removing it.
- **Does the `fuzz` tier want a pytest marker?** The six tiers are pytest markers
  and this is not a pytest suite. Either a seventh marker over a replay test, or
  a `just` lane outside pytest entirely. D6.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | `EXPECTED` is exactly `(BloomeryError,)`, with no exemptions. §3 verified all 62 error classes descend from it, so any exemption would be a hole in the hierarchy rather than a concession to the fuzzer. Locked because widening it is the one edit that silently converts this lane into decoration. |
| 2 | `LOCKED` | The CLI oracle is **`main(argv) != EXIT_INTERNAL`**, not `code in (0,1,2)`. The exit-code table already distinguishes a crash from a refusal; the weaker assertion would fire on every genuine internal error and hide the contract that exists. Locked because it is the CLI's own stated contract, not this document's preference. |
| 3 | `LOCKED` | Widening `EXPECTED`, or adding a caught exception to any target, carries the same review bar as editing the error reference, and must land with either a translating fix or a recorded decision that the escape is intended. Consequence: a finding can never be closed by editing the harness alone. |
| 4 | `LOCKED` | Every confirmed finding becomes a checked-in test under an existing tier before the fuzz corpus is relied on to hold it. The corpus is unreviewed, unnamed and pruned; a finding living only there regresses silently. |
| 5 | `ASSUMED` | A finding expressible as a Hypothesis strategy over model objects goes to the property tier instead of gaining a fuzz target. Believed to keep the seam clean; depart if a class of finding is genuinely awkward in both and pick whichever is cheaper. |
| 6 | `OPEN` | Whether the lane is a seventh pytest marker or a `just` lane outside pytest. The six tiers are markers, but a libFuzzer target is not a pytest test; a marker would cover only a replay test over the corpus. Settled by whether RFC 0072's replay job wants to be `pytest -m fuzz`. |
| 7 | `OPEN` | Whether the two narrow-handler sites (`evidence.py:824`, `resolve/steps.py:740`) gain `RecursionError` or a depth limit raising a named error. The second matches `FilterTooComplex`, which is the corpus's existing answer to unbounded nesting, and is the better shape wherever the reproduction shows authored input can reach it; the first is right where it cannot and the fix is hygiene. Decide per site from its reproduction — `evidence.py` reads an authored project, `resolve/steps.py` reads a trusted registry — and log both. |
| 8 | `ASSUMED` | Targets are built in §5.3's order and none is written before the previous one has run. Assumed rather than locked because a cheap target discovered mid-execution may be worth taking out of order. |

## 12. Phasing

- **P1 — the harness and T1.** `fuzz/_harness.py`, fixtures, `fuzz_parse_doors.py`,
  seeds, dictionary, the `just` lane, `atheris` in the dev group. **Measure the
  stack depth at each of the thirteen sites under a real compile first** (§10) —
  one instrumented run, and it tells the rest of the phase which sites are real.
  Then reproduce the narrow-handler asymmetries (D7), fix them, and check that T1
  finds each when its fix is reverted — a target that cannot catch the defect that motivated
  it is not finished. Ships the `pages/docs/contributing/fuzzing.md` page. **Self-contained:
  useful, and complete, with no CI.**
- **P2 — T2 and T3.** The CLI oracle and the spec-layer target. `fuzz_cli.py` is
  small enough to be nearly free once the harness exists.
- **P3 — the promise targets.** T4 and T5, the in-process half of determinism.
  The cross-process half is RFC 0072's replay job; landing P3 first means that job
  has targets to replay when it arrives.
- **P4 — T6.** Demand-gated on the planner surface settling.

RFC 0072 is gated on P1 alone: there is no point running in CI what has not run
on a laptop. RFC 0073 is gated on P3, since it needs a seeded, exercised harness
to be worth measuring against.
