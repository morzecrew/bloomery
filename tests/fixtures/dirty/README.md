# The dirty-data corpus

Seven CSV files, one per failure family, every row a deliberate specimen.

RFC [0016](../../../rfcs/0016-data-quality.md) §6 calls this corpus "the single
highest-value asset in this document," and Document 5 §8.1 puts the reason plainly:
**cleansing bugs are silent by nature — the pipeline is green, the numbers are wrong.**
A cleansing change that passes the whole corpus is safe to ship; one that changes a row's
disposition without a matching diff here is a regression that nobody would otherwise
notice until a dashboard total drifted.

## These files are DATA, not tests

There are no assertions here and no pytest files in this directory. The **policy** these
values are judged under lives in [`../dirty_corpus/`](../dirty_corpus/) — one entity per
failure family, declaring the default rule set the `_expected` column below is written
against. The suites that consume both are:

| Suite | What it asserts |
| --- | --- |
| [`tests/execution/test_dirty_corpus.py`](../../execution/test_dirty_corpus.py) | `_expected`, row by row, reading **both** sides of the quarantine split |
| [`tests/execution/test_dedupe_and_audits.py`](../../execution/test_dedupe_and_audits.py) | `keys.csv`'s dedupe order and the D21 blocking audit |
| [`tests/execution/test_merge_gates.py`](../../execution/test_merge_gates.py) | idempotence and full-refresh ≡ incremental |
| [`tests/execution/test_quarantine_replay.py`](../../execution/test_quarantine_replay.py) | the enum-widening walkthrough, `enums.csv`'s two `valid_but_unmapped` rows |
| [`tests/execution/test_quality_mart.py`](../../execution/test_quality_mart.py) | `gold.mart_data_quality`'s counts and the quarantine rate as a `MetricRequest` |
| [`tests/property/test_conservation.py`](../../property/test_conservation.py) | the conservation law over generated batches |
| [`tests/chaos/test_mutation_harness.py`](../../chaos/test_mutation_harness.py) | that the suites above would notice a deliberate lowering defect |

There were two departures from "every row is asserted". Both closed on 2026-08-10, and
what is left of them is two rows.

No corpus row cast cleanly and *then* violated a declared `range` bound, so the rule was
lowered, matrixed, reported in the quality mart, and diverted nothing anywhere in the
corpus. `keys.csv` now carries the adjacent pair `amount_at_range_min` /
`amount_below_range_min` — one ulp apart, opposite dispositions — which pins the bound's
inclusive edge as well as its firing (RFC 0016 D85).

`unicode.csv`'s `flag` marks encode a judgement about *deceptive characters* that no v1
rule could express. The `normalize` and `charset` rules (D86) now decide twenty of its
twenty-two specimens. The remaining two are named in the suite and are not gaps a bigger
character set would close: **`zero_width_joiner`** — U+200D is required by
`emoji_zwj_sequence` and forbidden here, so what separates them is *context* — and
**`combining_mark_alone`**, a well-formed, NFC-stable value holding no forbidden
character, whose problem is *where* the mark sits.

## The rule

**Every production incident adds a row.** Redact it, name the `_case` after the
mechanism rather than the customer, write the `_note` so the next reader understands why
the value is dangerous without having lived through the incident, and keep the file
small. This is a curated regression corpus, not a volume test — 139 rows across seven
files, and it should stay in that order of magnitude. A row earns its place by
representing a *class* of failure; a second row of the same class earns its place only
by disagreeing with the first about a disposition.

## What each file exercises

| File | Rows | Failure family | Rules exercised | Dispositions present |
| --- | --- | --- | --- | --- |
| `numerics.csv` | 20 | Locale, currency, notation and precision in a decimal field: comma decimals, ASCII vs thin-space grouping, currency prefixes, accounting negatives, scientific notation, Arabic-Indic digits, `decimal(38,9)` overflow, `NaN`/`Infinity`, the literal string `NULL`, negative zero, scale-overflow rounding | `coercible`, `pattern` | `pass`, `flag`, `quarantine`, `dialect_divergent` |
| `dates.csv` | 21 | Format ambiguity and impossible instants: DMY vs MDY (including the genuinely undecidable `01/02/2025`), offsets, ISO basic, the MySQL zero date, 2025-02-30, a non-leap Feb 29, a leap second, epoch `0`, spreadsheet serials, `9999-12-31` | `coercible`, `pattern`, `not_null` | `pass`, `quarantine` |
| `enums.csv` | 18 | Membership against `{paid, pending, refunded}`: case and whitespace variants, a misspelling, a numeric code, a zero-width space, an NBSP, a Cyrillic homoglyph, and two **valid-but-unmapped** values — the enum-widening path RFC 0016 calls the normal case, not the exception | `in_enum`, `in_set`, `coercible` | `pass`, `quarantine` |
| `keys.csv` | 22 | Identity and dedupe order: exact duplicates, a recency tie broken by `_load_id`, a tie broken through `_load_id` down to `_source_row_id` (D20's total order), case/whitespace near-duplicates that collide only after normalization, null and empty-string key parts, **deliberate ingestion-metadata violations** for the blocking audit, and the adjacent pair that pins §5.3's `range` bound | `dedupe`, `unique`, `not_null`, `range`, `coercible` (forced to `fail` on dedupe-referenced fields, D6) | `pass`, `dedupe_winner`, `dedupe_loser`, `quarantine`, `fail` |
| `refs.csv` | 16 | Referential integrity: an orphan FK (§5.4's `CASE` lowering), a NULL FK that is **not** an orphan (D19), an empty-string FK that **is** one, self-references, a mutual cycle, an FK to a row that quarantines on its own rules, and a source value colliding with the reserved `__unknown__` member | `referential` (`on_missing`), `not_null` | `pass`, `unknown_member`, `quarantine` |
| `unicode.csv` | 22 | Invisible and deceptive text: RTL mark and bidi override, ZWJ and ZWSP, NBSP, soft hyphen, a BOM inside a field, Cyrillic homoglyphs, fullwidth and Arabic-Indic digits, NFC vs NFD of the same string, an astral emoji, a ZWJ emoji sequence, a 13-codepoint grapheme cluster, U+FFFD, and the escape form of a lone surrogate | `pattern`, `length`, `unique`, `normalize`, `charset` | `pass`, `flag`, `quarantine` |
| `extremes.csv` | 20 | Boundaries: `decimal(38,9)` max/min and one-past, one ulp and half a ulp, signed zero, `NaN`/±`Infinity`, int64 max/min/overflow, epoch 0, year 0001 and 9999, empty string vs NULL **in one row**, a 10 000-character string, and an all-payload-empty row | `coercible`, `not_null`, `length`, `pattern` | `pass`, `flag`, `quarantine` |

## Column contract

Every file carries the same frame:

| Column | Meaning |
| --- | --- |
| `_load_id`, `_ingested_at`, `_source_row_id` | The RFC 0016 D21 ingestion metadata contract. Entities using `quarantine` or `dedupe` require all three; `_source_row_id` is NOT NULL and unique per source row, and `reject_id` is the sha256 over the length-prefixed utf-8 pair (`source_relation`, `_source_row_id`). Those are data properties no compiler can check, so the lowering emits a generated blocking audit — and `keys.csv` carries the specimens that audit must catch. |
| `_case` | Snake-case name of the failure mechanism. Unique within a file; the stable handle a test parametrizes over. Rows reference each other by `_case`, never by position. |
| *(payload)* | The specimen itself — `raw_amount`, `raw_date`, `raw_status`, `raw_name`, `raw_value`, or the key/FK columns. |
| `_expected` | Intended disposition under the documented default rule set (see below). |
| `_note` | Why the value is dangerous, and which RFC 0016 decision governs it. |

Two files add a column: `unicode.csv` has `_codepoints`, which spells out the U+ sequence
because the whole point of that file is that the characters are invisible; `refs.csv` has
`_parent_status` ∈ `{present, absent, quarantined, not_applicable}`, which declares the
condition a suite must seed on the *referenced* side — the corpus states the fact, the
spec states the policy.

### `_expected` vocabulary

`pass` · `flag` · `quarantine` · `fail` · `unknown_member` · `dedupe_winner` ·
`dedupe_loser` · `dialect_divergent`

`flag`, `quarantine` and `fail` are RFC 0016 §5.1's `OnFail` members. `unknown_member` is
the `referential.on_missing` outcome. `dedupe_winner`/`dedupe_loser` name which side of a
dedupe partition a row lands on. `dialect_divergent` marks a row whose disposition is a
*property of the engine*, not of the data — DuckDB accepts `1.2e3` in a `DECIMAL` cast
and trims surrounding whitespace before casting; other engines do neither. Those rows
belong to the dialect matrix (§6), and a suite must not assert a single answer for them.

`_expected` records the disposition under the **default** rule set — `coercible` at its
default `quarantine`, no locale-aware or accounting transform declared, `in_enum`
case-sensitive, `referential.on_missing: unknown_member`. Many rows would land elsewhere
under a different declaration, and the `_note` says so where it matters. That is the
point: RFC 0016 D1 holds that specs describe and never guess, so `12,50` quarantines
until someone declares what it means.

## File format contract

Verified against both parsers; a change that breaks any of this breaks the corpus.

- **UTF-8, no BOM**, LF line endings, no CR anywhere, exactly one terminating newline.
  U+FEFF appears only as a *field value* in `unicode.csv` — the file itself has none.
- Written with `csv.QUOTE_STRINGS`, which makes the corpus's one subtle distinction
  representable: a **quoted** empty field (`""`) is the empty *string*, an **unquoted**
  empty field is SQL NULL. `extremes.csv` carries both in a single row
  (`_case = empty_string_vs_null`), and `refs.csv`, `keys.csv`, `enums.csv`, `dates.csv`
  and `unicode.csv` each pair a null specimen against an empty-string one. Per D19 those two
  values belong to different rules — `not_null` owns one, `coercible`/`length` the other
  — so conflating them silently drops half the specimens.
- Quoting everything else is deliberate too: leading and trailing whitespace survives and
  stays visible in a diff.
- No embedded newlines in any field, so the row count equals the line count minus one.

### Reading it

```python
rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
```

```sql
SELECT * FROM read_csv('numerics.csv',
                       header = true,
                       all_varchar = true,          -- do not sniff
                       allow_quoted_nulls = false)  -- keep "" distinct from NULL
```

Both flags matter. Python's `csv` yields `''` for a NULL field and cannot distinguish the
two on read, so tests that care about the distinction must read through DuckDB — and
DuckDB's default `allow_quoted_nulls = true` collapses `""` to NULL, destroying it.
`all_varchar` matters just as much: under the default sniffer DuckDB types `keys.amount`
as `DOUBLE`, and a float in a decimal pipeline is exactly the corruption RFC 0003 bans
from the IR and every emission path.

Both parsers agree on every value in every file (139 rows, DuckDB NULL read as `''`),
which is the property to re-check after any edit.
