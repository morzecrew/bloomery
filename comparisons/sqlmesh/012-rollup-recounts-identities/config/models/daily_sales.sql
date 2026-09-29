-- The pre-aggregate somebody builds to make the dashboard fast: per day, the
-- revenue and the distinct buyers. Both columns are correct for their day.
MODEL (
  name silver.daily_sales,
  kind FULL,
  grain ordered_on
);

SELECT
  ordered_on,
  SUM(amount) AS daily_revenue,
  COUNT(DISTINCT customer_id) AS daily_buyers
FROM silver.orders
GROUP BY ordered_on
