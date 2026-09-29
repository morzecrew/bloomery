-- One row per promotion.
MODEL (
  name silver.promos,
  kind FULL,
  grain promo_id
);

SELECT
  promo_id::TEXT AS promo_id,
  label::TEXT AS label
FROM bronze.corpus__promos
