# Comparisons

Reproduction bundles behind [`MATRIX.md`](MATRIX.md), one per system per case, as RFC 0043
§3 lays them out:

```text
comparisons/<system>/<case>/
  README.md   config/   commands.txt   observed.txt   sources.md
```

`README.md` records the version, the date, and the exact question being tested. `config/` is
the system's own configuration, authored the way that system's documentation describes.
`commands.txt` is what was run; `observed.txt` is what came back, verbatim. `sources.md`
cites the feature set the configuration uses.

## What a cell claims

**A cell is a property of a tested configuration, never a property of a product** (D1). Read
every one as "at this version, on this date, with this configuration, the system did this" —
not as "system X cannot do Y". The difference is not politeness: a true cell quoted later as
a general statement is the failure mode this whole tree is arranged to prevent, and the
phrasing is the only thing preventing it.

Six values, from RFC 0043 §2:

| Value | Meaning |
|---|---|
| `NATIVE-PREVENT` | documented native semantics prevent the failure before a wrong answer is produced |
| `NATIVE-PLAN` | documented native semantics construct a correct plan |
| `RUNTIME-DETECT` | a native runtime test or audit can detect the bad result or data condition |
| `CUSTOM` | achievable only with project-authored test, model or SQL |
| `NOT-REPRESENTED` | the required semantic fact has no documented native representation found |
| `UNKNOWN` | research incomplete |

**No cell is filled from reputation or memory** (D2). An unrun cell says `UNKNOWN`, which is
an honest value; a guessed one is indistinguishable from a researched one once written down,
and one guess voids the table.

## Rows are the corpus's cases

Every row is an expectation of a case in
[`tests/fixtures/semantic_corpus/`](../tests/fixtures/semantic_corpus/) (RFC 0043 D4, RFC
0042). One set of cases keeps this table and the regression suite from becoming two accounts
of the same question. A row this matrix needs and the corpus does not carry is a **missing
corpus case** first.

A bundle reads its case's `schema/` and `data/` directly rather than copying them, so a
fixture edit cannot leave a bundle quietly measuring different rows.

## bloomery's column has a different shape, and why

Every other column is a bundle. bloomery's column cites
`tests/fixtures/semantic_corpus/<case>/expected/semantic_outcome.json` and the test that
executes it, `tests/execution/test_semantic_corpus.py` — which runs in the default suite, on
every commit, for all twelve cases.

This is not bloomery being held to a lighter standard (D3). It is held to a heavier one: a
bundle is run by hand when someone remembers, and the corpus is a gate. Building
`comparisons/bloomery/` beside it would duplicate the same question into a second account
that can drift from the first, which is exactly what D4 exists to prevent.

The standard D3 actually asks for is that bloomery's losses are published, and they are:
`009-null-denominator` and `011-timezone-boundary` are cells where bloomery compiles the
request and returns **the wrong number**, and they appear in the table as
`NOT-REPRESENTED`.

## Staleness

A cell pins a version and a date. It returns to `UNKNOWN` when the version it pins is no
longer the version the reproduction resolves, or when its check date is more than twelve
months old — whichever comes first. For a system this repository does not depend on, only
the date half applies and the bundle says so.

## Running a bundle

Every cell here is **manual** in RFC 0043 §7's sense: each bundle's `commands.txt` is the
exact invocation, run by hand from the repository root, and nothing schedules it. They are
not tests — no marker, no CI, no fixture contract. A bundle that stops working is a fact
about the tree or the pinned version having moved, and the first thing to re-read is the
date and version in its `README.md`.
