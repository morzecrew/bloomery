-- The denormalized export that makes the trap available: shipping is a fact
-- about an order, and every line of that order carries a copy of it.
CREATE SCHEMA IF NOT EXISTS corpus;

CREATE TABLE corpus.orders (
    order_id VARCHAR,
    shipping DECIMAL(12, 4)
);

CREATE TABLE corpus.order_items (
    order_id   VARCHAR,
    line_no    BIGINT,
    unit_price DECIMAL(12, 4)
);
