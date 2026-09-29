-- The corpus's naive join, as a model this project's author wrote: orders
-- through the bridge to their promotions, one row per bridge row.
MODEL (
  name silver.promoted_orders,
  kind FULL
);

SELECT
  o.order_id,
  o.revenue,
  p.label
FROM silver.orders AS o
JOIN silver.order_promos AS b
  ON b.order_id = o.order_id
JOIN silver.promos AS p
  ON p.promo_id = b.promo_id
