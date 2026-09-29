-- One row per order. Shipping is a fact about an order and is stored here once.
MODEL (
  name silver.orders,
  kind FULL,
  grain order_id,
  references (order_id)
);

SELECT
  order_id::TEXT AS order_id,
  shipping::DECIMAL(12, 4) AS shipping,
  created_at::TEXT AS created_at
FROM bronze.corpus__orders
