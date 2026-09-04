# RFC 0057 — Declared source freshness

- **Status:** 📝 Draft — schedulable, and **narrower than the ceiling item that produced
  it**. §3 records why the "blocked on measured evidence" reading was wrong for the half
  this builds and right for the half it does not.
- **Scope:** A `freshness:` block on a bronze source, carrying the thresholds at which
  staleness warns and errors, emitted into the artifacts the frameworks already measure
  against. bloomery declares; the framework measures. The half that is genuinely blocked —
  bloomery *reporting* freshness — is named in §8 and built by nothing here.
- **Related:** [`src/bloomery/emit/dbt/__init__.py`](../src/bloomery/emit/dbt/__init__.py)
  (`_sources_artifact`),
  [`src/bloomery/quality/reject.py`](../src/bloomery/quality/reject.py)
  (`_ingested_at`, the column this keys on),
  [`src/bloomery/spec/catalog.py`](../src/bloomery/spec/catalog.py),
  RFC 0016 (ingestion metadata, D21), RFC 0022 (`SpecEvidence`; retired at `cc8c691`),
  RFC 0053 (retrieval semantics — §3 there established there is no intake for measured
  evidence).
- **Origin:** The ceiling review's third item, and a **correction to the split's own
  first reading of it**. Freshness was classified "blocked on a surface that does not
  exist", on the ground that `SpecEvidence` is everything knowable without touching data.
  That is true of bloomery reporting freshness and false of bloomery declaring it: dbt's
  `sources.yml` takes `freshness:` and `loaded_at_field:`, `dbt source freshness`
  measures it, and bloomery already emits that file and already requires the column.

---

## 1. Summary

A `freshness:` threshold is a declaration, not a measurement. The spec says "this source
is stale after six hours"; the framework runs the query that finds out. bloomery reads no
clock and touches no data, and neither of those constraints is in the way.

The column it keys on already exists and is already mandatory where it matters:
RFC 0016 D21 requires `_ingested_at` on every quarantining entity's bronze relation, and
that is exactly dbt's `loaded_at_field`. So this is a spec key, an IR field, and two
emitter branches.

## 2. Motivation

**The most common production failure in an analytics stack is not a wrong number — it is
a right number computed over yesterday's data.** Every check bloomery emits is about the
rows that arrived; none is about rows that did not.

**bloomery already owns the file the answer goes in.** `models/sources.yml` is emitted
today with `name`, `schema` and `tables` and nothing else. A shop that adopts bloomery
and had freshness configured loses it, and gets it back by hand-editing a generated file
the next compile overwrites — the same trap the SQLMesh `config.yaml` gateway turned out
to be.

**The declaration is checkable at compile in a way the measurement never is.** A
`freshness:` block on a relation with no `_ingested_at` is a threshold nothing can
evaluate, and that is a refusal bloomery can make from the spec alone. That is the useful
half, and it is available now.

## 3. Current state

Verified against the tree.

- **No `freshness` anywhere in `src/`.** Not in the spec layer, the IR, or any emitter.
- **`_ingested_at` is real and mandatory** on the bronze relation of every entity
  declaring `quarantine:` or `dedupe:` (RFC 0016 D21), and the ingestion-metadata audit
  already asserts it casts to a timestamp. An entity with neither does not require it,
  which is the constraint §5.2 turns into a refusal.
- **`_sources_artifact`** builds `{"name", "schema", "tables": [{"name": …}]}` — the
  exact shape dbt's `freshness:` and `loaded_at_field:` hang off.
- **SQLMesh** has no source-freshness concept; sources are not modelled objects there at
  all. §5.3.
- **`SpecEvidence` is "everything knowable about a spec without touching data"** and has
  no intake for a measured result. That sentence is what made freshness look blocked, and
  it constrains only §8's half.

**The correction, stated plainly.** The split's first pass put freshness with the blocked
items. It is two features sharing a word: *declaring* a threshold is a spec key with an
emitter branch, and *reporting* observed staleness needs an evidence intake that does not
exist. The first is buildable today; the second is not, and is out of scope here rather
than deferred inside it.

## 4. Goals / Non-goals

**Goals**

- `freshness: {warn_after: 6h, error_after: 24h}` on a source relation in a mapping.
- dbt `sources.yml` carrying `freshness:` and `loaded_at_field:`.
- A refusal when a threshold is declared on a relation whose entity does not require
  `_ingested_at`, naming what to add.
- Durations reusing the grammar `quarantine.retention` already validates — one spelling
  of a duration in the spec surface, not two.

**Non-goals**

- **Measuring freshness.** bloomery emits the threshold; `dbt source freshness` runs the
  query. bloomery executes nothing (RFC 0003).
- **Reporting observed staleness in `SpecEvidence`.** No intake exists for a measured
  result, and inventing one is a larger RFC than this (§8).
- **An SLA on a mart or a metric.** Downstream freshness is derived from source freshness
  plus a schedule, and bloomery knows no schedule — it emits no `cron` for exactly that
  reason.
- **A default threshold.** A source with no `freshness:` block gets none. Guessing six
  hours for everyone would emit an assertion nobody made.

## 5. Design

### 5.1 The spec surface

On the mapping's source, beside the relation it already names:

```yaml
sources:
  - relation: shopify.order_lines
    freshness: {warn_after: 6h, error_after: 24h}
```

Durations are the `quarantine.retention` grammar — `90d`, `6h` — reused rather than
re-invented, so a reader who has learned one has learned both, and one validator covers
them.

`error_after` below `warn_after` is refused: an error threshold that fires before its
warning makes the warning unreachable, which is a spec that means something other than
what it says.

### 5.2 The `_ingested_at` requirement

dbt's freshness query is `SELECT MAX(<loaded_at_field>)`, so the column must exist. It
does — for entities that quarantine or dedupe. For an entity that does neither, the
bronze relation carries no required ingestion metadata, and a `freshness:` block there
would emit a `loaded_at_field` naming a column that may not exist: a source freshness
check that errors at run time on a project that compiled clean.

So: **refused at compile**, naming the two ways out — declare `quarantine:` or `dedupe:`
on the entity, which makes the column mandatory, or drop the block.

### 5.2a One relation, several mappings

`_sources_artifact` groups by physical `(namespace, relation)`, so several mappings
reading one bronze relation produce **one** dbt table entry. Two of them declaring
different thresholds cannot both be emitted, and picking one silently is the
plausible-but-wrong shape this project refuses.

**A threshold is a statement about the relation, not about the mapping that carries it.**
That sentence decides every case below, and an earlier draft of this section did not have
it — which produced a rule with no valid configuration (§9's last risk, and the reason
this paragraph exists).

- **Equal thresholds** are not a conflict. They collapse to the one entry.
- **Different thresholds** are **refused**, naming both mappings. This is RFC 0024 D33's
  rule — declarations about one physical thing must agree — and it is the only genuine
  disagreement of the three.
- **One mapping declares and another omits** is **fine**, and neither is refused. A
  mapping that reads a relation and says nothing about its staleness is not disagreeing
  with a threshold; it is not making a statement about the relation at all. The tempting
  refusal here — "silence is not agreement" — mistakes *who* a threshold is about.

The `_ingested_at` requirement follows from the same sentence, and follows it back from
where an earlier draft put it. dbt's freshness query names `_ingested_at` on the shared
table entry, so what must hold is that the **relation** exposes the column — which is
exactly what the *declaring* mapping's ingestion-metadata contract asserts (RFC 0016 D21).
A sibling mapping of the same physical table neither adds nor removes a column, so it has
nothing to satisfy.

Requiring the contract from every consumer instead reads as thorough and has no valid
configuration: a plain entity reading a relation whose other consumer quarantines could
not declare the threshold (§5.2 refuses it, since it needs no `_ingested_at`) and could
not omit it either. The only escape would be declaring `quarantine:` on an entity that
does not want it, to satisfy a freshness rule on someone else's mapping.

### 5.3 Targets

- **dbt**: `freshness: {warn_after: {count: 6, period: hour}, error_after: …}` and
  `loaded_at_field: _ingested_at` on the table entry in `models/sources.yml`.
- **SQLMesh**: nothing. Sources are not objects there — a bloomery bronze relation is a
  name in a `FROM` clause and SQLMesh has nothing to attach a threshold to. As with
  exposures (RFC 0056 D4), emitting nothing is not a degradation, because there is no
  artifact being approximated.
- **Cube**: nothing, for the same reason.

### 5.4 What a reader is told

The docs sentence that has to be there, because the failure it prevents is silent:
`dbt build` does **not** run freshness. `dbt source freshness` does, as its own command in
the schedule. An emitted threshold that nobody runs is a threshold that never fires, and
it looks identical to one that passes.

## 6. Tests

- **Unit:** the two refusals — inverted thresholds, and a block on an entity with no
  ingestion metadata.
- **Golden:** `sources.yml` with and without the block; every existing golden unchanged.
- **e2e:** `dbt parse` over a project declaring freshness, and `dbt source freshness`
  against a seeded DuckDB — the second because a well-formed threshold on a
  `loaded_at_field` of the wrong type parses and fails only when run.
- **Refusal census:** both messages.

## 7. Docs

- The dbt how-to: the block, and §5.4's sentence about which command runs it.
- `pages/docs/reference/errors.md`: the two refusals.
- The quality concepts page: freshness is about rows that did **not** arrive, which is
  the axis every other check on that page is silent about.

## 8. Out of scope

- **bloomery reporting freshness.** `SpecEvidence` is everything knowable without
  touching data; an observed staleness is a measurement, and there is no intake for one
  anywhere in the compiler. That is its own RFC and it is not a platform-metadata
  feature — it is a question about whether this compiler ever ingests measured evidence,
  which RFC 0053 §3 raised and left open.
- **Schedules.** No `cron`, here or anywhere.
- **Mart-level SLAs** (§4).

## 9. Risks

- **A threshold nobody runs.** The whole feature is inert unless `dbt source freshness`
  is in the schedule, and nothing bloomery emits can make it so. §5.4 is the mitigation
  and it is a sentence, which is a weak one.
- **`_ingested_at` is required only where quality is declared.** The refusal in §5.2
  makes the coupling explicit, but it means "I want freshness" implies "I want quarantine
  or dedupe", which is a surprising dependency to meet in an error message. The message
  has to explain the *why* and not only the fix.
- **A rule about a shared relation is easy to make unsatisfiable.** This RFC did it once:
  requiring the ingestion contract from every consumer *and* refusing a mapping that omits
  a threshold left a relation shared by a quarantining and a plain entity with no legal
  configuration at all. Both rules read as thorough in isolation. The check that catches
  it is to write down what the declaration is *about* — the relation — and derive each
  rule from that rather than from what feels rigorous per mapping.

- **Duration grammar reuse could drift.** `retention` and `freshness` sharing a validator
  is right today; if either grows a unit the other must not, the sharing becomes a
  coupling. Cheap to split later, noted so it is a decision and not an accident.

## 10. Unresolved questions

- Whether `filter:` (dbt's freshness filter, for partitioned sources where the max scan
  is expensive) belongs here. It is a performance escape hatch and carries a SQL fragment,
  which is a category bloomery admits reluctantly.
- Whether freshness belongs on the *source relation* or on the *catalog*. The catalog
  describes relations that exist; the mapping describes what reads them. This RFC puts it
  on the mapping because the threshold is a statement about the pipeline, not the table.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | bloomery **declares** freshness and never measures it. The threshold is emitted; the framework runs the query. This is the same line drawn everywhere else — no execution, no clock, no environment. |
| 2 | `LOCKED` | **Superseded by D2c.** A `freshness:` block on an entity that requires no `_ingested_at` is refused, and the requirement is over **every** consumer of the relation rather than the declaring one. |
| 2a | `LOCKED` | Two mappings declaring **different** thresholds on one physical relation are refused, naming both. `_sources_artifact` emits one table entry per relation, so one of the two would be silently dropped — the same rule RFC 0024 D33 applies to quality rules over a merged entity. Equal thresholds collapse and are not a conflict. |
| 2b | `LOCKED` | **Superseded by D2c.** One mapping declaring a threshold while another on the same relation omits it is refused too, not resolved in favour of the explicit one. |
| 2c | `LOCKED` | **A threshold is a statement about the relation, not about the mapping that carries it.** So: the ingestion-metadata contract is required of the **declaring** mapping, because that is what asserts the relation exposes `_ingested_at`, and a sibling mapping of the same physical table has nothing to satisfy — it neither adds nor removes a column. And a mapping that omits a threshold is not disagreeing with one; it is making no statement about the relation, so the mixed case is legal. D2's "every consumer" and D2b's refusal each read as thorough and together admit **no valid configuration**: a plain entity sharing a relation with a quarantining one could neither declare (D2 refuses it) nor omit (D2b refuses it), and its only escape was to declare `quarantine:` it does not want. D2a survives untouched, because two different thresholds are a real disagreement about one thing. |
| 3 | `ASSUMED` | Durations reuse `quarantine.retention`'s grammar and validator. One spelling of a duration across the spec surface. |
| 4 | `LOCKED` | `error_after` below `warn_after` is refused. An unreachable warning is a spec that means something other than what it says. |
| 5 | `ASSUMED` | No default threshold. A source with no block gets none; a guessed six hours would emit an assertion nobody made. |
| 6 | `LOCKED` | SQLMesh and Cube emit nothing, and it is not a refusal — neither models a source as an object, so there is no artifact being approximated (the RFC 0056 D4 rule). |
| 7 | `ASSUMED` | Reporting *observed* staleness is out of scope and is not a phase of this RFC. It needs an evidence intake that does not exist, and folding it in would make a two-commit change wait on an open question. |

## 12. Phasing

Two commits:

1. **Spec key, IR field, and all three refusals** — inverted thresholds, a threshold on a
   mapping whose entity requires no `_ingested_at`, and conflicting thresholds on one
   relation — with the census entries. The mixed case is legal and gets a test saying so,
   because "this is allowed" is the half a refusal-shaped phase forgets to pin. No emitter change: the refusals are the risky half and land alone.
2. **The dbt `sources.yml` branch**, its golden, and the `dbt source freshness` e2e leg.
