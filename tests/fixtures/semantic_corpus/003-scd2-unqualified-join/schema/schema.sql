CREATE SCHEMA IF NOT EXISTS corpus;

CREATE TABLE corpus.orders (
    order_id    VARCHAR,
    customer_id VARCHAR,
    ordered_at  TIMESTAMP,
    amount      DECIMAL(12, 4)
);

-- One row per version per key. `customer_id` is the business key and is not
-- unique here — which is the whole case.
CREATE TABLE corpus.customer_tier (
    customer_id VARCHAR,
    tier        VARCHAR,
    valid_from  TIMESTAMP,
    valid_to    TIMESTAMP
);
