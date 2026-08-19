# RFC 0028 — `timestamp` is zoneless UTC, on every port

- **Status:** 📝 Draft — the defect is measured on all three engines and the fix
  is determined by an existing contract rather than chosen. One decision (D5)
  is open.
- **Scope:** Making `to_utc` produce what `timestamp` is documented to be — a
  **zoneless UTC** value — instead of a zone-aware one whose derived dates
  depend on something the spec never said. Touches
  `transforms/_builtins.py` (`to_utc`), all three ports' `render`, every golden
  holding a `to_utc`, and the Iceberg column type in `examples/lakehouse/`.
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
stripped of its zone at the point it enters the type — inside `to_utc`, which is
the only door.

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
| **D5** | Whether an emit-time check should assert that a silver column's rendered type matches its declared physical type. It would have caught this class at the source rather than by measurement, and it is a larger piece of machinery than this fix. | `OPEN` |

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
