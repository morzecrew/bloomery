-- The wide export the case warns about, built the way a warehouse builds it:
-- one row per line, the order's shipping copied onto each. The case creates
-- only the normalized tables, so the relation a line-grain model reads is made
-- here, from them, and nothing about it is edited by hand.
CREATE VIEW bronze.order_items_wide AS
SELECT i.order_id, i.line_no, i.unit_price, i.created_at, o.shipping
FROM bronze.corpus__order_items AS i
JOIN bronze.corpus__orders AS o USING (order_id);
