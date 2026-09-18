-- The same orders at the instant they happened, which takes a dialect-specific
-- conversion written by this project's author: SQLMesh carries the expression
-- through without knowing it is a zone conversion.
MODEL (
  name silver.orders_anchored,
  kind FULL,
  grain order_id,
  references (order_id)
);

SELECT
  order_id,
  revenue,
  placed_at AT TIME ZONE 'America/New_York' AS placed_at_utc
FROM silver.orders
