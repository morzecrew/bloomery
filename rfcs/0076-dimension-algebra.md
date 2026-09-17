# RFC 0076 — Dimension algebra

- **Status:** 📝 Draft — the large one of its group, and **not scheduled**. A vocabulary RFC:
  it adds facts about how dimensions relate and names the rules that would consume them, most
  of which are future work. Nothing here converts a corpus case on its own.
- **Scope:** Declared relations *between* dimensions — determination, role, and conformance —
  and what becomes provable once they exist. Touches the entity model's field vocabulary,
  `RollupMart.keep`'s meaning, and the flatten grammar's `prefix:`. Deliberately does **not**
  cover dimension tables as relations, slowly-changing dimension storage, or any query-time
  surface.
- **Related:** [`src/bloomery/spec/marts.py`](../src/bloomery/spec/marts.py) (`ViaStep`'s
  `prefix`, `DateRoleStep`, `RollupMart.keep`),
  [`src/bloomery/semantic/rollup.py`](../src/bloomery/semantic/rollup.py) (R008, R013),
  [`src/bloomery/errors.py`](../src/bloomery/errors.py) (`UnsupportedHierarchy`),
  [`src/bloomery/ir/nodes.py`](../src/bloomery/ir/nodes.py) (`DimensionRef`),
  [RFC 0059](0059-multi-project-composition.md) (a conformed dimension crossing a project
  boundary is this document's question one scope out),
  RFC 0038 (measure semantic types and additivity algebra; retired at `efba2b6`) — the
  measure-side counterpart this is named against, RFC 0010 (marts and role-playing
  dimensions; retired at `33bc4f9`), RFC 0058 (rollup marts; retired at `efba2b6`),
  RFC 0015 (query vocabulary; retired at `33bc4f9`).
- **Origin:** Named in the ordering as the third of a group with
  RFC 0074 (declared source timezone; retired at `fb4c6ac`) and
  RFC 0075 (a ratio over one row set; retired at `ba52320`). Those two give a *value* the fact it was
  missing; this one gives a *dimension* the facts it was missing, and it is much larger
  because dimensions relate to each other and values do not.

---

## 1. Summary

RFC 0038 is called *"Measure semantic types and additivity algebra"*. Measures have an
algebra: a closed vocabulary of aggregation kinds, rules about which compose over which, and
refusals when a project claims one that is not true. **Dimensions have no such thing.** They
are column names that appear in `keep:`, in `prefix:`, and in a filter, and nothing in
bloomery says that two of them are related.

This RFC adds three relations — one column **determines** another, a column **plays a role**
of a named dimension, and two columns **are** the same dimension — and states what each buys.
It is deliberately a vocabulary rather than a feature: the rules that consume these facts are
named in §5.4 and mostly not designed here.

## 2. Motivation

**Hierarchy is refused at the query surface and unrepresentable at the spec surface.**
`UnsupportedHierarchy` (`errors.py:975-980`) refuses `$descendant_of`/`$ancestor_of` and tells
the author to "model hierarchy as flattened level columns on the mart". They do — and the
resulting `city`, `state`, `country` columns carry no declared relation, so the advice
produces exactly the shape nothing can reason about.

**A rollup's `keep:` is a set of names with no meaning attached.** `RollupMart.keep` is "the
parent's columns this rollup groups by" (`spec/marts.py:242-248`), and R013 asks one question
about the *measure* over the dropped columns. A rollup keeping `state` while dropping `city`
is a **coarsening** — its groups are unions of the parent's. A rollup keeping `sku` while
dropping `city` is a different question entirely. The two are indistinguishable to every rule
in the registry.

**A prefix is a naming device, not a role.** `ViaStep.prefix` is mandatory and disambiguates
columns (`spec/marts.py:43-63`), so a mart with a billing address and a shipping address gets
`billing_region` and `shipping_region`. Nothing says both are `region`. `DateRoleStep` is the
one place a *role* is declared, and it is **date-only** — `{date: order_date, role: ordered}`
expanding to `ordered_day … ordered_year`. Dates got the concept; every other dimension got a
string prefix.

**RFC 0059 makes this worse, and soon.** A platform project exporting `customer` and a domain
project joining to it will each carry a `region`, and the composed graph will have two. The
export list is a set of names; nothing says a name means the same thing on both sides. A
dimension algebra is what a conformed dimension would be declared in.

## 3. Current state

Verified against the tree.

| What exists | Where | What it does not say |
|---|---|---|
| `DimensionRef(dimension, role)` with `qualified` → `ordered_date` | `ir/nodes.py` | anything relating two dimensions |
| `DateRoleStep{date, role}` | `spec/marts.py:69-75` | that a non-date dimension can play a role |
| `ViaStep.prefix`, mandatory | `spec/marts.py:43-63` | that two prefixes of one relationship are two roles of one dimension |
| `RollupMart.keep`, "at least one, each named once" | `spec/marts.py:242-248` | whether the kept set is a coarsening of the parent's |
| R013 — "a mart's measure is re-aggregable over the dimensions a rollup of it drops" | `semantic/proof.py:356` | anything about the dropped dimensions' own structure |
| `UnsupportedHierarchy`, with its remediation | `errors.py:975-980` | how a flattened hierarchy's levels relate once flattened |

**The measure side, for contrast.** `RULES` holds seventeen rules (`semantic/proof.py:338`).
R008 and R011–R017 reason about measures, aggregation kinds and time frames; R001–R007
compose functional dependencies **between entities** — `closure.py:696-715` keys them on
`determined.ref.entity`, so a determination *between two columns of one entity* has no home
in them. Read the seventeen summaries and a dimension is the object of two (R013's dropped
columns, R015's own dimension) and the subject of none. The asymmetry is not a decision
anybody recorded; it is what happens when the pressure to reason about measures arrives
first.

**A determination relation already exists one level up and is not reusable here.** R005 and
R006 compose functional dependencies between *entities* and their keys. `city → state` is the
same mathematics between two *columns of one entity*, and the existing machinery is keyed on
entity grain rather than on columns, so the shape does not carry over without a new fact.

## 4. Goals / Non-goals

**Goals**

- An author can declare that one dimension column determines another.
- An author can declare that a column plays a named role of a dimension, for any dimension
  and not only a date.
- An author can declare that two columns are the same dimension.
- Each fact has at least one named consequence — a refusal that becomes possible, or a proof
  that becomes constructible — and §5.4 names it. A fact with no consumer is not added.
- Existing projects compile unchanged. Every relation here is optional and additive.

**Non-goals**

- **Dimension tables as first-class relations.** A conformed dimension materialized once and
  referenced everywhere is a build-shape change; this is about facts, not about what is
  emitted.
- **Slowly-changing dimension storage.** RFC 0023 owns that and it is orthogonal: a versioned
  dimension still has levels and roles.
- **Reviving `$descendant_of`.** A declared hierarchy does not make a recursive filter
  portable, which is why RFC 0015 refused it. The refusal stands and gains a better
  remediation, not an exemption.
- **Inferring any of it.** Not from names (`city`/`state`), not from cardinality, not from
  the data. Same argument as RFC 0074 D1, one type over.
- **Solving case 012.** A distinct count is not additive over a coarsening either — a
  customer who buys in two cities is one customer and two city-level counts. Determination
  gives disjointness of *groups*, which is not what a distinct count needs. Saying so here
  stops a plausible-sounding claim from being made later.

## 5. Design

### 5.1 Determination — `determines:`

```yaml
entities:
  order:
    fields:
      city:    {type: string, determines: [state]}
      state:   {type: string, determines: [country]}
      country: {type: string}
```

One column determines another when each value of the first corresponds to exactly one value
of the second. It is declared on the **determinant**, transitively closed by the compiler, and
refused on a cycle.

It is a claim about the data that bloomery cannot check and does not try to — the same
posture as a declared `many_to_one` (R002), which is the closest existing relation and the
one this is modelled on. A wrong `determines:` produces a wrong rollup with full compiler
blessing, which §9 states plainly.

### 5.2 Roles, for any dimension

```yaml
flatten:
  - {via: billing_address,  prefix: billing,  role_of: address}
  - {via: shipping_address, prefix: shipping, role_of: address}
```

`role_of:` names the dimension a prefixed column family is a role of. `DateRoleStep` becomes
the special case it always was — a date's roles expand to buckets, which is a date-specific
elaboration of a general idea — rather than the only case.

The prefix stays and stays mandatory: it is what keeps the emitted columns distinct, and RFC
0010 D3 already refused an empty one. `role_of:` adds what the prefix never carried, which is
what the two prefixes have in common.

### 5.3 Conformance — `same_as:`

```yaml
marts:
  orders:
    flatten:
      - {via: customer, prefix: customer, role_of: party}
  tickets:
    flatten:
      - {via: reporter, prefix: reporter, role_of: party, same_as: orders.customer}
```

Two roles are the same dimension when they draw from the same value set. Within a project
this is mostly derivable — two roles of one `role_of:` are conformed by construction — so
`same_as:` exists for the case that is not: two columns reaching the same dimension by
different relationships, and, when RFC 0059 lands, a local dimension conformed with an
imported one.

**This is the relation most likely to be cut.** §12 puts it last precisely because the
in-project case is derivable and the cross-project case has no consumer until RFC 0059 P3.

### 5.4 What each fact buys

A fact with no consumer is not added, so each relation is listed with the rule that would
read it. **Every rule below is named, not designed** — that is what makes this a vocabulary
RFC and what §12 phases around.

| Fact | Consumer | What becomes possible |
|---|---|---|
| `determines:` | **R020** — a rollup that keeps a determinant of every dropped dimension is a coarsening | The `state`/`city` rollup gets a proof the `sku`/`city` one does not. Today R013 grades both on the measure alone. |
| `determines:` | `plan()`'s impact report | Changing `city` reaches the `state` rollup built over it. Today they are unrelated nodes and the report says nobody. |
| `determines:` | `UnsupportedHierarchy`'s remediation | The refusal can name the declared levels instead of telling an author to flatten and then saying nothing about the result. |
| `role_of:` | **R021** — two roles of one dimension are comparable | A filter, a join predicate, or an assertion across `billing_region` and `shipping_region` has a warrant. Today it is two strings. |
| `role_of:` | the emitters | A role-playing non-date dimension can emit one shared dimension in Cube and MetricFlow rather than two unrelated column families. |
| `same_as:` | RFC 0059 | A downstream project's `region` conformed with the platform's. Nothing else needs it, which is why it is last. |

### 5.5 Alternatives considered

**Declare hierarchy as an ordered list on the mart.** `levels: [country, state, city]`, one
key, obvious to read. Rejected: a hierarchy is a property of the *entity's* columns, not of a
mart that happens to carry them, so the same fact would be restated on every mart and the
restatements would disagree. It also cannot express a column determining two others
independently — a `postcode` determining both `state` and `delivery_zone` is a lattice, not a
list, and lists are exactly the shape that makes a lattice unrepresentable.

**Infer determination from the data.** One `GROUP BY` answers it exactly. Rejected on RFC
0003 alone, and on the same argument RFC 0074 D1 makes: an inference is indistinguishable from
a declaration once written down, and this one would be inferred from *one* load of a source
that happens not to have a counterexample yet.

**Reuse the entity relationship vocabulary.** Model `city` and `state` as entities with a
declared `many_to_one`, and let R002 do the work. Genuinely tempting — the mathematics is
identical and the rules exist. Rejected because it forces a dimension to be an entity with a
grain, a key and a mapping, which is a large modelling tax for a fact about two columns, and
because it would make every hierarchy level a node in the lineage graph. A project with a
five-level geography would gain five entities nobody builds.

**Do nothing, and let `keep:` mean whatever it means.** The status quo, and it is defensible:
no wrong number is currently attributed to this gap, unlike RFC 0074's and RFC 0075's. What
argues against it is §2's last point — RFC 0059 composes two projects' dimensions by name
alone, and the first conformed-dimension bug will be a cross-project one, which is the worst
place to meet it.

## 6. Tests

- **Unit:** `determines:` parses, closes transitively, refuses a cycle, and refuses naming a
  field the entity does not declare. `role_of:` and `same_as:` parse and refuse dangling
  names.
- **Semantic:** R020 proves a coarsening and refutes a rollup that keeps no determinant of a
  dropped dimension; R021 proves two roles comparable and refutes two unrelated columns.
- **Corpus:** no case converts. A new case is needed — *a rollup that keeps `state` and drops
  `city` alongside one that keeps `sku`* — and by RFC 0042 D4 it belongs in that corpus
  before it belongs here.
- **Golden:** a role-playing non-date dimension in the Cube and MetricFlow artifacts, because
  §5.4's emitter row is the only consequence visible in output.
- **Not tested:** that a declared `determines:` is true. It cannot be, it is the same standing
  as a declared `many_to_one`, and §9 says so where a reader meets it.

## 7. Docs

- A concepts page on dimensions as such. There is currently none — dimensions are described
  where marts, rollups and role-playing dates are described, which is three partial accounts.
- `UnsupportedHierarchy`'s remediation is rewritten once there is something better to say
  than "flatten it".
- The rollup how-to gains the coarsening distinction, which is the consequence an author will
  actually feel.

## 8. Out of scope

- **A `dimension:` document kind.** Tempting and larger: dimensions declared once, centrally,
  the way metrics are. This RFC attaches facts to columns where they already live. A central
  document is the escape hatch if per-column declarations prove unwieldy, named and not built.
- **Ragged and skip-level hierarchies.** A geography where some countries have no state is a
  real modelling problem and `determines:` states nothing about totality. Deliberately
  excluded rather than half-handled.
- **Aggregate navigation.** Answering a `state`-grain query from a `city`-grain mart by
  aggregating on the fly is the classic payoff of a hierarchy and a planner change, not a
  vocabulary one.
- **Dimension-level security.** RFC 0055's grants are per relation; per level is a different
  design.

## 9. Risks

- **A wrong `determines:` is invisible and consequential.** It produces a rollup proof that
  does not hold, which is a wrong number with a proof attached — worse than no proof. It has
  exactly the standing of a declared `many_to_one`, which is the precedent that makes it
  acceptable and also the precedent for how loudly the docs must say it.
- **Three relations is a lot of vocabulary for facts with few consumers today.** Two of the
  six consumers in §5.4 are future rules and one is a future RFC. The mitigation is §12's
  order and the honest admission that `same_as:` may never be needed.
- **It reads as OLAP nostalgia.** "Hierarchies and conformed dimensions" is Kimball
  vocabulary, and a reviewer may read the whole document as importing a modelling tradition
  rather than solving a problem. §2's four pointers into the tree are the answer, and the
  document has to lead with them rather than with the vocabulary.
- **The large-and-unscheduled combination rots.** A vocabulary RFC nobody executes is a
  document that goes stale while looking authoritative. Its status line says not scheduled and
  should keep saying so until a consumer is scheduled first.

## 10. Unresolved questions

- Whether `determines:` belongs on the **entity** or on the **canonical field**. A canonical
  field is shared across mappings and a determination is a property of the values, not of a
  feed — which argues for the catalog rather than the entity model, and cuts against RFC 0074
  D2's placement for a different reason.
- Whether R020 should **require** a determinant of every dropped dimension, or merely prove
  more when one is present. Requiring it refuses today's legal rollups; proving more leaves
  the `sku`/`city` rollup exactly where it is, which may be the honest answer.
- Whether two roles of one dimension are conformed **by construction** or need `same_as:`
  anyway. §5.3 assumes the former, which is what makes `same_as:` small; if it is wrong,
  `same_as:` becomes the primary relation and §12's order inverts.
- What a **date** is under this vocabulary. `DateRoleStep` already does roles and the date
  dimension already has levels — `day`, `month`, `year` are a declared hierarchy in all but
  name. Whether the general vocabulary absorbs it or sits beside it is a real choice, and
  absorbing it touches every existing project.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **Every relation is declared, never inferred.** Not from column names, not from cardinality, not from the data. One `GROUP BY` would answer `determines:` exactly and from a single load of a source that has no counterexample *yet*; an inference cannot be told from a declaration once written down. Same standing as a declared `many_to_one`, and the same posture RFC 0074 D1 takes for a zone. |
| 2 | `LOCKED` | **A fact with no consumer is not added.** Each of the three relations is listed in §5.4 with the rule or surface that reads it, and one that loses its consumer during execution is dropped rather than landed. A vocabulary that outruns its rules is a spec surface nobody can be refused by, which is a promise the compiler does not keep. |
| 3 | `LOCKED` | **A dimension is not an entity.** Modelling `city`/`state` as entities with a `many_to_one` would reuse R002 exactly and is rejected: it taxes a two-column fact with a grain, a key and a mapping, and it puts every hierarchy level into the lineage graph as a node nobody builds. |
| 4 | `ASSUMED` | **Determination is a lattice, not a list.** A column may determine several independently, and `postcode → {state, delivery_zone}` is the ordinary case rather than the exotic one. Departing means an ordered-levels spelling, which is smaller and cannot express it — the trade is stated in §5.5 rather than left to be rediscovered. |
| 5 | `ASSUMED` | **`role_of:` generalizes `DateRoleStep` rather than replacing it.** A date's roles expand into buckets, which is a date-specific elaboration, so the two coexist. Departing means absorbing dates into the general vocabulary, which §10 flags as touching every existing project. |
| 6 | `OPEN` | **Whether `determines:` lives on the entity model or on the catalog's canonical field.** A determination is a property of values rather than of a feed, which argues for the catalog; the entity model is where fields are otherwise described. The executor decides against the shape of both documents and logs it. |
| 7 | `OPEN` | **Whether R020 requires a determinant of every dropped dimension or merely proves more when one is present.** Requiring refuses rollups that are legal today; proving more leaves them where they are and may be the honest answer. Decide with one real rollup corpus in hand. |
| 8 | `OPEN` | **Whether `same_as:` is needed at all.** §5.3 argues the in-project case is derivable from `role_of:` and the cross-project case has no consumer until RFC 0059 P3. If both hold, this relation is not built. |

## 12. Phasing

Not scheduled, and phased so that each commit has a consumer before it lands. The order is
*by consumer*, which is the opposite of the order the relations are easiest to build in:

1. **`determines:`, and R020** — the one relation with a consumer that exists today, over a
   rollup vocabulary that is already shipped. Gated on RFC 0042 gaining the coarsening case
   (§6), because by D4 the corpus case comes before the rule that converts it.
2. **`role_of:`, and R021** — generalizing `DateRoleStep`, with the emitter consequence as
   the visible half.
3. **`same_as:`** — only if D8 resolves that it is needed, and not before RFC 0059 P3 gives
   it the cross-project consumer that is its only unambiguous one.

**P1 is worth doing alone.** If P2 and P3 never happen, `determines:` plus R020 still closes
the gap §2 opens with — a rollup that coarsens proving more than one that drops — and the
document can retire against that.
