-- Revenue is a fact about an order and is summed over orders, whatever the
-- bridge says about them: 150.00.
SELECT ROUND(SUM(revenue), 2) AS revenue
FROM bronze.corpus__orders;
