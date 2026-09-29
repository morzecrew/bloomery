-- The rate relation the case supplies as `silver.fx_rate`. Named apart from it
-- so the view SQLMesh publishes does not collide with the supplied relation.
MODEL (
  name silver.fx_rates,
  kind FULL,
  grain (from_ccy, to_ccy, valid_from)
);

SELECT
  from_ccy::TEXT AS from_ccy,
  to_ccy::TEXT AS to_ccy,
  rate::DECIMAL(18, 8) AS rate,
  valid_from::DATE AS valid_from,
  valid_to::DATE AS valid_to
FROM silver.fx_rate
