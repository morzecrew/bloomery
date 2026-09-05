CREATE TABLE bronze.corpus__orders (
    order_id    VARCHAR,
    customer_id VARCHAR,
    created_at  VARCHAR,
    amount      DECIMAL(12, 4)
);

-- One row per version per key. `customer_id` is the business key and is not
-- unique here — which is the whole case.
--
-- In `silver`, and seeded rather than derived: type-2 versions come from the
-- operator's snapshotting, not from anything bloomery builds out of bronze.
CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE silver.customer_tier (
    customer_id VARCHAR,
    tier        VARCHAR,
    valid_from  TIMESTAMP,
    valid_to    TIMESTAMP
);

-- The bronze relation the mapping names. It exists because the spec declares
-- the entity, and it is empty because nothing here builds the versions from
-- it: a case creating a `silver.` relation is telling the harness that one is
-- supplied, and bloomery's model for it is not run.
CREATE TABLE bronze.corpus__customer_tier (
    customer_id VARCHAR,
    tier        VARCHAR
);
