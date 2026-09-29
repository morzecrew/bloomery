-- The relation at bridge grain the case's `bridged` expectation declares: one
-- row per promotion applied to an order, carrying the order's revenue. The
-- case creates only the three normalized tables; this is `naive.sql`'s join,
-- made from them and nothing else.
CREATE VIEW bronze.order_promos_wide AS
SELECT b.order_id, b.promo_id, b.applied_on, o.revenue
FROM bronze.corpus__order_promos AS b
JOIN bronze.corpus__orders AS o ON o.order_id = b.order_id;
