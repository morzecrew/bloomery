CREATE SCHEMA IF NOT EXISTS corpus;

-- A snapshot fact: one row per account per day, carrying the state of the
-- account on that day. Not an event, and not a delta.
CREATE TABLE corpus.balances (
    account_id VARCHAR,
    as_of_day  DATE,
    balance    DECIMAL(12, 4)
);
