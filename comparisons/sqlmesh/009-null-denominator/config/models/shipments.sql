-- One row per shipment: what the carrier charged, and how many parcels moved.
-- `s3` was cancelled after the charge, so its `parcels` is a known zero.
--
-- The audit is non-blocking on purpose: it is here to be measured, not to make
-- the plan fail. What it flags is a legitimate row.
MODEL (
  name silver.shipments,
  kind FULL,
  grain shipment_id,
  references (shipment_id),
  audits (accepted_range(column := parcels, min_v := 1, blocking := false))
);

SELECT
  shipment_id::TEXT AS shipment_id,
  carrier_cost::DECIMAL(12, 2) AS carrier_cost,
  parcels::INTEGER AS parcels,
  shipped_on::DATE AS shipped_on
FROM bronze.corpus__shipments
