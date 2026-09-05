CREATE SCHEMA IF NOT EXISTS corpus;

CREATE TABLE corpus.order_items (
    order_id   VARCHAR,
    line_no    BIGINT,
    unit_price DECIMAL(12, 4)
);
