-- One row per order. Revenue is a fact about an order.
MODEL (
  name silver.orders,
  kind FULL,
  grain order_id
);

SELECT
  order_id::TEXT AS order_id,
  revenue::DECIMAL(12, 2) AS revenue,
  placed_on::DATE AS placed_on
FROM bronze.corpus__orders
