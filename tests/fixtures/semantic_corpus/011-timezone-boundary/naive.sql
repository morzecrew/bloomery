-- The timestamp parses, the comparison is well-typed, and the boundary is off
-- by five hours: o1 lands in January and February reports 40.00.
SELECT ROUND(COALESCE(SUM(revenue), 0), 2) AS february_revenue
FROM bronze.corpus__orders
WHERE CAST(placed_at AS TIMESTAMP) >= TIMESTAMP '2025-02-01 00:00:00'
  AND CAST(placed_at AS TIMESTAMP) <  TIMESTAMP '2025-03-01 00:00:00';
