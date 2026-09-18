-- The semi-additive reduction, written as SQL by this project's author,
-- because SQLMesh's metric vocabulary has no key for a non-additive axis:
-- each account at the last day the snapshot carries.
MODEL (
  name silver.latest_balances,
  kind FULL,
  grain account_id,
  references (account_id)
);

SELECT
  account_id,
  as_of_day,
  balance
FROM silver.balances AS b
WHERE b.as_of_day = (SELECT MAX(as_of_day) FROM silver.balances)
