-- The same conversion with the wrong pair: the euro amounts are converted as
-- though they were yen. Every cast succeeds; the rate relation carries no JPY
-- row, and nothing in the project says the input was euros.
MODEL (
  name silver.payments_usd_mislabelled,
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
  ON r.from_ccy = 'JPY'
 AND r.to_ccy = 'USD'
 AND p.paid_at >= r.valid_from
 AND p.paid_at < r.valid_to
