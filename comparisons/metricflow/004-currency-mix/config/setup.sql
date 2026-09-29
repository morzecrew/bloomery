-- The conversion, as project-authored SQL: a measure's `expr` reads only its
-- own semantic model's columns, so the rate has to be joined in before
-- MetricFlow sees the rows. Both views are the case's own `correct.sql` join;
-- the second differs only in the currency it asks the rate relation for.
CREATE VIEW bronze.payments_converted AS
SELECT p.payment_id, p.paid_at, p.fee_usd,
       CAST(p.amount_eur * r.rate AS DECIMAL(12, 4)) AS amount_usd
FROM bronze.corpus__payments AS p
JOIN silver.fx_rate AS r
  ON r.from_ccy = 'EUR' AND r.to_ccy = 'USD'
 AND p.paid_at >= r.valid_from AND p.paid_at < r.valid_to;

CREATE VIEW bronze.payments_converted_as_jpy AS
SELECT p.payment_id, p.paid_at, p.fee_usd,
       CAST(p.amount_eur * r.rate AS DECIMAL(12, 4)) AS amount_usd
FROM bronze.corpus__payments AS p
JOIN silver.fx_rate AS r
  ON r.from_ccy = 'JPY' AND r.to_ccy = 'USD'
 AND p.paid_at >= r.valid_from AND p.paid_at < r.valid_to;
