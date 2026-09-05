-- Equality on the business key, which is what every ERD says to join on.
-- `customer_tier` holds two rows for `c1`, so each order matches both and
-- every amount is counted once per version.
SELECT SUM(o.amount) AS revenue
FROM corpus.orders AS o
JOIN corpus.customer_tier AS t ON o.customer_id = t.customer_id;
