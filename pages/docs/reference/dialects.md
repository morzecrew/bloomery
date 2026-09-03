# Dialects

Three SQL dialects ship — `duckdb`, `postgres`, `trino` — and every emitter renders
through the same port, so the choice of dialect is independent of the choice of target.

## Shipped dialects

| `--dialect` | Port | Notes |
|---|---|---|
| `duckdb` | `DuckDBDialect` | The default in every example; runs in-process, so the execution test tier uses it |
| `postgres` | `PostgresDialect` | `variant` is `JSONB`, and `TRY_CAST` has no keyword — see below |
| `trino` | `TrinoDialect` | The federated engine; used by the lakehouse example over Iceberg |

Passing any other name is an `EmitError` naming the three. A fourth port is a
`register_dialect()` call away — the port protocol is public, and the capability flags
below exist so a new one refuses what it cannot express instead of approximating it.

## Physical types

The seven logical types, as each port spells them:

| Logical | `duckdb` | `postgres` | `trino` |
|---|---|---|---|
| `string` | `VARCHAR` | `TEXT` | `VARCHAR` |
| `int` | `BIGINT` | `BIGINT` | `BIGINT` |
| `decimal(p,s)` | `DECIMAL(p, s)` | `DECIMAL(p, s)` | `DECIMAL(p, s)` |
| `bool` | `BOOLEAN` | `BOOLEAN` | `BOOLEAN` |
| `date` | `DATE` | `DATE` | `DATE` |
| `timestamp` | `TIMESTAMP` | `TIMESTAMP` | `TIMESTAMP` |
| `variant` | `JSON` | `JSONB` | `JSON` |

`variant` is the only row where the choice carries meaning. Postgres maps to `JSONB` —
the binary, indexable, canonicalized form — rather than `JSON`, which is a text blob
preserving key order and duplicates, properties `variant` never promises.

There are no floats in the type system, and a `decimal` stays exact end to end — with one
named exception, `divide` on DuckDB, which that engine cannot express exactly. It is
described below rather than left to be discovered.

## Where the ports spell things differently

All three declare every capability, so nothing here is a feature gap. These are the
places one engine needs different SQL for the same meaning, and the port supplies it —
the reason a spec compiles to different text without meaning anything different.

| Construct | `duckdb` | `postgres` | `trino` |
|---|---|---|---|
| Zone interpretation (`to_utc`) | `x AT TIME ZONE 'Europe/Berlin' AT TIME ZONE 'UTC'` | same as DuckDB | `CAST(AT_TIMEZONE(WITH_TIMEZONE(x, 'Europe/Berlin'), 'UTC') AS TIMESTAMP)` |
| Null-on-failure cast (the `coercible` marker) | `TRY_CAST(x AS BIGINT)` | `CASE WHEN PG_INPUT_IS_VALID(x, 'BIGINT') THEN CAST(x AS BIGINT) END` | `TRY_CAST(x AS BIGINT)` |
| Nested read `$.payload.shipping.country` | `payload ->> '$.shipping.country'` | `JSON_EXTRACT_PATH_TEXT(CAST(payload AS JSON), 'shipping', 'country')` | `JSON_EXTRACT_SCALAR(payload, '$.shipping.country')` |
| `normalize` rule | `NFC_NORMALIZE(x)` | `NORMALIZE(x, NFC)` | `NORMALIZE(x, NFC)` |
| `reject_id` digest | `SHA256('v')` | `ENCODE(SHA256(CONVERT_TO('v', 'UTF8')), 'hex')` | `LOWER(TO_HEX(SHA256(TO_UTF8('v'))))` |
| Reject `raw` payload | `JSON_OBJECT('a', a)` | `JSON_BUILD_OBJECT('a', a)` | `JSON_OBJECT('a': a)` |

Four of those are not stylistic. Postgres has no `TRY_CAST` keyword, and SQLGlot renders
one as a plain `CAST` — which would turn "quarantine the uncastable row" into "abort the
run", so the port wraps the engine's own input parser instead of approximating it with a
regex. Trino's `sha256` takes and returns `varbinary`, so the plain spelling does not
even plan; its `to_hex` is uppercase, and `reject_id` has to agree across engines byte
for byte. Trino parses only the SQL-standard `JSON_OBJECT` spelling. DuckDB has no
`NORMALIZE` at all.

## Two divergences the ports absorb for you

Trino's engine differs from the other two in ways a spec cannot see, and both are the
same shape: one spelling, two meanings, and no error to tell you which you got. Neither
is a caveat you have to work around any more — the port closes both — but both are worth
knowing, because each moved data on upgrade.

### `parse_ts: ISO8601` and the `T` separator

ISO 8601 permits three spellings of the separator — `T`, `t`, and (by the profile most
tools follow) a space — and each engine takes a different subset:

| Input | DuckDB | PostgreSQL | Trino |
|---|---|---|---|
| `2026-01-06T12:00:00` | parses | parses | `NULL` |
| `2026-01-06t12:00:00` | **raises** | parses | `NULL` |
| `2026-01-06 12:00:00` | parses | parses | parses |

No error was ever raised for the Trino column. Outside the quality system it was a silent
NULL; inside it the generated `coercible` rule read "the projection is NULL although the
source was not" as a coercion failure, so **every row of the source was quarantined**
while the diagnosis pointed at data that was fine. DuckDB's lowercase cell is the loud
version of the same problem: a plain cast stops the run outright, and inside the quality
system it quarantines the row.

Both ports normalize the separator before the cast now, through the same function, so
every spelling parses and a value that is genuinely not a timestamp still fails as one.
The rewrite is applied to the text rather than to the cast, so it survives the cast
becoming a `TRY_CAST` for an entity in the quality system. PostgreSQL needs neither and
adds neither.

`parse_date: ISO8601` is deliberately *not* normalized. An ISO date has no `T`, and the
case that would need it — a full timestamp handed to a date parser — is not helped:
Trino cannot cast `2026-01-06 12:00:00` to `DATE` either, so rewriting only turns a NULL
into a hard `INVALID_CAST_ARGUMENT`.

The offset guard beside it is **not** a divergence and is not absorbed here: all three
engines truncate a `+01:00` identically, so the refusal lives in the shared rendering
path and every port inherits the same guard around whatever its own cast spelling is. It is documented with the transform, in
[Transforms](transforms.md#a-timestamp-that-states-its-own-offset).

### `to_utc`, the zone argument, and the zone that came back

Two problems, one after the other, both now closed.

Trino's `AT TIME ZONE` promotes a zoneless timestamp with the **session** zone before
converting, leaving the instant unchanged — so the zone argument moved nothing but the
display. Trino renders `with_timezone` instead, and all three ports agree that a 12:00
value read as `Europe/Berlin` is the instant 11:00Z.

Every engine's zone interpretation then returns a zone-*aware* value, while `timestamp`
is defined as always UTC and maps to a zoneless type. The instant was right and
everything derived from it read the display rule rather than the instant: on DuckDB and
PostgreSQL `date(ordered_at)` moved with the **reader's session zone**, and on Trino it
was the local date in **whatever zone the mapping named** — so two rows at one instant,
mapped from two shops in two zones, landed in different days. Each port now normalizes
to UTC and drops the zone, and the emitted column is the zoneless type the entity model
declared.

If you built tables on a version before either fix, the timestamps in them moved when you
upgraded, and any date bucket derived from a `to_utc` column moved with them. That is the
point, and it needs a restatement.

**Nothing will tell you that.** Both fixes live in port rendering, so the IR is
byte-identical across the upgrade and so is `project_fingerprint`; a
[`plan`](../how-to/evolve-a-spec.md) between the two versions is refused outright for
crossing `bloomery_ir_version`s, and would report no change even if it were not. The
emitted SQL is where the difference is.

So find the affected models yourself and rebuild them:

1. `grep -rl to_utc` your mapping specs. Every entity with a `to_utc` step is affected,
   and so is every mart reading one of its timestamp columns — including any date role
   bucketed from one.
2. Rebuild those from bronze rather than incrementally: `sqlmesh plan --restate-model`
   naming each, or `dbt run --full-refresh --select` over the same set. An incremental
   run only rewrites new partitions and leaves the old rows on the old semantics, which
   is worse than not upgrading — one column, two meanings, no boundary marked.
3. Rebuild downstream marts after the silver models, since a mart's date buckets are
   derived and will not move on their own.

Diff a sample before and after: a row whose local time is late in the day in a zone east
of UTC is the one that moves, and it moves by a whole day.

## Every transform produces the type it declares

A conformance battery probes every (transform, input type) pair the typechecker
admits against real DuckDB, PostgreSQL and Trino, and compares the engine's own
column type against the transform's declared output. It asserts set equality per
port, so a divergence that appears fails the suite and one that is repaired fails
it too until its row is deleted. **The register is empty**: on all three engines,
every transform now produces what it says it produces.

Getting there closed defects on all three ports — four transforms PostgreSQL
could not run at all, eight Trino cases where a `coalesce` or `nullif` literal
was not coerced to its column's type, a `parse_ts` format branch that stored a
different instant depending on who ran it, and decimal arithmetic that widened
past the tracked `(p, s)` everywhere. None of them had golden coverage: no
fixture used `json_path`, `divide`, `multiply`, `round` or `abs`, which is why
they survived.

One divergence remains and cannot be repaired here:

**`divide` is inexact on DuckDB.** The engine has no exact decimal division —
`/` is float division and `//` is integer division — so the division itself
happens in binary floating point, and what the port can do is narrow the result
back to the declared decimal. PostgreSQL and Trino divide exactly. The emitted
column has the right type on all three; only DuckDB's *value* has been through a
float, and only for `divide`.

If exactness matters on DuckDB, multiply by the reciprocal instead: `{multiply:
"0.01"}` rather than `{divide: 100}` stays in decimal arithmetic end to end. The
shipped examples do exactly that, and say why.

**A catalog recipe's `/` is inexact on every engine.** The `divide` transform is
marked so PostgreSQL and Trino keep it in exact decimal arithmetic, but a
recipe's `expr:` is parsed SQL, not a built transform, and carries no marker —
`expr: line_total / quantity` renders as `CAST(line_total AS DOUBLE PRECISION) /
quantity`, a binary-float division narrowed back to the declared decimal
(logs/T-0002.md D-004). The narrowing bounds the error the way DuckDB's `divide`
is bounded above; values needing more than ~15 significant digits can still
round. Marking a recipe's division exact needs operand types the recipe grammar
does not carry yet — until it does, prefer a `divide`/`multiply` transform chain
where the division must be exact, and keep recipe `expr:` division for
screen-precision derivations.

## Notes

- **The dialect is not the target.** `--target sqlmesh --dialect postgres` and
  `--target dbt --dialect postgres` share every line of dialect logic; a semantics bug
  cannot exist in only one target's SQL.
- **Rendering never mutates the neutral AST.** One expression tree is shared across
  ports, so each rewrite works on a copy — a port that edited in place would leave the
  next one rendering its neighbour's spelling.
- **Reserved identifiers are quoted on every port.** An entity named `order` emits
  `silver."order"` everywhere.
- **Capability flags are how a fourth dialect stays honest.** A port that cannot express
  a null-on-failure cast, an array, a text digest, Unicode normalization, or a JSON
  object refuses the constructs that need them rather than emitting something close.
  All three shipped ports declare all of them, so no project meets those refusals today;
  the test suite provokes them against a deliberately incapable port.
- The engine test tier runs the emitted SQL against real DuckDB, PostgreSQL and Trino
  containers, which is where claims on this page are checked.
