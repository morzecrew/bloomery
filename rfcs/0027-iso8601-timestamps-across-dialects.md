# RFC 0027 — ISO 8601 timestamps across dialects

- **Status:** 📝 Draft — the defect is measured and the constraint on the fix is
  settled; the shape of the fix is one open decision (D4). Nothing here is
  scheduled.
- **Scope:** Making `{parse_ts: ISO8601}` accept ISO 8601 on every shipping
  dialect. It does not on Trino: the ISO branch lowers to a bare
  `CAST(… AS TIMESTAMP)`, and Trino's cast rejects the `T` separator that
  ISO 8601 defines, returning NULL where DuckDB and PostgreSQL return a
  timestamp. Touches `transforms/_builtins.py` (`parse_ts`, `parse_date`),
  `dialects/{duckdb,postgres,trino}.py`, and every golden holding a lowered
  ISO parse. Adds no spec surface: the fix is invisible in the YAML.
  Deliberately does **not** touch offset-bearing text (`…+01:00`), which is a
  separate divergence recorded in §7.
- **Related:**
  [`src/bloomery/transforms/_builtins.py`](../src/bloomery/transforms/_builtins.py)
  (`parse_ts`, `parse_date`, and the `_ISO8601` branch),
  [`src/bloomery/dialects/trino.py`](../src/bloomery/dialects/trino.py)
  (the port that diverges, and the `AtTimeZone` rewrite that fixed its sibling),
  [`src/bloomery/dialects/postgres.py`](../src/bloomery/dialects/postgres.py)
  (the render-rewrite precedent),
  [`src/bloomery/ir/nodes.py`](../src/bloomery/ir/nodes.py) (`SqlExpr` — the
  canonical-text round-trip that constrains the whole design), RFC 0003 D2
  (expressions are held as canonical text and re-parsed at emit), RFC 0004 D7
  (transform builders produce dialect-neutral AST and never see a dialect),
  RFC 0008 D3 (fail loud, never degrade silently), RFC 0016 §5.2 (the
  `coercible` rule, which turns this defect from wrong data into no data).
- **Origin:** Building `examples/lakehouse/`. Every row of the CRM landed in the
  reject table at once — six of six — because the seed wrote `2026-01-04T08:00:00`
  and the generated `updated_at_coercible` audit is precisely "the projection is
  NULL although the source was not". The example was made to work by rewriting
  its own data to the space-separated spelling, which is a workaround and is
  labelled as one.

---

## 1. Summary

`{parse_ts: ISO8601}` names a standard. On Trino it does not implement it.

```
trino> SELECT TRY_CAST('2026-01-06T12:00:00' AS TIMESTAMP);   -- NULL
trino> SELECT TRY_CAST('2026-01-06 12:00:00' AS TIMESTAMP);   -- 2026-01-06 12:00:00
```

DuckDB and PostgreSQL accept both spellings. Trino accepts only the space
separator, which ISO 8601 permits by mutual agreement and never requires — so
the one spelling the argument's name most obviously promises is the one that
fails.

It fails *silently* in the ordinary case, producing NULL for a value that was
there. Inside the quality system it fails loudly and wrongly: the generated
`coercible` rule reads a NULL projection over a non-NULL source as a coercion
failure, quarantines the row, and the run reports every row of the source as
bad data. The diagnosis points at the data. The data was fine.

**This is the same class of defect as the `to_utc` inversion fixed alongside
this document, and it is not the same size.** That one was a one-port rendering
correction over an unambiguous neutral node. This one is constrained by an
architectural fact — the IR carries *text* — which removes the obvious fix and
makes the remaining options cost something. §3 is the whole argument.

## 2. What was measured

Against `trinodb/trino:483`, DuckDB 1.x in-process, and `postgres:16`, session
zone UTC throughout.

| Expression | DuckDB | PostgreSQL | Trino |
| --- | --- | --- | --- |
| `CAST('2026-01-06 12:00:00' AS TIMESTAMP)` | 12:00 | 12:00 | 12:00 |
| `CAST('2026-01-06T12:00:00' AS TIMESTAMP)` | 12:00 | 12:00 | **NULL** |
| `CAST('2026-01-06T12:00:00.123456' AS TIMESTAMP)` | 12:00.123456 | 12:00.123456 | **NULL** |
| `from_iso8601_timestamp('2026-01-06T12:00:00')` | — | — | 12:00 UTC, typed `timestamp(3) with time zone` |
| `from_iso8601_timestamp('2026-01-06 12:00:00')` | — | — | **NULL** |
| `CAST(REPLACE(x, 'T', ' ') AS TIMESTAMP)`, `x` text | 12:00 | 12:00 | 12:00 |
| `CAST(REPLACE(x, 'T', ' ') AS TIMESTAMP)`, `x` already `TIMESTAMP` | — | — | **type error** |

Three readings matter:

1. **Trino has the capability and spells it differently.**
   `from_iso8601_timestamp` parses the `T` form — and *only* the `T` form, and
   returns a different type. It is not a drop-in replacement for the cast; it is
   the other half of the same gap.
2. **`REPLACE` covers both spellings on all three ports** and is the shortest
   expression that does.
3. **`REPLACE` is not safe to apply blindly.** Its last row is why: a
   `CAST(… AS TIMESTAMP)` whose operand is already a timestamp becomes a type
   error, and emitted Trino artifacts contain such casts today —
   `CAST(_ingested_at AS TIMESTAMP)` over a column Iceberg stores as a
   timestamp, and `CAST(NULL AS TIMESTAMP)` in the typed-NULL arm of a union
   merge.

## 3. Why the `to_utc` fix does not generalise

The `to_utc` inversion was closed in `TrinoDialect.render` by rewriting
`exp.AtTimeZone` into `with_timezone(…)`. That worked because of a property
this defect does not have: **`AtTimeZone` is a node type with exactly one
producer in this codebase**, and it survives the round-trip that separates the
transform from the dialect.

That round-trip is the constraint. `SqlExpr` holds an expression as *canonical
dialect-neutral text* and re-parses it at emit (RFC 0003 D2):

```python
class SqlExpr:
    sql: str
    def ast(self) -> Expression:
        return _parse_sql(self.sql).copy()
```

So by the time any dialect sees an expression, everything that is not in the
text is gone. `placed_at AT TIME ZONE 'Europe/Berlin'` re-parses to `AtTimeZone`
and the rewrite finds it. `CAST(created_at AS TIMESTAMP)` re-parses to a `Cast`
that is **identical** to every other timestamp cast in the tree, whatever
produced it — a mapping's `parse_ts`, the ingestion-metadata contract, a typed
NULL in a union arm.

Marking the node at build time does not survive: a custom argument on the AST is
not in `node.sql()`, and `node.sql()` is what is stored. Provenance is not
recoverable at the port. **Any fix must therefore change what the canonical text
says**, or find a rewrite that is correct for every timestamp cast — and the
last row of §2's table shows there is no such rewrite.

This is not a flaw in RFC 0003 D2. Canonical text is what makes "same specs in ⇒
byte-identical artifacts out" checkable, and a fingerprint over an AST with
opaque annotations would be a worse guarantee. It simply means the fix lives at
the *neutral spelling*, not at the port.

## 4. Options

**(a) A neutral marker construct.** `parse_ts: ISO8601` builds a function call
no engine defines — `BLM_ISO_TIMESTAMP(x)` — and every dialect's `render`
rewrites it: DuckDB and PostgreSQL to `CAST(x AS TIMESTAMP)` unchanged, Trino to
the `REPLACE` form. Precisely scoped, because the marker has one producer and
means one thing. Fails loud on a fourth dialect, which renders an unknown
function rather than silently-wrong SQL — the `DialectFeature` philosophy
applied to a construct instead of a capability.
*Cost:* the canonical text of every ISO parse changes, so **every fingerprint
over a project using `parse_ts: ISO8601` changes**, and every golden with one
moves.

**(b) A neutral `REPLACE`.** `parse_ts: ISO8601` builds
`CAST(REPLACE(x, 'T', ' ') AS TIMESTAMP)` for everyone. No dialect changes at
all; `REPLACE` is in all three. Same fingerprint cost as (a), and it makes the
DuckDB and PostgreSQL artifacts carry a rewrite they never needed — a cost paid
in every reader's attention, forever, for one engine's parser.

**(c) A second transform.** Leave `parse_ts: ISO8601` alone and add
`parse_iso_ts`, correct everywhere, documenting the old spelling as
Trino-lossy. No fingerprint break for anyone who does not migrate. But it leaves
a whitelisted transform in the registry that does not do what its argument says,
which is the defect, preserved and given a name.

**(d) Refuse it on Trino.** `parse_ts: ISO8601` becomes an
`UnsupportedByTarget` on that dialect until one of the above lands. Honest by
RFC 0008 D3, and it breaks every project that currently uses the space-separated
spelling and works — punishing the people who already worked around the bug.

## 5. Decisions

| # | Decision | Grade |
| --- | --- | --- |
| **D1** | `{parse_ts: ISO8601}` must accept the `T` separator on every shipping dialect. The argument names a standard; a whitelisted transform that implements it on two ports of three is a defect in the transform, not a caveat for the docs. | `LOCKED` |
| **D2** | The fix may **not** be a blanket render-time rewrite of `CAST(… AS TIMESTAMP)` on Trino. Emitted artifacts already cast operands that are timestamps and NULLs, and `REPLACE` over either is a type error, not a no-op (§2). | `LOCKED` |
| **D3** | The fix lives in the **neutral spelling**, not at the port, because provenance does not survive the canonical-text round-trip (§3). Any option that needs the dialect to know a cast came from `parse_ts` is out. | `LOCKED` |
| **D4** | Which option of §4. The lean is **(a)**: it is the only one that keeps the DuckDB and PostgreSQL artifacts unchanged in meaning, keeps one producer for the construct, and makes a fourth dialect fail loud rather than quietly wrong. | `OPEN` |
| **D5** | Whatever lands is a **fingerprint-affecting change** for projects using `parse_ts: ISO8601`, and takes the stability treatment: a restating diff, not a breaking one — the artifacts change, the meaning of the spec does not. | `ASSUMED` |
| **D6** | `parse_date: ISO8601` is in scope with `parse_ts`. It lowers the same way, to `CAST(… AS DATE)`, and a date has no `T` — but the two are one branch in one builder, and fixing one while leaving the other reads as an oversight rather than a boundary. | `ASSUMED` |
| **D7** | Until this lands, the divergence is **documented, not refused**. (d) is the RFC 0008 D3-pure answer and it breaks working projects to punish a bug they already routed around; the projects that hit it hit it loudly, through the `coercible` rule, not silently. | `LOCKED` |

## 6. What "fixed" looks like

Not a unit test asserting a rendering. The rendering was never the thing that
was wrong — `CAST(x AS TIMESTAMP)` is valid Trino, it just does not do this.

The test that closes this is in the **engine tier**, where Trino actually runs:
land `2026-01-04T08:00:00` in a bronze column, map it with
`{parse_ts: ISO8601}`, and assert the silver row holds `2026-01-04 08:00:00` and
the reject table is empty. It fails today on the second half — the row is in the
reject table, quarantined by `updated_at_coercible` — which is exactly how the
defect was found and exactly what a reader needs to see.

`examples/lakehouse/seed/` reverts to the `T` spelling in the same change. It
writes space-separated timestamps today for one reason, and that reason is this
document.

## 7. Not in scope

**Offset-bearing text.** `2026-01-06T12:00:00+01:00` is also ISO 8601, and the
three ports disagree about it in a second, independent way: the cast drops or
converts the offset differently, and bloomery's `timestamp` is zoneless by
construction (RFC 0004 §5.1), so there is a modelling question underneath the
parsing one — what a zoneless type should do with a value that carries a zone.
The documented path today is `parse_ts` then `to_utc`, which presumes the text
had no offset. Fixing the separator does not touch this, and pretending
otherwise would let a much larger question ride in on a small fix.

**`measures:` on a non-additive metric.** Found in the same sweep and unrelated:
`MetricFlow` reads a mart's `measures:` as *what this mart serves* and emits a
ratio there as a metric, while the Cube emitter reads it as *what this mart
stores* and refuses the same spec — with a message asserting the guardrail stage
should already have caught it, which it does not and, on MetricFlow's reading,
should not. One under-specified word, two emitters, no refusal. It wants its own
document.
