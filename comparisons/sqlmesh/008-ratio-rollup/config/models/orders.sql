-- One row per order, carrying what it earned and how many lines it had.
MODEL (
  name silver.orders,
  kind FULL,
  grain order_id,
  references (order_id)
);

SELECT
  order_id::TEXT AS order_id,
  revenue::DECIMAL(12, 2) AS revenue,
  item_count::INTEGER AS item_count,
  placed_on::DATE AS placed_on
FROM bronze.corpus__orders
