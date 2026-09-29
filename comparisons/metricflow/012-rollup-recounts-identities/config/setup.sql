-- The monthly pre-aggregate the case describes, built the way `naive.sql`
-- builds it: daily counts first, then the month adds the columns up. The case
-- creates only the orders; this relation is made from them and nothing else.
CREATE VIEW bronze.orders_monthly AS
SELECT DATE_TRUNC('month', ordered_on) AS ordered_month,
       SUM(daily_revenue) AS revenue,
       SUM(daily_buyers) AS buyers
FROM (
    SELECT ordered_on,
           SUM(amount) AS daily_revenue,
           COUNT(DISTINCT customer_id) AS daily_buyers
    FROM bronze.corpus__orders
    GROUP BY ordered_on
) AS by_day
GROUP BY 1;
