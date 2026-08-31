# Task logs

Departures taken while executing an RFC, one file per task, appended and never edited in
place.

**These are not RFCs.** They carry no number, have no status, and never appear in
[`rfcs/INDEX.md`](../rfcs/INDEX.md)'s table — that document links to this directory in
prose instead. They live outside `rfcs/` because an RFC's own prose may never be edited to
match what was built: doing that launders the flip and destroys the record that a decision
changed at all. A log entry **is** the amendment proposal; the author accepts it by
appending a row to the RFC's decision table, and that row cites the entry it came from.

| Task | Executed | Drift |
| --- | --- | --- |
| [T-0001](T-0001.md) | Retire RFC 0028; RFC 0029's readiness gate, which did not clear | 0 |
| [T-0002](T-0002.md) | RFC 0029 — transform types the engine agrees with | 2 |
| [T-0003](T-0003.md) | RFC 0026 — the dbt singular-test surface | 0 |
| [T-0004](T-0004.md) | RFC 0024 P1 — deterministic union merge | 0 |
| [T-0008](T-0008.md) | RFC 0032 — mapping identity | 0 |

## How to read an entry

Each entry is a fenced ```divergence block — the machine-checkable record — followed by
prose that carries the argument. The block's fields are fixed:

- **`decision`** cites the *spec's* identifier (`RFC 0029 D1`), or `unlisted` when no row
  covers the question. Entries have no identifiers of their own, so nothing here is ever
  renumbered; the `D-NNN` and `V-NNN` headings are historical, minted under the previous
  format and kept because source and tests cite them.
- **`grade`** is the grade that was in force **when the executor acted**, not what the
  current table says. A checker that re-resolved it at read time would rewrite the log's
  past every time someone re-graded a row.
- **`class`** answers one question: could this have been known before code existed? Each
  log reproduces the table, because the people who read these logs are executing nothing
  and a class name whose test lives in a skill file they do not have is a label they cannot
  check.
- **`action`** must be the one its grade licenses — `LOCKED` → `halted`, `ASSUMED` →
  `departed`, `OPEN`/`UNLISTED` → `decided`. Halting on an assumption fails as loudly as
  departing from a lock.

Prose between blocks is free, and the checker ignores it.

**`drift` should be zero, and a non-zero count is a finding against the executor rather
than against the document** — including the second half of that row, because an RFC's
evidence is written by the same hand that executes it. The two halves are not the same
failure, so an entry says which: an implementation that departed, or a claim that was not
true when it was made. Every log declares its count even at zero, because a missing count
and an honest zero read identically and only one of them is a claim.

## Checking

```bash
python3 .claude/skills/flag-dont-flip/scripts/log_check.py --log logs/T-0002.md --root .
```

It checks the schema, grade-to-action legality both ways, the declared drift count against
the entries classed `drift`, and that every citation resolves.

**Two entries in [T-0003](T-0003.md) fail the legality check, and the failure is the
point.** D-012 and D-013 each name a `LOCKED` row and did not halt. That is
[A-1](T-0003.md#self-audit--2026-08-20), recorded as open and awaiting the author's call —
the self-audit caught D-013 by hand, and adopting the checker caught D-012 as well. Until
the author settles it, `log_check.py` is not wired into `just quality`: a gate that is red
on arrival teaches people to skip it.

**No `tasks/*.json` files accompany these logs, so the silence check never runs.** That
check needs each `LOCKED` decision's declared `paths` — the area it governs — and for four
tasks executed against three since-retired RFCs those areas would be reconstructed now
rather than declared then. A guessed area produces both false silences and false clean
runs, which is exactly why the checker refuses to guess one. Tasks executed from here on
should ship a task file written *before* the work, not after.

## This directory replaced a single file

Until 2026-08-21 these entries lived in one `rfcs/EXECUTION-LOG.md`, with `D-NNN` numbers
running continuously across the corpus, plus a separate `rfcs/0024-DEVIATIONS.md` carrying
`V-NNN`. One shared log is a write hotspot the moment two tasks run at once, and continuous
numbering means every entry has an identifier that a reader has to keep unique. The split
is per task, which is the unit that actually executes.

Three things came out of the migration rather than out of any task:

- **[T-0002](T-0002.md) D-018.** Converting entries to a format whose evidence must be
  *locatable* meant checking evidence that had never been checked. D-002 records a
  compile-time refusal of an out-of-range `coalesce` literal; no such check exists, none
  was ever committed, and the runtime `ConversionException` D-002 says it prevents is
  reproducible today. Appended as a new entry with the drift count raised to 2 — not by
  editing D-002, which stands as written.
- **[T-0003](T-0003.md) D-012 is a second `LOCKED` departure**, alongside the one A-1
  already named. The previous format recorded grades in prose, where "touches D10
  (`LOCKED`)" and "did not halt" sit in different sentences and no one compares them.
- **[T-0004](T-0004.md) V-004 stopped being a divergence.** D21 asked for a refusal that
  already existed under RFC 0017, so nothing was decided and nothing departed. The three
  legal actions all presuppose a decision, so it is recorded as prose. The gap is in the
  vocabulary, not in the entry.
