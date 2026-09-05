-- Valid SQL. Correct join. Declared cardinality is right. Wrong answer.
-- The join is many_to_one, so it does not multiply *orders* — it multiplies
-- the shipping value, once per line, and SUM cannot tell the copies apart.
SELECT SUM(o.shipping) AS shipping_total
FROM corpus.order_items AS i
JOIN corpus.orders AS o USING (order_id);
