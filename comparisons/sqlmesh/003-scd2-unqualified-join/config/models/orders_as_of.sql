-- Each order with the tier its customer held when it was placed. The as-of
-- predicate is SQL this project's author wrote.
MODEL (
  name silver.orders_as_of,
  kind FULL,
  grain order_id,
  references (customer_id)
);

SELECT
  o.order_id,
  o.customer_id,
  o.amount,
  t.tier AS tier_at_order
FROM silver.orders AS o
JOIN silver.tier_versions AS t
  ON o.customer_id = t.customer_id
 AND o.ordered_at >= t.valid_from
 AND o.ordered_at < t.valid_to
