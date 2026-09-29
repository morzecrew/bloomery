-- Each payment with its euro side converted at the rate in force on the day
-- it was paid. The pair, the dated join and the multiplication are SQL this
-- project's author wrote; SQLMesh carries them through as expressions.
MODEL (
  name silver.payments_usd,
  kind FULL,
  grain payment_id
);

SELECT
  p.payment_id,
  CAST(p.amount_eur * r.rate AS DECIMAL(12, 4)) AS amount_usd,
  p.fee_usd,
  p.paid_at
FROM silver.payments AS p
JOIN silver.fx_rates AS r
  ON r.from_ccy = 'EUR'
 AND r.to_ccy = 'USD'
 AND p.paid_at >= r.valid_from
 AND p.paid_at < r.valid_to
