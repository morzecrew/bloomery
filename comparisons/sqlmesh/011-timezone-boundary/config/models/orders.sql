-- Orders as the source system publishes them: a local wall-clock string with
-- no zone on it. The zone the store runs on is documentation, and there is
-- nowhere in this block to write it down.
MODEL (
  name silver.orders,
  kind FULL,
  grain order_id,
  references (order_id)
);

SELECT
  order_id::TEXT AS order_id,
  revenue::DECIMAL(12, 2) AS revenue,
  placed_at::TIMESTAMP AS placed_at
FROM bronze.corpus__orders
