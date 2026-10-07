# Dialects

Pick the warehouse SQL dialect a target renders, and know where the dialects differ:
physical types, capabilities a port withholds, and the few places a value can differ.

## The dialect is not the target

`--dialect` chooses how SQL is spelled; `--target` chooses which artifacts exist. Every
SQL target renders through the same port, so `--target sqlmesh --dialect postgres` and
`--target dbt --dialect postgres` share every line of dialect logic. Cube and MetricFlow
ignore the dialect.

```console
$ bloomery compile specs/ --target sqlmesh --dialect trino --out build/sqlmesh
$ bloomery explain specs/ --metrics revenue --by ordered_month --dialect snowflake
```

```python
from bloomery import Target, compile_project

artifacts = compile_project(project, target=Target.DBT, dialect="bigquery")
```

## Seven ports

| `--dialect` | Pick it when | What to know |
|---|---|---|
| `duckdb` | local work, tests, examples | `divide` goes through a float (below) |
| `postgres` | Postgres warehouse | `variant` is `JSONB`; null-on-failure casts use `PG_INPUT_IS_VALID` |
| `trino` | federated engine, Iceberg lakehouse | |
| `redshift` | Redshift | withholds arrays, `normalize` and `json_path`; `variant` is `SUPER` |
| `snowflake` | Snowflake | `int` is `NUMBER(38, 0)`, `timestamp` is `TIMESTAMP_NTZ`; withholds `normalize` |
| `bigquery` | BigQuery | `timestamp` is `DATETIME`; `decimal` lands on `NUMERIC` or `BIGNUMERIC` by its bounds |
| `databricks` | Databricks SQL | `variant` is `STRING`; no transactions; withholds `normalize` |

Any other name is an `EmitError` naming the seven. DuckDB, Postgres and Trino are
checked against real engines; the four cloud ports are checked at rendering level, plus
the engine's own compiler where a lane runs one.

## Physical types

| Logical | `duckdb` | `postgres` | `trino` | `redshift` | `snowflake` | `bigquery` | `databricks` |
|---|---|---|---|---|---|---|---|
| `string` | `VARCHAR` | `TEXT` | `VARCHAR` | `VARCHAR(MAX)` | `VARCHAR` | `STRING` | `STRING` |
| `int` | `BIGINT` | `BIGINT` | `BIGINT` | `BIGINT` | `NUMBER(38, 0)` | `INT64` | `BIGINT` |
| `decimal(p,s)` | `DECIMAL` | `DECIMAL` | `DECIMAL` | `DECIMAL` | `DECIMAL`, `p` ≤ 38 | `NUMERIC`/`BIGNUMERIC` | `DECIMAL`, `p` ≤ 38 |
| `bool` | `BOOLEAN` | `BOOLEAN` | `BOOLEAN` | `BOOLEAN` | `BOOLEAN` | `BOOL` | `BOOLEAN` |
| `date` | `DATE` | `DATE` | `DATE` | `DATE` | `DATE` | `DATE` | `DATE` |
| `timestamp` | `TIMESTAMP` | `TIMESTAMP` | `TIMESTAMP` | `TIMESTAMP` | `TIMESTAMP_NTZ` | `DATETIME` | `TIMESTAMP_NTZ` |
| `variant` | `JSON` | `JSONB` | `JSON` | `SUPER` | `VARIANT` | `JSON` | `STRING` |

There are no floats in the type system. A `decimal` wider than a port can hold is refused
at emit. `vector(...)` has no physical spelling on any port: it belongs to the retrieval
target, not a warehouse table.

## Capabilities: refused, never approximated

A port that cannot express a construct refuses it at compile time. `duckdb`, `postgres`
and `trino` refuse none of these.

| Construct | Refused on | What to do |
|---|---|---|
| a `normalize` quality rule | `redshift`, `snowflake`, `databricks` | drop the rule there, or normalize upstream |
| the `json_path` transform (variant extraction) | `redshift` | read the nested path as a `string` field instead |
| array columns | `redshift` | nothing: `_quality_flags` and `failed_rules` become a comma-delimited string, sorted by rule name, empty string when clean |
| a `regex_extract` transform naming a capture group other than the first | `bigquery`, `redshift` | restructure the pattern so the group you want is the first |

On Redshift, a consumer asks "does this row carry a flag" by matching a delimited member
instead of indexing an array. A mart's `has_quality_flags` works on both shapes.

A `pattern` rule's regex is a portable subset on every dialect; lookaround,
backreferences and repetition bounds above 1000 are refused at parse, everywhere.

## Same meaning, different SQL

The port supplies the spelling; the meaning does not change. Worth knowing when reading
emitted SQL:

- **Null-on-failure casts** (the `coercible` rule): `TRY_CAST` on DuckDB, Trino,
  Redshift, Databricks; `SAFE_CAST` on BigQuery; a `PG_INPUT_IS_VALID` guard on Postgres;
  a `VARCHAR` cast first on Snowflake. Never a plain `CAST` that aborts the run.
- **Current instant** is UTC everywhere (`SYSDATE()` on Snowflake, never the
  session-zoned `CURRENT_TIMESTAMP`).
- **`to_utc`** renders through each engine's own zone function.
- **`reject_id`** digests agree byte for byte across engines.
- **Reserved identifiers** are quoted: `silver."order"`, `silver."ORDER"` on Snowflake,
  `` silver.`order` `` on BigQuery and Databricks.
- **Databricks** has no transaction: the dbt replay commits statement by statement, and a
  failure part-way leaves earlier statements committed.

The ports also absorb two engine quirks that used to move data: `parse_ts: ISO8601`
accepts the `T`, `t` and space separators on every engine, and `to_utc` returns the same
instant whoever runs it.

## Exact arithmetic

**`divide` is inexact on DuckDB**: the engine has no exact decimal division, so the value
passes through a float and is narrowed back to the declared decimal. When exactness
matters, multiply by the reciprocal:

```yaml fragment
fields:
  amount:
    from: "$.amount_cents"
    transform: [{to_decimal: [14, 2]}, {multiply: "0.01"}]
```

**A catalog recipe's `/` divides as `divide` does**: every `/` in a recipe `expr:` is lowered
through the same marker, its dividend cast to a decimal at least `decimal(38, 9)` wide and the
result narrowed once. Exact on PostgreSQL and Trino, through a float on DuckDB.

## Published pages

- [Dialects](https://morzecrew.github.io/bloomery/latest/reference/dialects/)
- [Transforms](https://morzecrew.github.io/bloomery/latest/reference/transforms/)
