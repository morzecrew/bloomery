-- Orders as the source system publishes them: a local wall-clock timestamp
-- with no zone on it. The zone is a fact about the *system*, written in its
-- documentation and nowhere in its data.
CREATE TABLE bronze.corpus__orders (
    order_id  VARCHAR,
    revenue   DECIMAL(12, 2),
    placed_at VARCHAR
);
