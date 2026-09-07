-- Two normalized tables. Shipping is stored once per order and discount once
-- per line, which is what makes one question about both a question about two
-- grains -- and what makes the join that puts them in one relation wrong for
-- one of the two columns.
CREATE TABLE bronze.corpus__orders (
    order_id   VARCHAR,
    shipping   DECIMAL(12, 4),
    created_at VARCHAR
);

CREATE TABLE bronze.corpus__order_items (
    order_id   VARCHAR,
    line_no    BIGINT,
    discount   DECIMAL(12, 4),
    created_at VARCHAR
);
