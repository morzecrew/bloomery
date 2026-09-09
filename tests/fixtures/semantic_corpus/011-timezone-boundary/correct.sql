-- The same comparison against the instant the order actually happened:
-- the local wall clock read in the zone it was written in. 140.00.
SELECT ROUND(COALESCE(SUM(revenue), 0), 2) AS february_revenue
FROM bronze.corpus__orders
WHERE CAST(placed_at AS TIMESTAMP) AT TIME ZONE 'America/New_York' >= TIMESTAMPTZ '2025-02-01 00:00:00+00'
  AND CAST(placed_at AS TIMESTAMP) AT TIME ZONE 'America/New_York' <  TIMESTAMPTZ '2025-03-01 00:00:00+00';
