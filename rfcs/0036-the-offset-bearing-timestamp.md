# RFC 0036 — The offset-bearing timestamp

- **Status:** 🚧 In progress — **shipped; retired one change from now.** Every decision
  below is built and under test, and §12's single phase landed whole. It stays live only
  because a retirement row has to name a commit that already holds this document and is
  reachable from `main`, and no such commit exists until the change that ships it lands
  ([`RETIRED.md`](RETIRED.md) argues why that cannot be the deleting commit). Rows added
  by execution cite [`logs/T-0013.md`](../logs/T-0013.md).
- **Scope:** One expression, in one place: the guard `strip_iso_text` wraps around
  every `parse_ts: ISO8601` cast so that text carrying a **numeric UTC offset** yields
  NULL instead of a truncated wall clock. No spec-layer surface, no IR change, no new
  transform, no per-port divergence — `src/bloomery/dialects/base.py` is the only
  source file the fix touches, and the ports inherit it by already calling that
  function. What it changes for a user is one class of value: an input the current
  compiler answers *wrongly* becomes an input it refuses, which the existing
  `coercible` rule, reject table and D21 metadata audit already know how to report.
- **Related:** [`src/bloomery/dialects/base.py`](../src/bloomery/dialects/base.py),
  [`src/bloomery/transforms/_builtins.py`](../src/bloomery/transforms/_builtins.py),
  RFC 0027 (the ISO-text marker), RFC 0028 (zoneless UTC), RFC 0029 (transform types),
  RFC 0016 D21 (the ingestion-metadata audit).
- **Origin:** `logs/T-0012.md` F-9 — raised in review of PR #73, measured, and left
  open there because the fix is a contract question rather than a bug fix.

---

## 1. Summary

`parse_ts: ISO8601` parses a **local wall clock**; `to_utc` is the only door into the
always-UTC `timestamp` type (RFC 0028). Text that carries a numeric offset —
`2026-01-06T12:00:00+01:00` — says something the contract does not let it say, and
every engine bloomery targets resolves that contradiction the same silent way: it
throws the offset away and keeps the wall clock. The instant is wrong by the offset
and nothing reports it.

This RFC makes that input NULL. One `CASE WHEN` inside `strip_iso_text`, refusing text
whose eleventh character onward contains `+` or `-`, on every port at once. A `Z`
suffix is deliberately *kept*: it names the same zone the target type is in, so
truncating it loses nothing.

## 2. Motivation

Measured 2026-09-03 on `postgres:16-alpine`, `trinodb/trino:483` and DuckDB, casting
the text `parse_ts: ISO8601` emits a cast for:

| Input | PostgreSQL | Trino | DuckDB | Correct instant |
| --- | --- | --- | --- | --- |
| `2026-01-06T12:00:00` | `12:00` | `12:00` | `12:00` | `12:00` — in contract |
| `2026-01-06T12:00:00Z` | `12:00` | `12:00` | `12:00` | `12:00` |
| `2026-01-06T12:00:00+01:00` | `12:00` | `12:00` | `12:00` | **`11:00`** |
| `2026-01-06T12:00:00-05:00` | `12:00` | `12:00` | `12:00` | **`17:00`** |

The last two rows are this project's worst failure class stated as a measurement: the
pipeline runs, the audits pass, the mart aggregates, and the number is off by the
offset. Nothing in the compiler, the generated audits or the quality system can see
it, because every layer downstream of the cast is looking at a timestamp that parsed
fine.

**F-9 recorded this as a Trino defect. It is not** — the table above is the correction.
Trino was where a reviewer found it, and the `T`-separator work on that branch made
Trino the engine under a microscope; the truncation is uniform across all three, which
also means the fix cannot live in a port.

## 3. Current state

`parse_ts` with the format name `ISO8601` lowers to a cast wrapped in a marker
(`transforms/_builtins.py:parse_ts`):

```python
if fmt == _ISO8601:
    return exp.cast(iso_text(col), exp.DataType.build("TIMESTAMP"))
```

The marker exists because the engines disagree about their own casts and the IR
carries canonical text, so by emit time nothing else distinguishes an ISO parse from
any other cast (RFC 0027 §3). Every port must call `strip_iso_text`, and one that does
not is refused at render rather than left to emit an undefined function
(`dialects/base.py:305`).

That gives this change a single site. `strip_iso_text` already receives, per port, the
one expression that *is* the ISO parse:

```python
def replace(child: Expression) -> Expression:
    if isinstance(child, exp.Anonymous) and child.name.upper() == ISO_TEXT_MARKER:
        return spelling(child.expressions[0])
    return child
```

Three ports call it — DuckDB and PostgreSQL with `lambda text: text`, Trino with
`space_separated`, which casts to VARCHAR and replaces both ISO separators. RFC 0016
D21's ingestion-metadata audit is the fourth caller of `iso_text` and reaches the same
rewrite (`emit/lower/silver.py:_uncastable_ingested_at`).

`parse_date: ISO8601` is deliberately **not** marked, on engine-tier evidence recorded
in its own comment, and this RFC does not change that: an ISO *date* has no time and
therefore no offset.

## 4. Goals / Non-goals

**Goals**

- An offset-bearing input to `parse_ts: ISO8601` produces NULL rather than a wrong
  instant, identically on every port.
- The refusal is visible through machinery that already exists: the implicit
  `coercible` rule on a quality-carrying entity, the reject table under
  `quarantine:`, and D21's blocking metadata audit for `_ingested_at`.
- Nothing in contract changes value. Zoneless text, `Z`-suffixed text, bare dates and
  the space separator emit and evaluate exactly as they do today.

**Non-goals**

- **Converting the offset to the correct instant.** §5.3.
- **A spec-level way to declare that a source stamps instants.** §8 — designed far
  enough to show it is reachable, demand-gated like RFC 0024 D31.
- **Refusing `Z`.** §5.2 — and the residue that leaves is named in §9.
- **Anything about `parse_date`.** No time, no offset.

## 5. Design

### 5.1 The guard, and where it lives

`strip_iso_text` wraps `spelling(inner)` instead of returning it:

```python
CASE
  WHEN SUBSTRING(<text> FROM 11) LIKE '%+%' OR SUBSTRING(<text> FROM 11) LIKE '%-%'
  THEN NULL
  ELSE <spelling(text)>
END
```

Position 11 is the first character after an ISO calendar date (`YYYY-MM-DD` is ten
characters), so every `-` belonging to the date is behind the window and every `+` or
`-` inside it belongs to a zone offset. A bare date leaves the window empty and matches
nothing; a NULL input leaves the predicate NULL, falls to `ELSE`, and casts to NULL as
it does today.

`SUBSTRING` and `LIKE` are chosen over a regex because they need no per-port spelling:
SQLGlot renders them as `SUBSTRING(x, 11)` on DuckDB, `SUBSTRING(x FROM 11)` on
PostgreSQL and `SUBSTR(x, 11)` on Trino, all native, and every engine's `LIKE` takes
`%`. The alternative — a regex predicate — is three function names and two escaping
dialects for the same answer.

**It lives in the shared function, not in the ports.** All three ports would otherwise
need the same guard, and the port that forgot it would be the one nobody runs
(`logs/T-0012.md` F-1 is that failure, with the partition clause). Putting it in
`strip_iso_text` also means a *future* port inherits the refusal by satisfying the
existing "every port must call this" rule, rather than by remembering a second one.

### 5.2 `Z` is kept, and why that is a line rather than an oversight

`Z` names UTC. The column being written is UTC and zoneless (RFC 0004 §5.1, RFC 0028),
so truncating a `Z` loses no information: the wall clock and the instant are the same
number. A numeric offset names a *different* zone, so truncating it loses exactly the
difference.

That is the whole of the distinction, and it is honest about what it does not cover:
`parse_ts: ISO8601` followed by `to_utc: "Europe/Paris"` over `Z`-stamped text is still
a wrong instant, because the author declared a zone the data contradicts. §9 carries it
as a named risk with the mechanism that would close it.

### 5.3 Why NULL and not the right answer

Reading the offset and converting to UTC is the fix a reviewer proposes first, and it
loses on two counts.

**It makes `parse_ts` mean two things depending on the bytes.** The same declaration
would read one row as a local clock and the next as an instant, and no reader of the
spec could say which. `to_utc` exists to make that statement once, in the spec, where a
person can see it.

**On Trino the obvious spelling is worse than the defect.** Measured under a session
zone of `Pacific/Kiritimati` (`logs/T-0012.md` F-9):

```
COALESCE(TRY(CAST(AT_TIMEZONE(FROM_ISO8601_TIMESTAMP(x), 'UTC') AS TIMESTAMP)), …)
'2026-01-06T12:00:00'  ->  2026-01-05 22:00:00
```

`FROM_ISO8601_TIMESTAMP` attaches the **session zone** to zoneless text, so that fix
reintroduces the reader-dependence RFC 0028 removed — for the common case, to repair
the rare one.

NULL is the project's existing spelling for "this text is not what the spec said it
was". It is what `coercible` reads, what `quarantine:` diverts, and what D21's audit
blocks on. One guard therefore makes the whole quality system able to see a problem it
could not previously be told about, with no new audit, no new rule kind and no new
reporting surface.

### Alternatives considered

- **Convert to the true instant.** §5.3. Loses the spec's ability to say what the text
  is, and on Trino the spelling that does it re-introduces session dependence.
- **A generated audit that reports offset-bearing rows** rather than NULLing them.
  Louder, and it does not stop the wrong number: an audit that reports while the
  pipeline writes 12:00 has still written 12:00. Under §5.1 the row is NULL, and an
  audit is what the author *adds* — `coercible` — if they want it blocking.
- **Refuse at compile time.** There is nothing to refuse: the offset is in the data,
  and the spec that reads it is legal.
- **A port-by-port guard.** §5.1.

## 6. Tests

- **Unit, per dialect** (`tests/unit/test_dialects/`): the rendered SQL for a
  `parse_ts: ISO8601` chain carries the guard on all three ports, and the marker still
  reaches none of them.
- **Execution (DuckDB)**: a bronze row per line of §2's table through a compiled
  entity, asserting the NULL for the two offset rows and the unchanged value for the
  other three.
- **Engine (PostgreSQL, Trino)**: the same table, executed — this is the tier that
  produced §2 and the only one that can keep it true. It joins
  `tests/engines/test_zoneless_utc.py`, whose subject is exactly this contract.
- **Quality**: an offset-bearing value on a `coercible`-carrying entity lands in the
  reject table naming the column, which is the claim §5.3 makes about the existing
  machinery.
- **Golden**: every `parse_ts: ISO8601` snapshot moves, on every target. That churn is
  the change being visible, and reviewing it is the point.

## 7. Docs

- `pages/docs/reference/transforms.md` — `parse_ts`'s row gains the sentence that an
  offset-bearing input is refused as NULL, beside the existing statement that it reads
  a local clock.
- `pages/docs/concepts/` wherever `to_utc` is introduced as the door into UTC: the
  refusal is the enforcement of that sentence, so it belongs next to it.
- **Migration honesty.** A project whose bronze carries offsets sees values become
  NULL on upgrade. That must be stated plainly in the changelog, with the two things
  the author can do — strip the offset upstream, or state the zone with `to_utc` once
  the source is normalised — rather than described as a bug fix with no user effect.

## 8. Out of scope

- **A format name for a source that stamps instants** — `ISO8601_INSTANT` or similar,
  parsing the offset and refusing zoneless text, the mirror image of what `ISO8601`
  becomes here. It is reachable (`FROM_ISO8601_TIMESTAMP` + `AT_TIMEZONE` on Trino,
  `::timestamptz AT TIME ZONE 'UTC'` on PostgreSQL and DuckDB) and it is **not built**,
  because no project has asked for it: the demand gate RFC 0024 D31 uses. Named as the
  door, not built.
- **`parse_date`.** §3.
- **The `Z`-plus-`to_utc` contradiction.** §5.2, §9.
- **Fractional seconds, leap seconds, `24:00`, week dates and ordinal dates.** The
  engines' own ISO handling, unchanged by this RFC in either direction.

## 9. Risks

- **A silent NULL is still silent.** On an entity with no `quality:` block, the wrong
  number becomes an absent one and nothing says so. That is strictly better — a NULL
  propagates as NULL rather than as a plausible figure — and it is not *good*. The
  mitigation is the one the project already ships: `coercible` is implicit on a
  quality-carrying entity, and D21's audit blocks for `_ingested_at`. Accepted, and it
  is the strongest argument for the §8 door when demand arrives.
- **`Z` with an explicit `to_utc:` stays wrong.** §5.2. Closing it needs the marker to
  carry whether a zone is stated later in the chain — the lowering knows, the renderer
  does not — which is a second marker and a change to RFC 0027's vocabulary. Named,
  not built.
- **Upgrade turns data into NULL.** §7's migration note. The compiler cannot detect it,
  because the offending value is in the data and not in the spec — so the changelog is
  the only place it can be said.
- **Read as "bloomery cannot handle offsets".** It can, once the spec can say so (§8).
  What it refuses is guessing which of two meanings a timestamp column has.

## 10. Unresolved questions

None blocking. §8's format name and §9's `Z`-plus-`to_utc` case are both deliberately
deferred with their mechanisms recorded, and neither changes the guard this RFC ships.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **`parse_ts: ISO8601` reads a local wall clock, and text carrying a numeric UTC offset is out of contract.** This is RFC 0028's contract restated at the boundary that enforces it, not a new rule: `to_utc` is the only door into UTC, so a value that states its own zone is telling the compiler something the declaration already claimed to know. Locking it is what makes §5.3's refusal a consequence rather than a preference — an implementation that "helpfully" converted would be contradicting the spec layer, not extending it. |
| 2 | `LOCKED` | **Out-of-contract text becomes NULL; it is never converted and never raises.** NULL is the project's existing spelling for text that is not what the spec said it was, which is why this needs no new reporting surface: `coercible`, the reject table and D21's audit all already read it. Raising was rejected because the offending value is one row's bytes and a compiler that stops the pipeline on one row has no way back; converting was rejected in §5.3 on two independent grounds, one of them measured. Consequence: on an entity with no `quality:` block the refusal is silent, which §9 accepts and §8's door is the answer to. |
| 3 | `LOCKED` | **The guard lives in `strip_iso_text`, once, and every port inherits it.** The ports already must call that function or be refused at render (`dialects/base.py:305`), so this is the one place where "every target got the fix" is enforced by something other than memory. A per-port guard would land three times and drift in the copy no tier runs — the failure `logs/T-0012.md` F-1 recorded with D34's partition clause, forty lines from a lowering that had the right shape. |
| 4 | `ASSUMED` | **A `Z` suffix is kept and truncated as it is today.** `Z` names UTC, the target type *is* UTC and zoneless, so the wall clock and the instant are the same number and nothing is lost — where a numeric offset loses exactly the difference between them. Not `LOCKED`, because the reasoning holds only while no `to_utc:` follows in the chain (§5.2): with one, the author has declared a zone the data contradicts, and that case stays wrong. Departing here means refusing `Z` too, which needs §8's door built first — there is otherwise no legal spelling for the commonest bronze timestamp there is. |
| 5 | `ASSUMED` | **Detection is `SUBSTRING(x, 11)` plus two `LIKE`s, not a regex.** Portable with no per-port spelling and no escaping dialect, and correct for every ISO 8601 form these engines parse: the ten-character calendar date is the only place a `-` can appear innocently. Departing means a regex, and the cost of departing is three function names — `regexp_like`, `regexp_matches`, `~` — for the same boolean. |
| 6 | `ASSUMED` | **F-9's framing is corrected in the record: the truncation is uniform across PostgreSQL, Trino and DuckDB, not a Trino divergence.** It matters because it decides where the fix may live: a real divergence would belong in `dialects/trino.py`, and shipping it there would have left the other two ports wrong while a green engine tier said otherwise. *Recorded here rather than by amending the log, which is append-only.* |
| 7 | `ASSUMED` | **The detection window is taken over an explicit `VARCHAR` cast, refining D5.** D5 wrote the predicate as `SUBSTRING(x, 11)` over the marked operand, which is text in a transform chain by `parse_ts`'s declared input type — but the marker's *other* caller is RFC 0016 D21's metadata audit, where it sits on a bronze column typed however the project landed it. Measured: none of the three engines plans `SUBSTRING(<timestamp>, 11)`, so the guard as D5 spelled it would refuse to **compile** the audit rather than refuse the value, on the one column no `coercible` rule can reach — a check that stops checking, which is the failure this project ranks worst. It is the same totality the Trino port bought with the cast before its own `replace`, and a guard one node above it has to buy it too or the port's is undone. *Added by execution 2026-09-03 — see logs/T-0013.md (F-1), which carries the binder error.* |
| 8 | `ASSUMED` | **The separator normalisation moves to a shared spelling and DuckDB starts calling it, departing from §8's "the engines' own ISO handling, unchanged by this RFC in either direction".** §8 excluded the separator question as RFC 0027's, and it is — but the exclusion was written believing the port comment that said DuckDB "takes both `2026-01-06T12:00:00` and the space-separated spelling, so there is nothing for this port to add". Measured, DuckDB *raises* on the lowercase `t` that ISO 8601 permits and that PostgreSQL and Trino both read: a plain cast aborts the run and a `TRY_CAST` quarantines the row. Keeping that out of scope would have shipped a guard against a wrong number beside an untouched abort, in the same expression, on the same input class. The Trino port's `space_separated` becomes `dialects.base.space_separated` and both ports call it — one body, since the two engines need the same one and a second copy diverges in whichever port a tier does not run. *Added by execution 2026-09-03 — see logs/T-0013.md (F-3), which carries the measurement, and F-6.* |

## 12. Phasing

One phase. The guard, its tests across four tiers, the golden churn and the docs land
together — there is no half of this worth shipping alone, and the golden diff is the
review surface.

The §8 door (`ISO8601_INSTANT`) is a separate RFC under a demand gate, and D4 records
that refusing `Z` waits on it.
