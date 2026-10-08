# Dialects

Seven SQL dialects ship — `bigquery`, `databricks`, `duckdb`, `postgres`, `redshift`,
`snowflake`, `trino` — and every emitter renders through the same port, so the choice of
dialect is independent of the choice of target.

## Shipped dialects

| `--dialect` | Port | Notes |
|---|---|---|
| `duckdb` | `DuckDBDialect` | The default in every example; runs in-process, so the execution test tier uses it |
| `postgres` | `PostgresDialect` | `variant` is `JSONB`, and `TRY_CAST` has no keyword — see below |
| `redshift` | `RedshiftDialect` | `variant` is `SUPER`; the first port to withhold capabilities — `json_path`, `normalize` and arrays are refused, not approximated |
| `trino` | `TrinoDialect` | The federated engine; used by the lakehouse example over Iceberg |
| `snowflake` | `SnowflakeDialect` | The first cloud port; `timestamp` is `TIMESTAMP_NTZ` by name and every current instant is `SYSDATE()` — see below |
| `bigquery` | `BigQueryDialect` | `timestamp` is `DATETIME`, never the instant type; `decimal` lands on `NUMERIC` or `BIGNUMERIC` by its bounds; declares every capability |
| `databricks` | `DatabricksDialect` | Databricks SQL and nothing else — the port renders text and runs no Spark; `variant` is `STRING`, and there is no transaction |

Passing any other name is an `EmitError` naming the seven. An eighth port is a
`register_dialect()` call away — the port protocol is public, and the capability flags
below exist so a new one refuses what it cannot express instead of approximating it.

## Physical types

The seven logical types, as each port spells them:

| Logical | `duckdb` | `postgres` | `trino` | `redshift` | `snowflake` | `bigquery` | `databricks` |
|---|---|---|---|---|---|---|---|
| `string` | `VARCHAR` | `TEXT` | `VARCHAR` | `VARCHAR(MAX)` | `VARCHAR` | `STRING` | `STRING` |
| `int` | `BIGINT` | `BIGINT` | `BIGINT` | `BIGINT` | `NUMBER(38, 0)` | `INT64` | `BIGINT` |
| `decimal(p,s)` | `DECIMAL(p, s)` | `DECIMAL(p, s)` | `DECIMAL(p, s)` | `DECIMAL(p, s)` | `DECIMAL(p, s)`, `p` at most 38 | `NUMERIC(p, s)` while `s` ≤ 9 and `p − s` ≤ 29, else `BIGNUMERIC(p, s)` while `s` ≤ 38 and `p − s` ≤ 38; refused past both | `DECIMAL(p, s)`, `p` at most 38 |
| `bool` | `BOOLEAN` | `BOOLEAN` | `BOOLEAN` | `BOOLEAN` | `BOOLEAN` | `BOOL` | `BOOLEAN` |
| `date` | `DATE` | `DATE` | `DATE` | `DATE` | `DATE` | `DATE` | `DATE` |
| `timestamp` | `TIMESTAMP` | `TIMESTAMP` | `TIMESTAMP` | `TIMESTAMP` | `TIMESTAMP_NTZ` | `DATETIME` | `TIMESTAMP_NTZ` |
| `variant` | `JSON` | `JSONB` | `JSON` | `SUPER` | `VARIANT` | `JSON` | `STRING` |

`variant` is the only row where the choice carries meaning. Postgres maps to `JSONB` —
the binary, indexable, canonicalized form — rather than `JSON`, which is a text blob
preserving key order and duplicates, properties `variant` never promises. Redshift has no
`JSONB` and its `SUPER` is a different data model, navigated with PartiQL rather than with
`jsonb`'s operators, so that port refuses `json_path` instead of translating it.

Snowflake's column has three choices of its own. `int` is `NUMBER(38, 0)` because that is
what the engine stores — its `BIGINT` is a documented synonym for exactly that, not a
64-bit integer. A `decimal` past 38 digits of precision is refused at emit by name: the
engine has no wider fixed-point type to fall back to. And `timestamp` is spelled
`TIMESTAMP_NTZ` explicitly, never bare `TIMESTAMP`, which on Snowflake is an alias an
account or a session may point at the session-zoned `TIMESTAMP_LTZ` — the one type the
always-UTC zoneless `timestamp` must never become.

BigQuery's `timestamp` is `DATETIME`, chosen rather than inherited: GoogleSQL's `TIMESTAMP`
is an instant, read and written through a zone, and `DATETIME` is the zoneless wall clock
the always-UTC `timestamp` is defined as. Its `decimal` is placed by the declaration's
*integer* digits, `p − s`, and not by `p` alone, because GoogleSQL bounds a parameterized
type's precision relative to its scale: `decimal(38, 9)` fits `NUMERIC`, `decimal(30, 0)`
does not and lands on `BIGNUMERIC`, and a declaration past both bounds is refused rather
than widened into a type other than the one declared. Databricks spells `timestamp`
`TIMESTAMP_NTZ` for Snowflake's reason — its bare `TIMESTAMP` is session-zoned — and has no
JSON column type, so `variant` is `STRING` and its reads take the colon accessor,
`payload:shipping.country`.

The eighth logical type, `vector(scalar, dimensions)`, has no physical spelling on any
port and is refused by name: a vector column belongs to a retrieval target, not to a
warehouse's DDL (see [Retrieval](../concepts/retrieval.md)).

There are no floats in the type system, and a `decimal` stays exact end to end — with one
named exception, `divide` on DuckDB, which that engine cannot express exactly. It is
described below rather than left to be discovered.

## Where the ports spell things differently

DuckDB, Postgres, Trino and BigQuery declare every capability, so nothing in their
columns is a feature gap. `redshift` withholds three, and `snowflake` and `databricks` one
each — Unicode normalization, which none of the three engines has under any name, so a
`normalize` rule is refused at emit rather than rendered as a call the engine never
defined — and the cells they refuse are marked.
These are the places one engine needs different SQL for the same meaning, and the port
supplies it — the reason a spec compiles to different text without meaning anything
different.

| Construct | `duckdb` | `postgres` | `trino` | `redshift` | `snowflake` | `bigquery` | `databricks` |
|---|---|---|---|---|---|---|---|
| Zone interpretation (`to_utc`) | `x AT TIME ZONE 'Europe/Berlin' AT TIME ZONE 'UTC'` | same as DuckDB | `CAST(AT_TIMEZONE(WITH_TIMEZONE(x, 'Europe/Berlin'), 'UTC') AS TIMESTAMP)` | `CONVERT_TIMEZONE('Europe/Berlin', 'UTC', x)` | `CONVERT_TIMEZONE('Europe/Berlin', 'UTC', x)` | `DATETIME(TIMESTAMP(x, 'Europe/Berlin'), 'UTC')` | `CAST(TO_UTC_TIMESTAMP(x, 'Europe/Berlin') AS TIMESTAMP_NTZ)` |
| Null-on-failure cast (the `coercible` marker) | `TRY_CAST(x AS BIGINT)` | `CASE WHEN PG_INPUT_IS_VALID(x, 'BIGINT') THEN CAST(x AS BIGINT) END` | `TRY_CAST(x AS BIGINT)` | `TRY_CAST(x AS BIGINT)`, and `CASE WHEN CAN_JSON_PARSE(x) THEN JSON_PARSE(x) END` for `variant` | `TRY_CAST(CAST(x AS VARCHAR) AS NUMBER(38, 0))` | `SAFE_CAST(x AS INT64)` | `TRY_CAST(x AS BIGINT)` |
| Nested read `$.payload.shipping.country` | `payload ->> '$.shipping.country'` | `JSON_EXTRACT_PATH_TEXT(CAST(payload AS JSON), 'shipping', 'country')` | `JSON_EXTRACT_SCALAR(payload, '$.shipping.country')` | `JSON_EXTRACT_PATH_TEXT(payload, 'shipping', 'country', TRUE)` | `JSON_EXTRACT_PATH_TEXT(payload, 'shipping.country')` | `JSON_EXTRACT_SCALAR(payload, '$.shipping.country')` | `payload:shipping.country` |
| `normalize` rule | `NFC_NORMALIZE(x)` | `NORMALIZE(x, NFC)` | `NORMALIZE(x, NFC)` | **refused** — no `UNICODE_NORMALIZE` capability | **refused** — no NFC function | `NORMALIZE(x, NFC)` | **refused** — no NFC function |
| `reject_id` digest | `SHA256('v')` | `ENCODE(SHA256(CONVERT_TO('v', 'UTF8')), 'hex')` | `LOWER(TO_HEX(SHA256(TO_UTF8('v'))))` | `SHA2('v', 256)` | `SHA2('v', 256)` | `TO_HEX(SHA256('v'))` | `SHA2('v', 256)` |
| Reject `raw` payload | `JSON_OBJECT('a', a)` | `JSON_BUILD_OBJECT('a', a)` | `JSON_OBJECT('a': a)` | `OBJECT('a', a)` | `OBJECT_CONSTRUCT_KEEP_NULL('a', a)` | `JSON_OBJECT('a', a)` | `TO_JSON(NAMED_STRUCT('a', a))` |
| Current instant | `CURRENT_TIMESTAMP` | `CURRENT_TIMESTAMP` | `CURRENT_TIMESTAMP` | `CONVERT_TIMEZONE('UTC', CAST(GETDATE() AS TIMESTAMP WITH TIME ZONE))`, cast back | `SYSDATE()` | `CURRENT_DATETIME('UTC')` | `CAST(TO_UTC_TIMESTAMP(CURRENT_TIMESTAMP(), CURRENT_TIMEZONE()) AS TIMESTAMP_NTZ)` |
| Calendar row source (`dim_date`) | `GENERATE_SERIES(...)` | `GENERATE_SERIES(...)` | `UNNEST(SEQUENCE(...))` | a cross-joined ten-row generator numbered by `ROW_NUMBER()`, the day added to the date as an integer | `TABLE(GENERATOR(ROWCOUNT => n))` with `DATEADD` | `UNNEST(GENERATE_DATE_ARRAY(...))` | `EXPLODE(SEQUENCE(...))` |

Four of those are not stylistic. Postgres has no `TRY_CAST` keyword, and SQLGlot renders
one as a plain `CAST` — which would turn "quarantine the uncastable row" into "abort the
run", so the port wraps the engine's own input parser instead of approximating it with a
regex. Trino's `sha256` takes and returns `varbinary`, so the plain spelling does not
even plan; its `to_hex` is uppercase, and `reject_id` has to agree across engines byte
for byte. Trino parses only the SQL-standard `JSON_OBJECT` spelling. DuckDB has no
`NORMALIZE` at all.

Snowflake adds four of its own, none stylistic either. Its `TRY_CAST` accepts a string
source only and SQLGlot renders it as a plain `CAST` otherwise, so the port casts the
operand to `VARCHAR` first. Its object builder drops any pair whose value is NULL, which
would make a quarantined payload disagree with every other port's, so the reject payload
uses the `_KEEP_NULL` variant. Its `CURRENT_TIMESTAMP` is session-zoned, so every current
instant — including the replay's `resolved_at` stamps — is `SYSDATE()`, the engine's UTC
instant already typed `TIMESTAMP_NTZ`. And SQLGlot spells the calendar's series as
`ARRAY_GENERATE_RANGE(...)`, a scalar function the engine cannot select from, so the port
renders the row generator instead, with the count read from the calendar's own bounds.

Redshift's whole column is its own for the same reason: its `AT TIME ZONE` promotes a
zoneless value through the *session* zone the way Trino's does, so the PostgreSQL chain
does not cancel and the three-argument `CONVERT_TIMEZONE(source, target, ts)` says it in
one call; it defines no `JSON_OBJECT`, so the `SUPER` constructor `OBJECT` carries the
reject payload; and a neutral `CAST(x AS JSON)` renders there as a **no-op**, which is why
`variant` construction is `JSON_PARSE` and its null-on-failure form has to be guarded by
`CAN_JSON_PARSE` — `SUPER` has no `TRY_CAST`. The port inherits none of PostgreSQL's
rewrites: each was audited against Redshift separately, and the two that survived are
imported as named helpers. The nested read in that table is a bronze path, declared
`string`, and `JSON_EXTRACT_PATH_TEXT` over a text column returns text correctly, so the
port renders it — with `null_if_invalid` set, so a payload that is not JSON yields NULL
for the `coercible` rule to read rather than aborting the load; what the port refuses is
the `json_path` transform's *variant* extraction, which would declare `variant` and
produce a string.

BigQuery's column is decided rather than inherited too. `SAFE_CAST` is its null-on-failure
cast and holds under the quality system's lowering, including the cast of a wide decimal,
which becomes `SAFE_CAST(x AS BIGNUMERIC)` rather than a `NUMERIC` the value cannot fit.
GoogleSQL's `IN` takes a single-column subquery only, so the replay's resolution `UPDATE`,
which marks superseded reject rows with a row-value `IN` on every other port, is rewritten
to a correlated `EXISTS` with the update's target aliased `_row`. Its `REGEXP_EXTRACT`
addresses one capturing group, so a `regexp` transform naming another is refused by name.
And its RE2 refuses a repetition bound above 1000, so a `pattern` rule's `{1001}` is
refused at parse as outside the portable regex subset — on every dialect, since DuckDB and
Trino are RE2 engines too. A bare `BEGIN` opens a script block there, so
`begin_transaction` is `BEGIN TRANSACTION`.

Databricks has no transaction at all: every statement is its own Delta commit and `BEGIN`
is rejected, so `begin_transaction` is the empty string and the dbt replay envelope opens
and commits nothing — its header says each statement commits on its own, and that a
failure part-way leaves the earlier ones committed. Its `TO_UTC_TIMESTAMP(x, zone)` reads
a wall clock *in* the named zone and returns the UTC one, the direction `to_utc` means
(SQLGlot's `FROM_UTC_TIMESTAMP` runs the other way), and the same call around
`CURRENT_TIMESTAMP()` with `CURRENT_TIMEZONE()` is how the session's clock becomes UTC's
for every current instant, the replay's `resolved_at` stamps included. `DATE_TRUNC('DAY',
x)` replaces SQLGlot's `TRUNC`, and reserved names are backticked.

### Arrays, and the shape `_quality_flags` takes without them

`redshift` does **not** declare `DialectFeature.ARRAY`. Redshift's `SUPER` can hold an
array and `ARRAY()` constructs one, but no table column can be declared `VARCHAR[]`, and
a capability flag names what the engine can express as a column — so the port withholds
it rather than emitting a declaration Redshift rejects.

That choice is visible in the emitted artifacts. `_quality_flags` and `failed_rules`
share one physical contract with two lowerings, and this port takes the second:

| | array dialects (`duckdb`, `postgres`, `trino`, `snowflake`, `bigquery`, `databricks`) | `redshift` |
|---|---|---|
| A flagged row | `['email_shape', 'positive_total']` | `'email_shape,positive_total'` |
| A clean row | the empty array, never NULL | the empty string, never NULL |
| Order | lexicographic by rule name | lexicographic by rule name |
| `_quality_ok` | derived from the array's length | derived from the delimited string |

Both shapes carry the same flag set — rule names are identifier-constrained at parse, so
the comma needs no escaping, and the dialect-matrix tier asserts set equality across the
two lowerings. What differs is what a consumer writes: on `redshift`, a query asking
whether a row carries a given flag matches a delimited member rather than indexing an
array, and the reject table's `failed_rules` carries the same delimited text. A mart's
`has_quality_flags` is generated per shape and needs nothing from the reader.

## Two divergences the ports absorb for you

Both of these are engine behaviour a spec cannot see, and both are the same shape: one
spelling, two meanings, and no error to tell you which you got. Trino is in both; DuckDB
is in the first and Redshift shares Trino's rule in the second. Neither
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

Snowflake needs no fourth column: its port normalizes the separator the same way before
any cast, the strictly-safe choice until the live corpus shows which raw spellings its
`AUTO` format would have parsed on its own. BigQuery and Databricks normalize it the same
way; BigQuery also strips a trailing `Z`, which its `DATETIME` parser does not take, and
Databricks needs the rewrite most, since under ANSI mode a lowercase `t` raises there
rather than returning NULL.

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
adds neither, and neither does Redshift — its datetime input takes the `T` separator the
way PostgreSQL's does, so that port carries no rewrite here.

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
display. Trino renders `with_timezone` instead, and every shipped port agrees that a 12:00
value read as `Europe/Berlin` is the instant 11:00Z — Redshift shares Trino's promotion
rule, which is why its port renders the three-argument `CONVERT_TIMEZONE` rather than the
PostgreSQL chain.

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
every transform now produces what it says it produces. The four cloud ports are not
probed by it — no tier runs those engines in a container — so their spellings are pinned
at the rendering level, and each has a lane against the engine's own compiler that says
whether the rendered statements analyse: `EXPLAIN USING JSON` on Snowflake and a dry run
on BigQuery, both on `main` under repository credentials; `EXPLAIN EXTENDED` and
`DESCRIBE QUERY` on a Databricks warehouse, weekly; and `EXPLAIN` on a Redshift cluster,
which no workflow runs today. A claim on this page about one of those four is a
rendering-level claim unless its lane made it.

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

**A catalog recipe's operands are typed before its `expr:` is evaluated.** Each
operand carries the type the recipe's `types:` names it, or the declared type of
the canonical field of the same name; an operand under `+`, `-`, `*` or `/` that
neither types is refused at compile time, naming the `types:` entry that fixes it.
The cast is what keeps a text-shaped extraction from reaching an engine as text,
where the dialect would infer a type of its own.

**A catalog recipe's `/` divides as `divide` does.** A recipe's `expr:` is parsed
SQL rather than a built transform, so the compiler lowers every `/` in it, nested
ones included, through the marker the `divide` transform carries. The dividend is
cast to a decimal at least as wide as BigQuery's `NUMERIC` — 29 integer digits and
9 fractional — so two integer operands divide fractionally, a dividend wider than
the quotient does not overflow, and a nested quotient is not rounded before the
next division: `expr: line_total / quantity` into `decimal(12, 4)` renders as
`CAST(line_total AS DECIMAL(38, 9)) / quantity`, narrowed to `decimal(12, 4)` once,
at the end. It is exact on PostgreSQL and Trino and goes through a float on
DuckDB, exactly as `divide` does above.

## Notes

- **The dialect is not the target.** `--target sqlmesh --dialect postgres` and
  `--target dbt --dialect postgres` share every line of dialect logic; a semantics bug
  cannot exist in only one target's SQL.
- **Rendering never mutates the neutral AST.** One expression tree is shared across
  ports, so each rewrite works on a copy — a port that edited in place would leave the
  next one rendering its neighbour's spelling.
- **Reserved identifiers are quoted on every port.** An entity named `order` emits
  `silver."order"` on DuckDB, PostgreSQL, Redshift and Trino, `silver."ORDER"` on
  Snowflake, where an unquoted name folds to uppercase and a quoted one is taken verbatim —
  the folded spelling is the one that names the same object as the unquoted model name —
  and ``silver.`order` `` on BigQuery and Databricks, whose quoting character is the
  backtick.
- **Capability flags are how a port stays honest.** A port that cannot express a
  null-on-failure cast, an array, a text digest, Unicode normalization, or a JSON object
  refuses the constructs that need them rather than emitting something close. `duckdb`,
  `postgres`, `trino` and `bigquery` declare all of them; `redshift` withholds three —
  arrays, Unicode normalization and variant extraction — so a project using `json_path`
  or a `normalize` rule meets a refusal on that dialect and compiles on the others, and
  its quality flags take the delimited-string shape rather than an array column;
  `snowflake` and `databricks` withhold Unicode normalization alone. No shipped example
  meets those refusals today; the test suite provokes them against a deliberately
  incapable port.
- The engine test tier runs the emitted SQL against real DuckDB, PostgreSQL and Trino
  containers, which is where claims on this page are checked. The four cloud engines have
  no container, so each is established by the ladder S-0012 names: offline rungs on every
  pull request — unit, golden, and a re-parse of every rendered statement by the engine's
  own grammar; a *surrogate* lane, marked `surrogate` and never `engine`, that runs on
  `main` — the `sivchari/snowflake-emulator` image for Snowflake, the
  `goccy/bigquery-emulator` image for BigQuery at a pinned tag, a PostgreSQL container
  for Redshift's `postgres-compatible` fixtures, and local Spark for Databricks; and the
  engine's own compiler as the oracle, under credentials a pull request cannot reach. A
  green surrogate says the emulator accepted the statements, and its test names say so.
- **The local Redshift lane checks the PostgreSQL-compatible subset; only a live cluster
  checks the dialect.** There is no Redshift container to run locally, so the local
  lane submits the port's SQL to a real PostgreSQL standing in for a cluster
  (`tests/engines/test_redshift_surrogate.py`). A green run there says PostgreSQL
  accepted these statements — no more, and the test names and its marker say so rather
  than naming the engine. Fixtures are split into two classes for exactly this reason
  (`tests/support/redshift.py`): `postgres-compatible`, which the local lane runs, and
  `redshift-native` — everything reaching `SUPER`, PartiQL, a Redshift-only function or
  Redshift's own type rules — which it never runs, because a green over one of those
  would be a claim a PostgreSQL container cannot make. Nothing but a live cluster can
  check the native class, and no lane runs one today — so treat every Redshift-specific
  statement on this page as a rendering-level claim, not an engine observation.
