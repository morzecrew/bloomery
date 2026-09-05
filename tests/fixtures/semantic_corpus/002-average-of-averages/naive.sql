-- Average the published per-order averages. Every row read is correct, the
-- aggregate is legal, and the result answers a question nobody asked.
--
-- Cast because `AVG` is double in DuckDB and this corpus asserts exact
-- decimal arithmetic (RFC 0003 D5) — the cast is presentation, not the bug.
SELECT CAST(AVG(average_item_price) AS DECIMAL(18, 8)) AS average_item_price
FROM bronze.corpus__order_summaries;
