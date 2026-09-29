-- One row per order line, pointing at its order. Discount is a fact about a line.
MODEL (
  name silver.order_items,
  kind FULL,
  grain (order_id, line_no),
  references (order_id)
);

SELECT
  order_id::TEXT AS order_id,
  line_no::BIGINT AS line_no,
  discount::DECIMAL(12, 4) AS discount,
  created_at::TEXT AS created_at
FROM bronze.corpus__order_items
