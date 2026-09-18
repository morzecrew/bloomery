-- The per-order rollup the upstream system publishes: `average_item_price` is
-- already an average of that order's lines.
MODEL (
  name silver.order_summaries,
  kind FULL,
  grain order_id,
  references (order_id)
);

SELECT
  order_id::TEXT AS order_id,
  average_item_price::DECIMAL(12, 4) AS average_item_price,
  created_at::TEXT AS created_at
FROM bronze.corpus__order_summaries
