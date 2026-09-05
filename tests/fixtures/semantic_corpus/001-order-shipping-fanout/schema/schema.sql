-- The denormalized export that makes the trap available: shipping is a fact
-- about an order, and every line of that order carries a copy of it.
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
