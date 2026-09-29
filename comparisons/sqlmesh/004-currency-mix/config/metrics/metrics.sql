-- The wrong reading: euros and dollars added as though they were one unit.
METRIC (
  name total_usd_mixed,
  expression SUM(silver.payments.amount_eur + silver.payments.fee_usd)
);

-- The right one, over the model that already converted.
METRIC (
  name total_usd_converted,
  expression SUM(silver.payments_usd.amount_usd + silver.payments_usd.fee_usd)
);

-- The same shape over the conversion that names the wrong input currency.
METRIC (
  name total_usd_mislabelled,
  expression SUM(silver.payments_usd_mislabelled.amount_usd + silver.payments_usd_mislabelled.fee_usd)
);
