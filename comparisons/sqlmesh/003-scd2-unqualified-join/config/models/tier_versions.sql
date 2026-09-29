-- The type-2 tier history the case supplies as `silver.customer_tier`: one
-- row per customer per version. Named apart from it so the view SQLMesh
-- publishes does not collide with the supplied relation.
MODEL (
  name silver.tier_versions,
  kind FULL,
  grain (customer_id, valid_from),
  references (customer_id)
);

SELECT
  customer_id::TEXT AS customer_id,
  tier::TEXT AS tier,
  valid_from::TIMESTAMP AS valid_from,
  valid_to::TIMESTAMP AS valid_to
FROM silver.customer_tier
