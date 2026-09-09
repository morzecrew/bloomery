-- An order, a promotion, and the bridge that says which promotions an order
-- used. The bridge is the ordinary modelling of a many-to-many, and each of
-- its two edges points at *one* row — which is what makes the fan-out invisible.
CREATE TABLE bronze.corpus__orders (
    order_id  VARCHAR,
    revenue   DECIMAL(12, 2),
    placed_on DATE
);

CREATE TABLE bronze.corpus__promos (
    promo_id VARCHAR,
    label    VARCHAR
);

CREATE TABLE bronze.corpus__order_promos (
    order_id   VARCHAR,
    promo_id   VARCHAR,
    applied_on DATE
);
