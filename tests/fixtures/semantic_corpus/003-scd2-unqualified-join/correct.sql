-- The same join, read as of the order's own date: one version per order.
SELECT SUM(o.amount) AS revenue
FROM bronze.corpus__orders AS o
JOIN silver.customer_tier AS t
  ON o.customer_id = t.customer_id
 AND CAST(o.created_at AS TIMESTAMP) >= t.valid_from
 AND CAST(o.created_at AS TIMESTAMP) <  t.valid_to;
