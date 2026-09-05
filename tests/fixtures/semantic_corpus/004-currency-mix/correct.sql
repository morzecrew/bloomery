-- The EUR side is converted at the rate in force on the payment's own date,
-- and only then added to money already in USD.
SELECT SUM(CAST(p.amount_eur * r.rate AS DECIMAL(12, 4)) + p.fee_usd) AS total_usd
FROM bronze.corpus__payments AS p
JOIN silver.fx_rate AS r
  ON r.from_ccy = 'EUR' AND r.to_ccy = 'USD'
 AND p.paid_at >= r.valid_from AND p.paid_at < r.valid_to;
