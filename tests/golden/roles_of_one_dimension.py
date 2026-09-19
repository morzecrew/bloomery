"""A project whose mart flattens two families declared roles of one dimension.

Inline rather than a fixture directory (S-0007/what-each-fact-buys): the
emitted artifact is where the general role becomes visible, and the smallest
project that shows it is two prefixed families over one entity — ``billing_``
and ``shipping_`` addresses — which no existing fixture declares.

Consumed by the Cube and MetricFlow goldens, which is why it lives beside them
rather than inside either.
"""

from __future__ import annotations

DOCUMENTS = {
    "entity_model": """\
spec_version: 1
entities:
  order:
    grain: one row per order
    key: [order_id]
    fields:
      order_id: {type: string, required: true}
      amount: {type: "decimal(12,4)"}
      order_date: {type: date}
      bill_to_id: {type: string}
      ship_to_id: {type: string}
  address:
    grain: one row per address
    key: [address_id]
    fields:
      address_id: {type: string, required: true}
      region: {type: string}
relationships:
  - name: order_of_billing_address
    from: order
    to: address
    via: {bill_to_id: address_id}
    cardinality: many_to_one
  - name: order_of_shipping_address
    from: order
    to: address
    via: {ship_to_id: address_id}
    cardinality: many_to_one
""",
    "mapping_orders": """\
mapping_version: 1
source: src__orders
target: order
key:
  order_id: {from: "$.id", transform: [to_string]}
fields:
  amount: {from: "$.amount"}
  order_date: {from: "$.od", transform: [{parse_date: ISO8601}]}
  bill_to_id: {from: "$.bill", transform: [to_string]}
  ship_to_id: {from: "$.ship", transform: [to_string]}
""",
    "mapping_addresses": """\
mapping_version: 1
source: src__addresses
target: address
key:
  address_id: {from: "$.id", transform: [to_string]}
fields:
  region: {from: "$.region"}
""",
    "metrics": """\
metrics_version: 1
metrics:
  revenue:
    grain: order
    additivity: additive
    agg: sum
    expr: "amount"
""",
    "marts": """\
marts_version: 1
marts:
  orders:
    grain: order
    base: order
    owner: analytics@example.com
    flatten:
      - {via: order_of_billing_address, prefix: billing_, role_of: address}
      - {via: order_of_shipping_address, prefix: shipping_, role_of: address}
      - {date: order_date, role: ordered}
    measures: [revenue]
    partition_by: [days(ordered_day)]
""",
}

#: MetricFlow refuses a project with marts and no time spine (S-0030 R1), so
#: the manifest golden loads this beside the documents above.
CATALOG = """\
catalog_version: 1
vertical: ecom_retail

date_dimension:
  name: dim_date
  grain: day
  start_year: 2020
  end_year: 2030
"""
