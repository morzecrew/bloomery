# RFC 0048 — BigQuery dialect port

- **Status:** 📝 Draft — proposed, not scheduled. Validation method is
  [RFC 0046](0046-validating-a-dialect-port.md). Of the four cloud ports it has the
  **cheapest authoritative layer**: a dry run is a full parse, bind and type check that
  executes nothing and scans nothing.
- **Scope:** A `bigquery` `DialectPort`, its rewrite surface, and the tiers that establish
  it. GoogleSQL's type and timestamp semantics are the work; the test infrastructure is
  not.
- **Related:** [`src/bloomery/dialects/base.py`](../src/bloomery/dialects/base.py);
  RFC 0028 (zoneless UTC, retired), RFC 0036 (offset-bearing timestamps), RFC 0016 (data
  quality, retired) for the `SAFE_CAST` dependency.

---

## 1. Summary

BigQuery is very testable for a compiler. The main challenge is not test infrastructure; it
is GoogleSQL's type and timestamp semantics — and one decision, §7 D1, carries most of the
risk.

## 2. The rewrite surface

- **`DATETIME` versus `TIMESTAMP`.** BigQuery distinguishes them, bloomery has one
  `timestamp` that is UTC and zoneless (RFC 0028), and SQLGlot has a default. The port must
  map this deliberately rather than accept whatever the default produces — see D1.
- **`SAFE_CAST`**, on which the quality system's NULL-on-failure lowering depends: RFC 0016
  D3's `TRY_CAST` shape needs a GoogleSQL spelling, and the shape has to survive the
  `Cast → TryCast` rewrite the way it does on the other three ports.
- **ISO parsing and RFC 0036's offset guard**, whose `SUBSTRING(x, 11)` window and two
  `LIKE`s must render natively and mean the same thing.
- **`NUMERIC` and `BIGNUMERIC`** precision and scale boundaries, against bloomery's
  no-floats rule and declared `decimal(p, s)`.
- **SHA-256 returns `BYTES`**, so `text_sha256`'s lowercase-hex contract needs a hex
  encoding step — the same shape Trino needed.
- **Regexp capture behaviour**; **JSON extraction and its result types**; **Unicode
  normalization**; **array support** for `DialectFeature.ARRAY`; **backtick identifier
  quoting**; division and aggregate result types; date/timestamp truncation and timezone
  conversion; null behaviour.

Fixtures are needed for `STRING`, `INT64`, `BOOL`, `DATE`, `DATETIME` and `TIMESTAMP`, and
explicitly for the zoneless-UTC invariant.

## 3. Local execution

`goccy/bigquery-emulator` runs as a container with no Google Cloud project and no
credentials:

```bash
docker run --rm -p 9050:9050 -p 9060:9060 \
  ghcr.io/goccy/bigquery-emulator:<pinned> --project=test
```

REST on `9050`, gRPC on `9060`. Wrapped in a Testcontainers fixture, it covers generated
`SELECT` execution, seed data and fixture marts, joins and aggregates, common date/time
operations, `SAFE_CAST` where supported, basic JSON, regexp, arrays, and
quality/quarantine queries.

It is an independent implementation with incomplete API and SQL coverage — rung 4,
`surrogate`-marked, never the oracle. Pin the version; `latest` is not a lane.

## 4. Authoritative layers

```python
job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
job = client.query(sql, job_config=job_config)
```

A dry run validates the query and estimates bytes without executing. It reaches the real
service, so it is a better acceptance check than SQLGlot and better than the emulator. For
queries referencing tables, a tiny stable test dataset must exist first so that name and
type resolution can actually run.

The small execution corpus then covers what a dry run cannot: exact timestamp values,
decimal results, null propagation, `SAFE_CAST`, regexp captures, JSON extraction, SHA-256
hex output, Unicode normalization, and quarantine disposition. Tiny tables, explicit byte
limits.

## 5. CI identity

Workload Identity Federation with GitHub OIDC, not a long-lived service-account JSON key.
The CI identity needs only: issue query jobs and dry runs; read metadata for the dedicated
test dataset; execute the tiny live corpus where enabled. Dry-run and execution are
separate jobs so the default cloud lane cannot scan a large dataset (RFC 0046 §5).

## 6. Tests

```text
tests/unit/test_dialects/test_bigquery.py
tests/golden/…/bigquery/…
tests/support/bigquery.py
tests/engines/test_bigquery_surrogate.py
tests/engines/test_bigquery_live.py
```

## 7. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **The `DATETIME`/`TIMESTAMP` choice is made explicitly by this port and never inherited from a SQLGlot default.** bloomery's `timestamp` is UTC and zoneless (RFC 0028); BigQuery's `TIMESTAMP` is an instant and its `DATETIME` is a wall clock, and the two are not interchangeable under aggregation or comparison. Locked because a default that happens to work on the fixture corpus is indistinguishable from a decision until the day a value crosses a zone — and this is the single highest-risk line in the port. |
| 2 | `LOCKED` | **`SAFE_CAST` must satisfy RFC 0016 D3's NULL-on-failure contract, including under the `Cast → TryCast` rewrite.** The quality system's entire coercion story is that a bad value becomes NULL where `coercible` can see it, rather than aborting a run. A port whose safe cast does not survive that rewrite silently turns a quality-carrying entity back into produce-or-raise on one engine. |
| 3 | `LOCKED` | **The emulator is pinned and is never the authoritative lane.** RFC 0046 D1 and D3 applied. Recorded here because BigQuery's emulator is good enough, and its dry run cheap enough, that the tempting shortcut is the opposite of the usual one: skipping the emulator is defensible, skipping the dry run is not. |
| 4 | `ASSUMED` | **CI authenticates by Workload Identity Federation, not a stored service-account key.** A long-lived JSON key in repository secrets is the credential most likely to outlive the maintainer who created it. Not `LOCKED` because the trade is operational rather than semantic — a project without federation configured may start with a scoped key and a rotation note. |
| 5 | `ASSUMED` | **A tiny dedicated dataset exists before the dry-run lane, so name and type resolution actually run.** A dry run over a query referencing nothing validates syntax and little else, which would make the lane look authoritative while proving roughly what rung 3 proves. |
| 6 | `OPEN` | **Whether the emulator lane runs on PRs.** It needs no credential, which makes it eligible under RFC 0046 D5 where the other three ports' live lanes are not — but it is also the rung with the least authority. Decide on measured runtime and on whether it catches anything rungs 1–3 miss. |
| 7 | `OPEN` | **The `NUMERIC`/`BIGNUMERIC` mapping for declared `decimal(p, s)`.** The two have different precision and scale bounds and different division behaviour, and bloomery forbids floats in emission paths. Pick the mapping against the declared-type conformance battery rather than by reading the documentation, and record which bounds a declared type may not exceed. |

## 8. Phasing

Rungs 1–3, then the emulator lane, then the dry-run lane against a real project, then the
execution corpus. The dry-run lane is the one to build early: it is the cheapest
authoritative signal any of the four ports has, and it can validate the whole fixture
corpus rather than a subset.
