-- Sum over sum, which is the right shape for a ratio and the wrong set of
-- rows: s3's 40.00 has no parcels of its own, so it is charged to the 40
-- parcels the other two shipments moved. 160.00 over 40 is 4.00.
SELECT ROUND(SUM(carrier_cost) / SUM(parcels), 2) AS cost_per_parcel
FROM bronze.corpus__shipments;
