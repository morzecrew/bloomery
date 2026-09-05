-- The same join, read as of the order's own date: one version per order.
SELECT SUM(o.amount) AS revenue
FROM corpus.orders AS o
JOIN corpus.customer_tier AS t
  ON o.customer_id = t.customer_id
 AND o.ordered_at >= t.valid_from
 AND o.ordered_at <  t.valid_to;
