-- The bridge: one row per promotion applied to an order. Each row names one
-- order and one promotion, which is what its two references say.
MODEL (
  name silver.order_promos,
  kind FULL,
  references (order_id, promo_id)
);

SELECT
  order_id::TEXT AS order_id,
  promo_id::TEXT AS promo_id,
  applied_on::DATE AS applied_on
FROM bronze.corpus__order_promos
