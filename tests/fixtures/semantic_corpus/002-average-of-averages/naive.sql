-- Average the per-order averages. Every step is a legal aggregate over a
-- correct grouping, and the result answers a question nobody asked.
--
-- Cast because `AVG` is double in DuckDB and this corpus asserts exact
-- decimal arithmetic (RFC 0003 D5) — the cast is presentation, not the bug.
SELECT CAST(AVG(order_average) AS DECIMAL(18, 8)) AS average_item_price
FROM (
    SELECT order_id, AVG(unit_price) AS order_average
    FROM corpus.order_items
    GROUP BY order_id
);
