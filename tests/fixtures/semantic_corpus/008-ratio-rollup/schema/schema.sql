-- One row per order, carrying what it earned and how many lines it had.
-- Nothing is duplicated and no value is null; the trap is in the arithmetic.
CREATE TABLE bronze.corpus__orders (
    order_id   VARCHAR,
    revenue    DECIMAL(12, 2),
    item_count INTEGER,
    placed_on  DATE
);
