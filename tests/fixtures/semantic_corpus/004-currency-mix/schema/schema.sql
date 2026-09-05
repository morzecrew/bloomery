-- A payment processor's export: the settled amount in the currency it was
-- taken in, and the fee always in USD.
CREATE TABLE bronze.corpus__payments (
    payment_id VARCHAR,
    amount_eur DECIMAL(12, 4),
    fee_usd    DECIMAL(12, 4),
    paid_at    DATE
);

-- The rate relation the operator supplies. bloomery reads one; it never
-- invents one.
CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE silver.fx_rate (
    from_ccy   VARCHAR,
    to_ccy     VARCHAR,
    rate       DECIMAL(18, 8),
    valid_from DATE,
    valid_to   DATE
);
