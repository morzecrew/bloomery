-- The same versions declared without a grain: only the business key the
-- ERD joins on, as a reference. Its tier column is named apart from
-- `silver.tier_versions.tier` so a request can name one model or the other.
MODEL (
  name silver.tier_history,
  kind FULL,
  references (customer_id)
);

SELECT
  customer_id::TEXT AS customer_id,
  tier::TEXT AS history_tier,
  valid_from::TIMESTAMP AS valid_from,
  valid_to::TIMESTAMP AS valid_to
FROM silver.customer_tier
