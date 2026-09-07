-- Valid SQL, correct join, and the only shape that puts both columns in one
-- relation. `discount_total` is right; `shipping_total` is multiplied once per
-- line of its order, and nothing in the result says which half to trust.
SELECT
    SUM(o.shipping) AS shipping_total,
    SUM(i.discount) AS discount_total
FROM bronze.corpus__order_items AS i
JOIN bronze.corpus__orders AS o USING (order_id);
