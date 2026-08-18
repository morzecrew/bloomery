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

There are no floats. A `decimal` stays exact end to end, and nothing in the IR or on an
emission path is ever a binary float.

## Where the ports spell things differently

All three declare every capability, so nothing here is a feature gap. These are the
places one engine needs different SQL for the same meaning, and the port supplies it —
the reason a spec compiles to different text without meaning anything different.

| Construct | `duckdb` | `postgres` | `trino` |
|---|---|---|---|
| Zone interpretation (`to_utc`) | `x AT TIME ZONE 'Europe/Berlin'` | `x AT TIME ZONE 'Europe/Berlin'` | `WITH_TIMEZONE(x, 'Europe/Berlin')` |
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

## Divergences worth knowing before you pick

Two engine behaviours differ in ways a spec cannot see. Both are the same shape: one
spelling, two meanings, and no error to tell you which you got.

### `parse_ts: ISO8601` does not accept the `T` separator on Trino

`TRY_CAST('2026-01-06T12:00:00' AS TIMESTAMP)` is `NULL` on Trino and a timestamp on
DuckDB and PostgreSQL. Trino takes only the space-separated spelling.

**No error is raised for this, which is why it is here rather than in
[Errors](errors.md).** On an entity outside the quality system it is a silent NULL.
Inside it, it is worse and louder: the generated `coercible` rule reads "the projection
is NULL although the source was not" as a coercion failure, so every row of that source
is quarantined and the diagnosis points at data that was fine.

Until this is fixed, write space-separated timestamps in bronze if you compile for
Trino, or map the column with a chain that does not end in an ISO parse. The design is
[RFC 0027](https://github.com/morzecrew/bloomery/blob/main/rfcs/0027-iso8601-timestamps-across-dialects.md);
the fix changes the emitted text for every project using the transform, which is why it
is not a patch.

### `to_utc` reading its zone backwards on Trino — fixed

Trino now renders `with_timezone`, and all three ports agree that a 12:00 value read as
`Europe/Berlin` is the instant 11:00Z. Before that fix Trino promoted with the *session*
zone and left the instant unchanged, so if you built tables on an earlier version, the
timestamps in them moved when you upgraded.

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
