-- The monthly rollup, built the way a rollup is built: group the daily
-- pre-aggregate by month and add the columns up. Revenue survives that; the
-- customer count does not, and nothing about the SQL says which is which.
SELECT SUM(daily_buyers) AS buyers
FROM (
    SELECT ordered_on, COUNT(DISTINCT customer_id) AS daily_buyers
    FROM bronze.corpus__orders
    GROUP BY ordered_on
) AS by_day;
