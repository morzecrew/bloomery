CREATE TABLE bronze.corpus__order_items (
    order_id   VARCHAR,
    line_no    BIGINT,
    unit_price DECIMAL(12, 4),
    created_at VARCHAR
);

-- The per-order rollup the upstream system already publishes. Nothing is
-- wrong with it: each row is a correct average of that order's lines. What is
-- wrong is what happens next.
CREATE TABLE bronze.corpus__order_summaries (
    order_id           VARCHAR,
    average_item_price DECIMAL(12, 4),
    created_at         VARCHAR
);
