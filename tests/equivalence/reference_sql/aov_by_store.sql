SELECT store, SUM(amount) / NULLIF(COUNT(order_id), 0) AS average_order_value
FROM gold.mart_orders
GROUP BY store
