-- Each order's revenue per item is right, and averaging them is not: it weights
-- a 30-line order the same as a 10-line one. 3.00 and 4.00 average to 3.50.
SELECT ROUND(AVG(revenue / item_count), 2) AS revenue_per_item
FROM bronze.corpus__orders;
