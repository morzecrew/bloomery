-- Two inner joins, each on a key, each many-to-one in the direction it is
-- written. Nothing here looks like a fan-out and the result is 250.00.
SELECT ROUND(SUM(o.revenue), 2) AS revenue
FROM bronze.corpus__orders o
JOIN bronze.corpus__order_promos b ON b.order_id = o.order_id
JOIN bronze.corpus__promos p ON p.promo_id = b.promo_id;
