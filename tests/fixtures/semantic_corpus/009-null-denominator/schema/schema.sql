-- One row per shipment: what the carrier charged, and how many parcels moved.
-- A cancelled shipment still costs money and moves nothing, which is the row
-- the ratio has no denominator for.
CREATE TABLE bronze.corpus__shipments (
    shipment_id VARCHAR,
    carrier_cost DECIMAL(12, 2),
    parcels      INTEGER,
    shipped_on   DATE
);
