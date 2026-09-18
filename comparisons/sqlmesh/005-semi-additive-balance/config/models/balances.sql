-- A daily snapshot: one row per account per day, carrying that day's state.
-- The balance is additive across accounts and not across days, and nothing
-- below says so.
MODEL (
  name silver.balances,
  kind FULL,
  grain (account_id, as_of_day),
  references (account_id)
);

SELECT
  account_id::TEXT AS account_id,
  as_of_day::DATE AS as_of_day,
  balance::DECIMAL(12, 4) AS balance
FROM bronze.corpus__balances
