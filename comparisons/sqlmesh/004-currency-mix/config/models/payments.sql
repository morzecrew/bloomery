-- The processor's export: the settled amount in euros, the fee in dollars.
-- Both columns are DECIMAL, and nothing below says which currency either is in.
MODEL (
  name silver.payments,
  kind FULL,
  grain payment_id
);

SELECT
  payment_id::TEXT AS payment_id,
  amount_eur::DECIMAL(12, 4) AS amount_eur,
  fee_usd::DECIMAL(12, 4) AS fee_usd,
  paid_at::DATE AS paid_at
FROM bronze.corpus__payments
