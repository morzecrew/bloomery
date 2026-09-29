-- One row per order: who bought, how much, and on which day.
MODEL (
  name silver.orders,
  kind FULL,
  grain order_id,
  references (customer_id)
);

SELECT
  order_id::TEXT AS order_id,
  customer_id::TEXT AS customer_id,
  amount::DECIMAL(12, 2) AS amount,
  ordered_on::DATE AS ordered_on
FROM bronze.corpus__orders
