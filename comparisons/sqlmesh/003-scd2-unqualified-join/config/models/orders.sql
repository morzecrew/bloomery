-- One row per order, pointing at its customer. An order has one customer,
-- which is what `references` says.
MODEL (
  name silver.orders,
  kind FULL,
  grain order_id,
  references (customer_id)
);

SELECT
  order_id::TEXT AS order_id,
  customer_id::TEXT AS customer_id,
  created_at::TIMESTAMP AS ordered_at,
  amount::DECIMAL(12, 4) AS amount
FROM bronze.corpus__orders
