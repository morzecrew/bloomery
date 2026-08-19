# RFC 0028 — `timestamp` is zoneless UTC, on every port

- **Status:** 🚧 In progress — every decision is settled and implemented. It is
  not retired yet for a mechanical reason worth stating: a retirement row must
  name a commit the document is readable at *and reachable from mainline*
  ([`RETIRED.md`](RETIRED.md) argues why), and this document has only ever
  existed on the branch that introduced it. It retires in the first change
  after that branch lands.
- **Scope:** Making `to_utc` produce what `timestamp` is documented to be — a
  **zoneless UTC** value — instead of a zone-aware one whose derived dates
  depend on something the spec never said. The normalization boundary is
  **port rendering**, per D2: the `to_utc` builder is unchanged and still emits
  a dialect-neutral `AtTimeZone`, and each port rewrites the whole
  interpretation on its way to SQL. Touches `dialects/base.py` (the shared
  `utc_from_zone` walk) and all three ports' `render`, every golden holding a
  `to_utc`, and the Iceberg column type in `examples/lakehouse/`.
  Adds no spec surface: the YAML does not change.
- **Related:**
  [`src/bloomery/transforms/_builtins.py`](../src/bloomery/transforms/_builtins.py)
  (`to_utc` and its stated meaning),
  [`src/bloomery/dialects/base.py`](../src/bloomery/dialects/base.py)
  (`scalar_types`, which declares `TIMESTAMP`), RFC 0004 §5.1 (`to_utc` is "the
  only door into the always-UTC `timestamp` type"), RFC 0008 D3 (fail loud,
  never diverge silently), RFC 0003 (no ambient input may reach output).
- **Origin:** Review of #38, where two reviewers observed that `with_timezone`
  returns a zone-aware type while `scalar_types` declares a zoneless one. That
  was recorded as a schema-tidiness question and deferred. Measuring it for this
  document showed it is not about schema.

---

## 1. Summary

`to_utc` means "interpret this zoneless local timestamp as being in `zone`", and
it is the only way a value enters bloomery's `timestamp` type — which RFC 0004
§5.1 defines as **always UTC**. The type map says the physical type is a zoneless
`TIMESTAMP` on all three ports.

The value it actually produces is zone-*aware* on all three. The instant is
right. Everything derived from it is not, and the failure differs per engine and
is silent on all of them:

- On **DuckDB** and **PostgreSQL** the value renders through the **reader's
  session zone**, so `date(ordered_at)` — which is what a mart's date role
  buckets by — changes with who is querying.
- On **Trino** the value carries the *mapping's* zone, so `date(ordered_at)` is
  the local date **in whatever zone that mapping named**. Two rows at the same
  instant, mapped from two shops in two zones, land in different days.

A merged entity is exactly where this bites: `revenue by ordered_day` over two
shops in different zones splits one instant across two buckets, and nothing
warns.

## 2. What was measured

The value under test is `to_utc('2026-01-06 23:30:00', 'Europe/Berlin')`, whose
instant is **22:30Z**.

| Engine | Produced type | Session | Value as rendered | `date(value)` |
| --- | --- | --- | --- | --- |
| DuckDB | `TIMESTAMP WITH TIME ZONE` | `UTC` | `2026-01-06 22:30:00+00` | `2026-01-06` |
| DuckDB | `TIMESTAMP WITH TIME ZONE` | `Pacific/Kiritimati` | `2026-01-07 12:30:00+14` | **`2026-01-07`** |
| PostgreSQL | `timestamp with time zone` | `UTC` | `2026-01-06 22:30:00+00` | `2026-01-06` |
| PostgreSQL | `timestamp with time zone` | `Pacific/Kiritimati` | `2026-01-07 12:30:00+14` | **`2026-01-07`** |
| Trino | `timestamp(3) with time zone` | either | `2026-01-06 23:30:00 Europe/Berlin` | `2026-01-06` |

And the Trino case that needs no session change at all — two mappings, one
instant, two days:

| Mapping | Value | `date(value)` |
| --- | --- | --- |
| `{to_utc: Europe/Berlin}` over `2026-01-06 23:30:00` | `… 23:30:00 Europe/Berlin` | `2026-01-06` |
| `{to_utc: Asia/Tokyo}` over `2026-01-07 07:30:00` | `… 07:30:00 Asia/Tokyo` | **`2026-01-07`** |

Both rows are the instant `2026-01-06 22:30:00 UTC` — confirmed by converting
each to UTC explicitly, which returns the same string for both.

**This is an ambient input reaching output** — the reader's session on two ports,
the author's zone argument on the third — which is what RFC 0003 exists to
forbid. It is not a rendering preference.

## 3. The fix, and why it is not a choice

`timestamp` is already defined as always UTC. A zone-aware value is not that; it
is an instant plus a display rule, and every consumer that derives a date, an
hour or a bucket reads the display rule. So the value is normalized to UTC and
stripped of its zone at the one step that puts a value into the type — the
`to_utc` step of a chain, which is the only door.

That step is a *neutral* `AtTimeZone` node, and normalizing it is the **port's**
job rather than the builder's (D2): the one meaning takes two spellings across
the three engines — DuckDB and PostgreSQL both render `AT TIME ZONE 'UTC'`,
byte for byte, while Trino needs a function-and-cast form — and a builder
produces dialect-neutral AST (RFC 0004 D7). One divergence is enough to make it
the port's job; the table below is what each renders. `dialects/base.py` walks
the tree for interpretations and each port supplies its own rewrite.

Each port has a spelling, each verified session-independent:

| Port | Spelling | Verified |
| --- | --- | --- |
| DuckDB | `<interpretation> AT TIME ZONE 'UTC'` → `TIMESTAMP` | `2026-01-06 22:30:00` under both sessions |
| PostgreSQL | `<interpretation> AT TIME ZONE 'UTC'` → `timestamp` | `2026-01-06 22:30:00` under both sessions |
| Trino | `CAST(AT_TIMEZONE(<interpretation>, 'UTC') AS TIMESTAMP)` | `2026-01-06 22:30:00` under both sessions |

Trino needs the extra cast because `at_timezone` stays zone-aware, and a bare
`CAST(tstz AS TIMESTAMP)` there keeps the value's *own* zone's wall clock —
`23:30`, the Berlin reading — which preserves the defect while looking like a
fix.

## 4. Decisions

| # | Decision | Grade |
| --- | --- | --- |
| **D1** | `to_utc` produces a **zoneless UTC** value. The type is already documented as always-UTC and the map already declares `TIMESTAMP`; producing a zone-aware value contradicts both. | `LOCKED` |
| **D2** | The normalization lives in the **ports**, not in the transform builder. The three spellings are one meaning, and a builder produces dialect-neutral AST (RFC 0004 D7). The neutral tree keeps carrying `AtTimeZone`; each port renders the whole interpretation. | `LOCKED` |
| **D3** | This is a **restating** change: artifacts change, spec meaning does not, and stored values move. A project that built tables before this has data whose derived dates were wrong; a restatement is the migration. | `LOCKED` |
| **D4** | No new spec surface. A per-column "keep the zone" escape hatch would reintroduce the ambiguity this removes, and nothing has asked for one. | `LOCKED` |
| **D5** | The check exists, and it is a **conformance battery at the engine tiers over the transform registry** — not an emit-time assertion. Emit has no engine to ask and no usable static model of one; and a type-shaped check at emit invites a cast-shaped fix, which would have made this defect's type right and its value no less wrong. §7 has the measurement. | `LOCKED` |

## 5. What "fixed" looks like

Not a rendering assertion. The rendering was never malformed — it is valid SQL on
every port and wrong about what it means.

The test that closes this is at the engine tier, twice over:

1. The same `to_utc` value queried under two different session zones yields the
   same derived date, on each engine.
2. Two mappings naming different zones over the same instant yield the **same**
   derived date on Trino.

Both fail today. The second is the one a merged entity would have shipped.

## 6. Not in scope

**A timestamp that should keep a zone.** Some domains want the local wall clock
preserved — a store's opening hour is 09:00 in its own city regardless of UTC.
bloomery has no type for that, and inventing one here would be designing a
feature under cover of a bug fix. If it is wanted it is a new logical type with
its own name, not a flag on this one.

**`_ingested_at` and other bronze-side casts.** Those are the caller's SQL, not
bloomery's; the ingestion contract types that column and nothing here changes it.

---

## 7. D5, decided: where a declared-vs-produced check can live

The question was whether emit should assert that a silver column's rendered
type matches its declared physical type. Three measurements say it cannot, and
one says where it can.

**Emit has nothing to ask.** Compilation does no I/O (RFC 0003), so the only
static model of an engine's type rules available is SQLGlot's annotator. Run
over the constructs the ports actually diverge on, it answers `UNKNOWN` for
`AtTimeZone` on DuckDB — the exact node this document is about. It would not
have caught the defect that prompted the question. Where it *does* answer, it
answers off an explicit `CAST` in the tree, which is bloomery's own claim read
back to itself.

**A type-shaped check invites a cast-shaped fix.** The obvious way to satisfy
such an assertion is to wrap the chain terminal in a cast to the declared type
— and `build.py` already does exactly that when the chain's terminal type
differs from the field's. But a cast converts; it does not assert. Wrapping the
old `to_utc` in `CAST(… AS TIMESTAMP)` yields `TIMESTAMP` on all three ports
while DuckDB and PostgreSQL still convert through the reader's session zone and
Trino still keeps the value's own zone's wall clock. The check would have gone
green over unchanged wrong data, and removed the type signal that eventually
exposed it.

**So the check asks the engine, per transform.** The declaration
(`TransformSpec.output_type`) and the construction (`TransformSpec.builder`)
sit next to each other and were never compared. Probing every (transform, input
type) pair the typechecker admits — over a real column, through the canonical
text round trip emit uses — gives the whole-column property by induction, and
covers transforms no fixture exercises.

**Necessary, not sufficient.** A type check could not have distinguished the
zone-aware value from a cast-repaired one, so §5's two value tests are the other
half and are now permanent rather than hand-run.

### What it found on its first run

Two defects, one of them fixed here:

- **`regex_extract` ignored its capture group on DuckDB and Trino.** The builder
  sets `group`; the canonical text round trip re-binds the third argument to
  `position`, and both generators then drop it, warning to a stderr nothing
  reads. `{regex_extract: [pattern, 1]}` returned the whole match. No fixture
  used the transform, so no golden showed it.
- **`divide` emits a binary float** — `CAST(x AS DOUBLE PRECISION) / n` on
  PostgreSQL, `CAST(x AS DOUBLE) / n` on Trino, and DOUBLE on DuckDB regardless
  — which RFC 0003 D5 forbids in an emission path, on the transform whose output
  is most often money. It is in three checked-in goldens, computing `unit_price`
  through a double and casting the result back to `DECIMAL(12, 4)`: the declared
  type right, the value through a float. **Not fixed here** — the flag that
  fixes it on two ports does not survive the canonical round trip, so it needs a
  neutral-text marker of the kind RFC 0027 D4 established, which is a design
  change. RFC 0029 carries it, with the rest of the register.

And 29 registered divergences across the three ports — decimal arithmetic that
widens past the (p, s) RFC 0004 §5.4 tracks, two functions PostgreSQL does not
define, two casts it refuses, `parse_ts`'s explicit-format branch returning
`timestamptz` there, deep JSON extraction returning `json` where `variant` is
`jsonb`, and eight Trino cases where a `coalesce` or `nullif` literal is not
coerced to the column's type. Each carries a reason and is asserted *exactly*:
a fix cannot land without deleting its row, and a regression cannot hide behind
a row that happens to describe it. RFC 0029 dispositions them.
