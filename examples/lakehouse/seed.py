"""Render `seed/` into the Trino SQL that lands the bronze layer.

    uv run python examples/lakehouse/seed.py | \\
        docker exec -i bloomery-lakehouse-trino-1 trino -f /dev/stdin
    just seed                                        # the same, shorter

The data lives in `seed/` in the shape each source really ships: two CSV
exports, one newline-delimited JSON event stream. This script only translates —
it invents no values and cleans nothing, because cleaning is the mappings' job
and doing any of it here would make the example prove itself.

**Everything lands as VARCHAR**, except the one timestamp the quarantine
contract requires. That is not laziness: bronze is landed text, and every cast
in this project belongs to a mapping's declared transform chain. A loader that
helpfully typed `list_price_cents` as an integer would be doing a mapping's job
and hiding the ' 1250' that its `trim` step exists for.

Nested JSON keeps its nesting. Each event's top-level keys become columns and
anything below them is re-serialized into a JSON *string* — which is what a
webhook landing table actually looks like, and what makes
`$.payload.pricing.line_total_cents` in the mapping a JSON extraction off a
physical column rather than a field somebody's ingester shredded in advance.

Standard library only, deliberately: this file is part of the example, and an
example that needs its own dependencies is not self-contained.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).parent
SEED = HERE / "seed"

#: ``bronze`` relation name → the file it is loaded from. The relation names
#: are exactly the ``source:`` of each mapping; that correspondence is the whole
#: contract between a bronze table and a mapping.
SOURCES: tuple[tuple[str, str], ...] = (
    ("catalogue__products", "products.csv"),
    ("crm__customers", "crm_customers.csv"),
    ("shopify__order_lines", "shopify_order_lines.jsonl"),
    ("woo__order_lines", "woo_order_lines.csv"),
)

#: Columns that land as something other than VARCHAR. Exactly one, and it is
#: required rather than chosen: the ingestion-metadata contract (RFC 0016 D21)
#: makes `_ingested_at` the time a reject row is measured against, and a
#: retention window over a string is not a window.
#:
#: It is also the one timestamp in `seed/` still written with a space rather
#: than the ISO `T`, and for a reason worth keeping: this cast is Trino's own,
#: not one bloomery emits, so nothing normalizes the separator for it. Every
#: *mapped* timestamp uses the `T` form, which is what the storefront and the
#: CRM actually export — and what a bloomery of an earlier version would have
#: quarantined every row over.
TYPED: dict[str, str] = {"_ingested_at": "TIMESTAMP"}


def quote(value: str | None) -> str:
    """A SQL literal for one landed value, NULL included."""
    if value is None:
        return "NULL"
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def typed(column: str, value: str | None, *, first: bool) -> str:
    """One VALUES cell.

    A column in :data:`TYPED` carries its type marker on **every** row, because
    a VALUES column whose rows disagree about type is an error rather than a
    coercion. Every other column is cast on the first row only, and that one
    cast is what fixes the column's type for the whole table: left to infer,
    Trino gives a VALUES column the narrowest varchar that fits the widest
    literal present — so the table would be born `varchar(19)`, and the first
    INSERT of a longer string (`just break-it` does exactly that) would fail on
    a width nobody chose and nothing documents.
    """
    literal = quote(value)
    if column in TYPED:
        kind = TYPED[column]
        return f"CAST(NULL AS {kind})" if value is None else f"{kind} {literal}"
    return f"CAST({literal} AS VARCHAR)" if first else literal


def flatten(event: dict[str, object]) -> dict[str, str | None]:
    """One JSON event's top-level keys, with anything nested re-serialized.

    ``sort_keys`` is off on purpose: the payload should reach bronze looking
    like what the shop sent, and re-ordering its keys here would quietly make
    the landed text differ from the wire text.
    """
    row: dict[str, str | None] = {}
    for key, value in event.items():
        if value is None:
            row[key] = None
        elif isinstance(value, (dict, list)):
            row[key] = json.dumps(value, separators=(",", ":"))
        else:
            row[key] = str(value)
    return row


def read_csv(path: Path) -> tuple[tuple[str, ...], list[dict[str, str | None]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        rows: list[dict[str, str | None]] = [dict(row) for row in reader]
    return columns, rows


def read_jsonl(path: Path) -> tuple[tuple[str, ...], list[dict[str, str | None]]]:
    rows = [flatten(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]
    # Column order follows first appearance across the file rather than the
    # first event alone: a key that only later events carry still gets a column.
    columns: list[str] = []
    for row in rows:
        columns.extend(key for key in row if key not in columns)
    return tuple(columns), rows


def table(relation: str, filename: str) -> str:
    path = SEED / filename
    reader = read_jsonl if path.suffix == ".jsonl" else read_csv
    columns, rows = reader(path)
    values = ",\n  ".join(
        "(" + ", ".join(typed(c, row.get(c), first=index == 0) for c in columns) + ")"
        for index, row in enumerate(rows)
    )
    return (
        f"DROP TABLE IF EXISTS iceberg.bronze.{relation};\n"
        f"CREATE TABLE iceberg.bronze.{relation} AS\n"
        f"SELECT * FROM (VALUES\n  {values}\n) AS t ({', '.join(columns)});"
    )


def main() -> None:
    print("CREATE SCHEMA IF NOT EXISTS iceberg.bronze;")
    for relation, filename in SOURCES:
        print(f"\n-- {relation}  <-  seed/{filename}")
        print(table(relation, filename))


if __name__ == "__main__":
    main()
