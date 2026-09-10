# RFC 0066 — Completing the semantic plan

- **Status:** 📝 Draft
- **Scope:** The node vocabulary of `bloomery.semantic.plan` and the proof rules that
  authorize its new members, so that every request bloomery answers carries a derivation
  and `QueryPlan.semantic` stops being optional. Four request shapes are answered today
  with no plan at all; this document adds the nodes that can state them and the rules that
  close their obligations. It changes no spec grammar, no artifact bytes and no emitter:
  the blast radius is `semantic/plan.py`, `planner/semantic_plan.py`, the rule registry in
  `semantic/`, and the corpus cases that convert. It does **not** wire a target to the
  plan — nothing lowers from a `SemanticPlan` today and nothing does after this either.
- **Related:** [`src/bloomery/semantic/plan.py`](../src/bloomery/semantic/plan.py) — the
  five-member node vocabulary;
  [`src/bloomery/planner/semantic_plan.py`](../src/bloomery/planner/semantic_plan.py) —
  `_plannable`, `build` and `compose`, the three places a plan is declined;
  [`src/bloomery/planner/compose.py`](../src/bloomery/planner/compose.py) — the composed
  statement that computes above the join without a node for it;
  [RFC 0039](0039-semantic-proof-ir.md) — the proof vocabulary these rules mint into;
  [RFC 0042](0042-semantic-bug-corpus.md) — the cases that supply the evidence;
  [RFC 0045](0045-soundness-positioning.md) — the claim this unblocks, held by its D2;
  RFC 0040 (the plan IR, retired — readable at `efba2b6`); RFC 0041 (multi-grain planning,
  retired — readable at `654d93e`).
- **Origin:** Executing RFC 0045 established that its §2 cannot be published, and why:
  `QueryPlan.semantic` is optional and four shapes leave it `None`
  ([`logs/T-0036.md`](../logs/T-0036.md)). That is a documentation decision blocked on a
  capability nothing in the corpus owned — 0040 owned the plan IR and has retired, and
  0039's seven rules name none of the three missing operations.

---

## 1. Summary

`SemanticPlan` has five node kinds — scan, filter, aggregate, projection, branch join — and
**none of them states arithmetic, a semi-additive reduction, or a window.** So a request
naming a ratio, a semi-additive measure, a cumulative metric, or two metrics restricted
differently is answered without a plan: the SQL is produced, the answer is returned, and
`QueryPlan.semantic` is `None`.

This RFC adds three nodes and the rules that authorize them, and makes the field
non-optional. The point is not the nodes. It is that "bloomery refuses what it cannot
derive" becomes true of every request rather than of the subset that happens to fit four
operators.

## 2. Motivation

Today a caller cannot tell a plan-backed answer from a plan-less one without inspecting
the field, and nothing in the API suggests they should. Both come back as a `QueryPlan`
with SQL in it.

That is a soundness gap and a documentation gap at once. RFC 0045 §2 wants to say:

> If bloomery cannot construct that derivation, it refuses the request.

It cannot say it. The honest statement today is "if bloomery cannot construct the
derivation, it answers anyway, through a path whose reasoning is a coverage precheck and
an embedded engine" — which is the shape RFC 0040 §6 was written to replace and which
survives, unnoticed, in the four shapes its P1 could not express.

The gap is invisible from every direction that matters. The suite is green: no test
asserts that a given request *has* a plan, because `None` is a legal value. The docs are
accurate: they never promised one. And the two places that decline are documented,
carefully, as deliberate — which they were, per phase, and which reads as settled rather
than as owed.

**What it costs concretely.** RFC 0043's matrix scores bloomery on cases it cannot yet
derive. RFC 0045 stays 🚧 indefinitely, holding a `LOCKED` row against a capability with no
owner — the failure mode this corpus has now hit twice (RFC 0058 D8, orphaned by its own
retirement). And every future statement about what bloomery derives has to carry the
subset it is true of.

## 3. Current state

Verified against the code, not from memory.

**The vocabulary is closed at five** (`semantic/plan.py`):

```python
PlanNode = Scan | Filter | Aggregate | Project | JoinAggregates
```

Its own comment records the two RFC 0040 §4 named and never built: `PreservingJoin`, which
would join *unaggregated* rows and which RFC 0041 D10 deliberately keeps refused, and
`ConvertUnit`, which "arrives with RFC 0038's unit work" — **RFC 0038 has since retired**,
so that node has no owner either (§8).

**Three places decline to build a plan**, and all three give one reason.

`_plannable` (`planner/semantic_plan.py`) requires four properties of a single-mart
request, each stated as a property rather than an observed counterexample, after "the
enumerating version of this guard missed two shapes in a row":

1. every requested metric is a **stored measure of the covering mart**, so R008 is true
   beneath the aggregate and no node is needed for a derivation;
2. every one is **a plain aggregate over the scan** — `_PLAIN_AGGREGATE` is
   `(ADDITIVE, DISTINCT_COUNT)`. A semi-additive measure is lowered as a first/last pick
   over its own dimension and then summed, "which one `Aggregate` cannot say" — and note
   that the docstring's own "first/last" is narrower than `SemiAdditiveRule`, which has
   five members (§5.3);
3. none is **cumulative**, "since a window and a `period_agg` are not a rollup at all";
4. all are **restricted alike**, because one `Filter` over the scan says one thing about
   every measure beneath it.

`compose` declines on top of that whenever `computed=True` — a metric produced by an
expression above the join — and says why in the sentence this whole RFC turns on:

> §4's vocabulary is a scan, a filter, an aggregate, a projection and a join, and none of
> them states arithmetic — so naming the metric in `Project.columns` would claim the join
> produced a column the join does not produce.

`compose.py` meanwhile *does* compute above the join: `Measure.expr` carries the
expression and `Measure.inputs` resolves each name to a branch and column. **The
arithmetic is already modelled — in the SQL builder, where no proof can reach it.**

**What is already in place.** `SemanticPlan.check()` refuses any node whose `claims`
property is true and whose proof is absent or not closed, and it refuses an empty plan.
`Proof`, `Provenance`, `SemanticFact` and the rule registry exist (RFC 0039). R012, derived
ratio reconstruction, **is already minted** — the rule for the first missing node exists
while the node does not. R013 is the rollup obligation, so R014 and R015 are the next free
ids.

**And the corpus does not hold what this document first assumed it did.** RFC 0042's two
`unguarded` cases are `009-null-denominator` and `011-timezone-boundary`; neither is
semi-additive or cumulative, and their "future rule" is not one of these. The
semi-additive case, `005-semi-additive-balance`, has its `declared` expectation
**`accepted` already** — citing `RFC 0006 D6`, a retired guardrail decision, rather than a
proof rule. And there is **no cumulative case in the corpus at all**.

That is not an obstacle to route around; it is the fact that decides D5. These rules are
not the kind that converts a refusal into an acceptance. Every shape here is answered
correctly today — what is missing is the derivation, not the answer — so `SafeQueries` does
not grow, RFC 0039 D4's monotonicity is untouched, and RFC 0042 D5's "a rule with nothing
to convert" bar does not apply, because it was written for rules that widen capability.
Applying it here would block a rule whose whole purpose is to explain an acceptance that
already exists.

## 4. Goals / Non-goals

**Goals**

- Three new node kinds: arithmetic, semi-additive reduction, window.
- The rules authorizing the two that make claims nothing currently covers.
- `QueryPlan.semantic` becomes non-optional.
- The corpus cases for these shapes cite a **rule** where they now cite a retired
  guardrail decision, which is what makes the rules evidence-backed rather than asserted.

**Non-goals**

- **Lowering a target from the plan.** Nothing consumes a `SemanticPlan` today and nothing
  does after this. That is RFC 0040 §6's other half and it needs its own document; wiring
  it here would change what the SQL is generated from, and the parity argument below
  depends on that not happening.
- **`PreservingJoin`.** Joining unaggregated rows stays refused (RFC 0041 D10). This
  document adds no capability to answer a request that is refused today.
- **New spec grammar.** Every shape here is already declarable and already answered; what
  is missing is the derivation, not the feature.
- **`ConvertUnit`.** Named in §8 with its owner problem, not built.

## 5. Design

### 5.1 The shape of the addition

Each new node follows the existing contract exactly: a frozen slots dataclass with
`multiplies`, `claims`, `document()` and `render()`, an optional `proof`, and canonical
ordering in `__post_init__` where a collection is unordered. `check()` needs no change —
it asks the node whether it claims rather than testing membership in a list, which is the
property RFC 0041 D14 chose it for.

```python
PlanNode = Scan | Filter | Aggregate | Project | JoinAggregates | Compute | Reduce | Window
```

### 5.2 `Compute` — arithmetic above an aggregate

States that a column is computed from other columns of the same relation, after they were
aggregated. It is the node `compose` says does not exist, and the node `build` needs for a
ratio or an **offset-free** `derived:` metric on a single mart.

**The offset case, which nearly became a fourth node.** `MetricInputIR` carries an optional
`offset_window` / `offset_to_grain`, so a `derived:` input may read its metric at a shifted
period, and such a request *is* answered today — `planner/explain.py` renders the offsets
into its explanation. An offset input is not a column of the relation `Compute` computes
over; it is a second read of the same relation at a different time range, so no arithmetic
node can state it.

It needs no new node either. Two branches over the **same** mart, differing only in their
`Filter`, each ending in an aggregate to the request's keys, joined by `JoinAggregates` and
computed above by `Compute` — which is structurally what the cross-mart case already does,
and R010 authorizes the join for the same reason: each branch is unique at the keys because
of the aggregate beneath it. `JoinAggregates` requires two branches and does not require
them to scan different relations.

Stated here rather than discovered in P4, because the alternative reading — an offset node —
was the obvious one and would have put a second scan-shaped concept in a vocabulary that
already has `Scan`.

```python
@dataclass(frozen=True, slots=True)
class Compute:
    #: Output column → the expression producing it, in the neutral vocabulary.
    #: Rendered as prose like `Filter.predicates`: a plan is not SQL.
    outputs: tuple[tuple[str, str], ...]
    #: What each referenced name resolves to, so a reader can check the
    #: expression against columns the plan actually produces.
    inputs: tuple[str, ...]
    proof: Proof | None = None
```

`claims` is **true**. The claim is not the arithmetic — division is division — but the
*ordering*: that computing this expression after aggregation is the same number as the
metric declares. `SUM(a)/SUM(b)` and a row-level `a/b` summed afterwards are different
numbers, which is RFC 0041 D1, and R012 is the rule that says which one the declaration
means.

`multiplies` is false.

### 5.3 `Reduce` — one named dimension collapsed by a declared rule

States what a semi-additive measure is lowered as before anything is summed: the `over:`
dimension reduced away by the declared rule, leaving one value per group. Today `build`
refuses these because "one `Aggregate` cannot say" it, and the plan would read as a plain
sum.

```python
@dataclass(frozen=True, slots=True)
class Reduce:
    #: The grain a row is identified by once `over` is gone.
    output_grain: str
    #: The dimension reduced away — a semi-additive measure's `over:`.
    over: str
    #: The full `SemiAdditiveRule` vocabulary.
    rule: SemiAdditiveRule
    measures: tuple[str, ...]
    proof: Proof | None = None
```

**Named `Reduce` rather than `Pick`, and carrying all five rules.** `SemiAdditiveRule` is
`last`, `first`, `avg`, `min`, `max` — verified, and three of them select no row at all.
A node called `Pick` would have been right about two members of a five-member vocabulary
and would have needed a comment arguing the name away, which is the shape this codebase
has already had to rename once.

It is distinct from `Aggregate` in what authorizes it, not in what it does to rows. An
`Aggregate` reduces by the metric's own declared aggregation and is authorized by the mart
contract; a `Reduce` collapses one *named* dimension by the semi-additive rule, and is
authorized by that declaration. Two nodes because two different facts license them.

`claims` is **true**: reducing along `over:` asserts that the surviving value represents
the group, which is exactly what the declaration says and what makes summing across the
*other* dimensions legitimate afterwards.

`multiplies` is false — it reduces.

**New rule, R014** — *semi-additive reduction*: a measure declared `semi_additive` with
`over: d` and any `rule:` of the five may be reduced along `d` by that rule, and the result
aggregated across dimensions other than `d`. Premised on the declaration (`DECLARED`
provenance) and on `d` being a dimension of the scanned relation. It says nothing about
aggregating along `d` itself, which stays refused — that is the whole content of
`semi_additive`.

### 5.4 `Window` — accumulation across rows at query time

States a cumulative metric's window: what accumulates, over what ordering, within what
reset boundary.

```python
@dataclass(frozen=True, slots=True)
class Window:
    measures: tuple[str, ...]
    #: The ordering the window runs along.
    over: str
    #: `trailing` with a span, or `grain_to_date` with its reset grain —
    #: the two forms RFC 0034 declares.
    frame: str
    proof: Proof | None = None
```

`claims` is **true**, and this one is worth stating carefully: a window's result is not a
rollup of its input, so a reader who sees `Aggregate` beneath it must not conclude the
window's output can be rolled further. The proof records what the frame is, so that any
later transformation has something to refuse against.

`multiplies` is false: a window adds a column, not rows.

**New rule, R015** — *declared window*: a metric declaring `cumulative:` may be computed as
a window over the declared ordering with the declared frame, and its result is **not**
re-aggregable — the judgement is terminal. `RESOLVABLE` for a window output is empty, and
R013 (rollup) must refuse it, which it already does by class.

### 5.5 Per-measure restriction

The fourth shape needs no node. A restriction removes rows and invents none, which is why
`Filter.claims` is false — so what is missing is not authorization but *expressiveness*:
one `Filter` over the scan cannot say that two measures beneath it are restricted
differently.

Two shapes, and the choice is deliberately left `OPEN` (D7):

- **a scope on the node** — `Filter` gains an optional `measures: tuple[str, ...]`, empty
  meaning "every measure", and a plan carries several;
- **a scope on the aggregate** — `Aggregate` carries its own per-measure predicates.

The first keeps one node type for one concept and makes the plan's node list longer; the
second keeps the restriction beside the thing it restricts and puts predicate text on a
node whose job is grain. Both are honest and the implementer will see which reads better
against `resolve.build._metric_filters`, which already holds the authored clauses.

### 5.6 Making the field non-optional

`QueryPlan.semantic: SemanticPlan` — no default.

This is the completion criterion and the reason for the ordering below: it can only be
done once nothing returns `None`, so it is the last change rather than the first, and it
is what stops the gap silently reopening. Until then, `None` is a legal value and no test
can assert its absence.

**A plan is still not a rendering, and this changes nothing about that** (RFC 0040 D4).
MetricFlow and `compose.py` continue to produce the SQL. The plan states what bloomery
decided; that a target lowers from it is a different document's work (§4).

### Alternatives considered

**Refuse the four shapes instead.** `QueryPlan.semantic` becomes non-optional immediately
and §2 becomes true the same day. It is also a capability regression sold as a soundness
improvement: four request shapes that are answered correctly today would start refusing,
and the refusal would be "bloomery cannot describe this", not "this is unsafe". D2 forbids
it.

**One escape-hatch node.** A single `Opaque(description, proof)` covering everything the
vocabulary cannot state. It makes the field non-optional with one node instead of three,
and it makes `check()` meaningless: every shape nobody modelled arrives as a closed proof
of nothing. This is the hand-authored escape hatch of RFC 0058 D3 in a different costume.

**Leave the field optional and document the subset.** Cheapest, honest, and it makes the
soundness claim permanently conditional — every future statement about what bloomery
derives would carry "for requests of the following four shapes". RFC 0045 §8's four
questions would be answerable but the answers would be a list, and a guarantee stated as a
list of exceptions is one nobody can hold in their head.

## 6. Tests

- **Every node with its rule, refused without it.** Constructing a claiming node with no
  closed proof must fail `check()` — the test exists for `Aggregate` and extends by
  construction, but the *new* node's version is what proves `claims` was actually set.
- **The corpus case re-cites its rule.** `005-semi-additive-balance`'s `declared`
  expectation is `accepted` today citing `RFC 0006 D6` — a retired guardrail decision. With
  R014 it cites R014, which is the observable difference between "a check found nothing
  wrong" and "here is why it is right". The cumulative shape has **no case at all**, so
  P3 writes one (§10) before minting R015; a rule whose evidence is a case written to
  demonstrate the rule is worth less than one converting a case that predates it, and that
  weakness is stated rather than hidden.
- **Parity: no request changes outcome.** The suite RFC 0040 §8 established has a fixed
  reference; every request answered today is answered identically after, with a plan
  attached. A request that starts refusing is a bug in this RFC, not a tightening.
- **The gap cannot reopen.** Once `semantic` is non-optional, a property test over the
  corpus asserting every answered request carries a plan is redundant with the type — but
  a test asserting that `_plannable`'s conditions are *gone* rather than merely widened is
  not. Whichever guard replaces it must not be a list of shapes.
- **A window's output refuses further rollup.** R013 already refuses by class; the test is
  that a `Window` node's judgement cannot be a premise of an `Aggregate` above it.

## 7. Docs

`pages/docs/concepts/what-bloomery-proves.md` carries a note saying the conversion from
"a documented check found nothing wrong" to "a positive derivation" is ongoing. When this
lands, that note is rewritten and RFC 0045 §2 and §7's second sentence are published — 0045
retires in the same change, which is the point of doing this at all.

`pages/docs/how-to/plan-a-metric-request.md` gains the plan as something a caller can read
back, once it is always there.

## 8. Out of scope

- **`ConvertUnit`.** RFC 0040 §4 named it, `plan.py`'s comment says it "arrives with
  RFC 0038's unit work", and RFC 0038 retired without it. Its nearest live home is
  RFC 0061, which is about a declared input currency and its proof rule — close, not the
  same. Named here so the orphan is written down somewhere; not claimed by this document,
  because a unit conversion node without RFC 0038's unit algebra in front of it would be a
  node with nothing to say.
- **Target lowering from the plan.** §4.
- **Widening what is answerable.** Every shape here is answered today.
- **A period-offset node.** Not needed: the shape composes from two same-mart branches and
  a `Compute` above the join (§5.2). Named here because "add a node for it" is the reading
  a reader arrives with, and the composition is the reason this RFC is three nodes rather
  than four.

## 9. Risks

- **Being built as three nodes and stopping.** The nodes are the interesting part and the
  non-optional field is the part that matters; a phase that adds nodes and leaves the
  default in place has changed nothing a caller can rely on. D3 exists to make that
  visible.
- **A rule minted to fit the node.** R014 and R015 are written here from the declarations
  they read, but a rule invented to make a node constructible — rather than to state
  something true — passes every test in this document. This risk is *higher* here than for
  R011 or R012, precisely because these rules convert nothing: there is no case that goes
  from wrong number to right number to keep them honest. The check that remains is that
  the rule states something falsifiable about the declaration it reads, and D5 is written
  to say so rather than to borrow RFC 0042 D5's bar, which does not fit.
- **`claims` set false to avoid writing a rule.** `check()` asks the node, so a node that
  declares itself claimless is exempt from proof forever, silently. This is the cheapest
  way to make this RFC look finished and is the one thing review should look for first.

## 10. Unresolved questions

- Whether per-measure restriction is a scope on `Filter` or on `Aggregate` (§5.5, D7).
- Whether a `Window` output should be representable in a mart at all, or stays
  query-time only. It is query-time only today by accident of what was built, not by a
  decision anyone wrote down.
- **What the cumulative corpus case should be.** There is none, and P3 needs one. It
  cannot be an `unguarded` case, because the cumulative shape is answered correctly — so
  it is a case demonstrating that the *plan* now states the window, which is a weaker kind
  of evidence than RFC 0042's cases usually carry. Whether that belongs in 0042 at all, or
  is a plan-level fixture of its own, is a question for whoever writes it.
- Whether `_plannable` survives at all after this, or whether its four conditions become
  a dispatch to the node that states each shape. The second is the shape that cannot
  silently regrow a list of exclusions.

## 11. Decisions

| # | Grade | Decision |
| --- | --- | --- |
| 1 | `LOCKED` | **The completion criterion is `QueryPlan.semantic` becoming non-optional**, not the node count. A phase that adds nodes and leaves the field optional has changed nothing a caller can depend on and nothing RFC 0045 §2 can be published against. Locked because it is the whole purpose: every other row here is a means to it, and a plan-shaped deliverable that stops short would read as done. |
| 2 | `LOCKED` | **No request that is answered today may start being refused.** Making the field non-optional by refusing the four shapes satisfies row 1 and is a capability regression sold as a soundness improvement — the refusal would mean "bloomery cannot describe this", which is not a safety statement. Locked because it is the cheap path to a green suite and it would be defended as rigour. |
| 3 | `LOCKED` | **Every node that makes a claim ships with the rule that closes it, in the same change.** `check()` asks the node whether it claims, so a node landing with `claims = False` is exempt from proof permanently and invisibly. A node and its rule are one unit of work; splitting them is how the exemption gets introduced as temporary. |
| 4 | `ASSUMED` | **Three nodes, one per operation kind — arithmetic, reduction, window — rather than one general node.** A single opaque node satisfies row 1 with a third of the work and makes `check()` meaningless: every unmodelled shape arrives as a closed proof of nothing. Not `LOCKED` because a fourth shape might genuinely warrant merging two of these; the escape-hatch shape is what row 3 and RFC 0058 D3's reasoning refuse. |
| 5 | `ASSUMED` | **These rules explain an existing acceptance rather than converting a refusal, and are held to that bar instead of RFC 0042 D5's.** Every shape here is answered correctly today, so `SafeQueries` does not grow and no case moves from `unguarded` to `accepted` — checked, not assumed: the two `unguarded` cases are unrelated, `005-semi-additive-balance` is already `accepted` citing a retired guardrail row, and no cumulative case exists (§3). D5's "a rule with nothing to convert" was written for capability-widening rules and would block these for lacking evidence they cannot in principle have. The bar instead: the rule states something falsifiable about the declaration it reads, and the corpus case that was accepted on a guardrail's authority now cites the rule. |
| 6 | `ASSUMED` | **`Compute` carries a proof because the *ordering* is the claim, not the arithmetic.** Division needs no authorization; computing after aggregation rather than before is RFC 0041 D1 and changes the number. Not `LOCKED` because if a later reading shows the ordering is structural — forced by where the node sits — the proof becomes decoration and the row should be revisited rather than defended. |
| 7 | `OPEN` | **Whether per-measure restriction scopes on `Filter` or on `Aggregate`** (§5.5). One node type per concept against keeping the restriction beside what it restricts. Execution decides against `resolve.build._metric_filters`, which already holds the authored clauses, and logs which and why. |
| 8 | `OPEN` | **What replaces `_plannable`.** Its four conditions exist to decline; once nothing declines they are either deleted or turned into a dispatch to the node stating each shape. The second cannot silently regrow into a list of exclusions, which the enumerating version of that guard already did twice — but it is a bigger change, and the choice belongs to whoever sees both shapes against the code. |

## 12. Phasing

**P1 — `Compute`, and the ratio that already has its rule.** R012 is minted and the node is
not, which makes this the phase with the least new reasoning: add the node, let `build`
state a single-mart ratio and an offset-free `derived:` metric, and let `compose` drop its
`computed=True` refusal. No new rule, so nothing here depends on the corpus. The
offset-bearing input composes from branches and lands in P4, where `_plannable`'s first
condition is retired rather than narrowed.

**P2 — `Reduce` and R014.** The semi-additive shape. First phase that mints a rule, so D5
first applies here — and note what it asks for: `005-semi-additive-balance` is `accepted`
today on `RFC 0006 D6`'s authority and re-cites R014, rather than converting from
`unguarded`.

**P3 — `Window` and R015.** The cumulative shape and the terminal judgement. The only phase
with no existing corpus case, so it writes one first (§10) — and the weakest phase
evidentially, which is a reason to do it after P2 rather than a reason to skip it.

**P4 — per-measure restriction, and the field.** D7's choice, then
`QueryPlan.semantic: SemanticPlan` with no default, then D8's call on `_plannable`. Last
because row 1's criterion can only be met once nothing returns `None` — and this is the
phase that lets RFC 0045 §2 be published and 0045 retire.
