# Say who owns a thing, what it holds, and who may read it

A spec says what an entity *is*. Three annotations say the things around it: who is
responsible, what class of data a column holds, and which roles may read the relation it
becomes. All three travel to metadata slots your targets already have, and none of them
changes a line of SQL.

```yaml
spec_version: 1
entities:
  customer:
    grain: one row per customer
    key: [customer_id]
    owner: growth-analytics@example.com
    grants:
      select: [analyst, reverse_etl]
    fields:
      customer_id: {type: string, required: true}
      email: {type: string, classification: pii}
      segment: {type: string, classification: internal}
```

**An owner is a declaration bloomery never verifies.** Nobody is paged, and a name is not
checked against a directory.

**A classification masks nothing either** — no column is dropped, redacted or encrypted —
but it is not inert: it is checked *against your grants*, and a sensitive column published
to an audience its source entity restricts is a compile error. What it cannot do is
protect a column on its own.

`grants:` is the one with a mechanism, and everything enforceable here runs through it.

## `owner:` — who to tell

A free string on an entity, a mart or a metric. It is not validated as an email, a handle
or a team name: every project spells this differently, and a format rule would refuse
spellings that are correct for their reader. `o'brien@example.com` is fine.

It reaches whichever slot each target has for that kind of node:

| | SQLMesh | dbt | Cube |
|---|---|---|---|
| entity | `MODEL (owner …)` | `meta.owner` | — |
| mart | `MODEL (owner …)` | `meta.owner` | cube `meta.owner` |
| metric | — | — | measure `meta.owner` |

The blanks are objects that do not exist rather than metadata that was dropped: Cube emits
no entities, and a metric has no model of its own in either SQL target.

**The MetricFlow manifest carries no owner yet.** A semantic model there has an `owners`
list and it would be the natural fourth column of that table; what it should hold — the
entity's owner, the metric's, or both — is a question about the manifest's shape rather
than about this annotation, and it is open.

**It does not inherit.** A mart over an owned entity has no owner until you write one, and
a metric instantiating a catalog template does not take the template's. An owner nobody
wrote should not look like one somebody did — so `metric_templates:` has no `owner:` key
at all. An entity's `<entity>__reject` table does carry its owner, because that is the same
entity's second artifact rather than a second thing to own.

## `classification:` — what a column holds

One of exactly four values on a field: `public`, `internal`, `pii`, `secret`. The
vocabulary is closed because the value is *routed*, not just recorded — and a closed list
is easy to widen later, while an open one could never be narrowed.

```yaml
      email: {type: string, classification: pii}
```

- **dbt** gets `meta.classification` on the column entry.
- **Cube** gets the same, and a `pii` or `secret` column becomes a member with
  `public: false`.
- **SQLMesh** gets nothing. Its model carries `description`, `tags` and
  `column_descriptions`, none of which is a key-value per column, and writing a routing
  value into a field people read as prose would be worse than leaving it out.

!!! note "`public: false` hides a column; it does not protect one"

    Measured against Cube v1.7.18: the member still appears in `/meta`, carrying
    `public: false` and `isVisible: false`, and **a client that names it in a query still
    gets an answer**. It is a visibility hint — Cube's own UIs honour it, so the column
    stops showing up in pickers — and it is not access control. If a role must not read a
    column, the tool is [`grants:`](#grants-who-may-read-it), or not putting the column in
    the mart.

`internal` is still marked public on purpose. It says who *should* read a column, which is
not something a semantic layer can enforce — and, as above, neither is `pii`.

A column no mart projects has no Cube surface to be taken off; its classification still
reaches dbt.

### What a classification refuses

The metadata above is the smaller half. A `pii` or `secret` column is checked against the
grants on the relations that publish it — a mart or a rollup — and there are three
outcomes, in decreasing order of what the compiler can prove:

**`secret` in a published relation is refused, always.** A mart is the published surface,
which is the one thing `secret` says the column is not part of. It does not matter what is
granted:

```
mart 'order_items' carries column 'order_customer_id', which is order.customer_id
classified secret (S-0062/D-10). A mart is the published surface, which is the one
thing 'secret' says this column is not part of. Fix: drop the column from the flatten,
or reclassify it if it is not secret
```

**A `pii`/`secret` column in a relation that admits a role its entity does not is
refused.** The ordinary leak is a customer table flattened into a wide mart and the mart
granted to everyone:

```
mart 'order_items' carries column 'order_customer_id', which is order.customer_id
classified pii, and grants select to everyone — role(s) entity 'order' does not grant
(S-0062/D-11)
```

Equal grants pass. Narrower grants pass. `{select: []}` passes, because no role at all is
the narrowest thing there is. **Disjoint sets are refused**, not passed: it is a set
difference rather than a superset test, and a role that can read the mart but not the
entity is the leak whether or not the mart also admits the entity's own roles.

**An undeclared audience advises rather than refuses.** If either side has no `grants:`
block, bloomery has no opinion about who reads the relation and your warehouse's own grants
stand — that is *unknown*, not wider, and refusing it would refuse every project that
manages gold grants elsewhere. You get an
[`undeclared_audience` advisory](../reference/errors.md#advisories-are-not-errors) on the
value `evaluate()` returns. Declare grants on both sides and the refusal above takes over.

A rollup is a published relation too, and declares **its own** grants — it does not inherit
its parent mart's, because a rollup is something you wrote and D2's rule is that authored
nodes do not inherit.

### How this relates to `quarantine.redact`

They answer different questions and never meet.
[`redact:`](../concepts/data-quality.md) decides what a **reject row** keeps — a reject
table is a copy of failing rows with a retention window, so a path listed there is removed
before the row is written. `classification:` describes a column that is *published*, and
what it composes with is `grants:`, above.

The two cannot be pointed at the same column anyway: bloomery refuses a `redact:` path that
a mapping reads, because replay re-runs the mapping against `raw` and a redacted path is
gone by then. A published column therefore never appears in `redact:`, which is exactly why
a classification has to be checked against something else.

## `grants:` — who may read it

```yaml
    grants:
      select: [analyst, reverse_etl]
```

On an entity or a mart. **This one is applied** — by SQLMesh at creation, by dbt on every
run — so being wrong here changes who can read data rather than only what a catalogue
says. An entity's reject table is granted with it, because a reject row is that entity's
data that failed a rule.

**An empty list is not an absent block.**

```yaml
    grants:
      select: []          # no role may select
```

```yaml
    # no grants: block at all — bloomery has no opinion, and whatever
    # your warehouse already grants stands
```

Emitting the first as the second would revoke nothing while looking like it did.

What the empty list can promise is bounded by the adapter, and it is worth knowing the
edge: dbt reconciles its grants against the relation on every run, SQLMesh applies them at
creation, and a warehouse may carry pre-existing privileges across a replace regardless of
either — Snowflake's `copy_grants` does exactly that. So `{select: []}` is a statement
about the **framework-managed** grant set, never about every privilege the object holds.

**Cube refuses a `grants:` block.** It reads relations it does not own, so a grant emitted
there would be a restriction in a file that restricts nothing. Compiling a granted project
for Cube fails with a message saying so, rather than dropping the block and letting you
believe the restriction is in force everywhere.

## What is not here

**Seeds.** `seeds:` is refused permanently, and the message says "refused, not missing". A
seed is a table of data in your repository; bloomery reads no files while compiling, so
the rows would have to live in a spec — which would make the spec a data file. Land the
CSV with your loader, declare the relation it writes as a bronze source, and map an entity
onto it like any other.

**Row-level access.** A grant names a role and applies to a relation. Filtering *rows* by
who is asking is a query-time concern and is not an annotation on a spec node.

**Masking.** No owner is paged and no classification masks a column — not even in Cube,
where `public: false` hides a member without making it unqueryable. A classification is
checked against your grants; it never rewrites a column. If a consumer must not read one,
the tool is a grant that does not include their role, or leaving the column out of the mart
they read.
