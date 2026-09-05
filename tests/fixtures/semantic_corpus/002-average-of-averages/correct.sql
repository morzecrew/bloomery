-- The ratio is recomputed from its operands: total value over total count.
SELECT CAST(SUM(unit_price) / COUNT(*) AS DECIMAL(18, 8)) AS average_item_price
FROM corpus.order_items;
