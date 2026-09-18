MODEL (
  name silver.order_items,
  kind FULL,
  grain (order_id, line_no),
  references (order_id)
);

SELECT
  order_id::TEXT AS order_id,
  line_no::BIGINT AS line_no,
  unit_price::DECIMAL(12, 4) AS unit_price,
  created_at::TEXT AS created_at
FROM bronze.corpus__order_items
