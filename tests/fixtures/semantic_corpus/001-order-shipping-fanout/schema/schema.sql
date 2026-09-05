-- Two normalized tables, which is what makes the trap available: shipping is a
-- fact about an order and is stored once, so joining orders to their lines
-- hands every line a copy of it and summing the joined rows counts it once per
-- line. Nothing here is denormalized -- the duplication is the join's.
CREATE TABLE bronze.corpus__orders (
    order_id VARCHAR,
    shipping DECIMAL(12, 4),
    created_at VARCHAR
);

CREATE TABLE bronze.corpus__order_items (
    order_id   VARCHAR,
    line_no    BIGINT,
    unit_price DECIMAL(12, 4),
    created_at VARCHAR
);
