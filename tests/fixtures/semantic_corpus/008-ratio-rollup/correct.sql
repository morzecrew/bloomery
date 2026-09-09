-- A ratio is rebuilt at the grain asked for, from operands that each sum:
-- 130.00 over 40 items is 3.25.
SELECT ROUND(SUM(revenue) / SUM(item_count), 2) AS revenue_per_item
FROM bronze.corpus__orders;
