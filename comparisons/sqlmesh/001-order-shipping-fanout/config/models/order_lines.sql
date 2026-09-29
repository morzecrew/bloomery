-- The wide export at line grain: every line carries its order's shipping.
-- This is the corpus's naive join, written as a model by this project's
-- author, and its grain is honest — one row per line.
MODEL (
  name silver.order_lines,
  kind FULL,
  grain (order_id, line_no)
);

SELECT
  i.order_id,
  i.line_no,
  i.unit_price,
  o.shipping
FROM silver.order_items AS i
JOIN silver.orders AS o
  ON i.order_id = o.order_id
