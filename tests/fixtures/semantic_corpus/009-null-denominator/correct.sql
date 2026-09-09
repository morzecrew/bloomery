-- The rows with no denominator are not rows this question is about. 120.00
-- over 40 parcels is 3.00.
SELECT ROUND(SUM(carrier_cost) / SUM(parcels), 2) AS cost_per_parcel
FROM bronze.corpus__shipments
WHERE parcels > 0;
