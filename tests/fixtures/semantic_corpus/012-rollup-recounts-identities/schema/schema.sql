-- An order fact: who bought, how much, and on which day. Every value is valid,
-- nothing is duplicated, and the trap is in a table that does not exist yet —
-- the pre-aggregate somebody builds to make the dashboard fast.
CREATE TABLE bronze.corpus__orders (
    order_id    VARCHAR,
    customer_id VARCHAR,
    amount      DECIMAL(12, 2),
    ordered_on  DATE
);
