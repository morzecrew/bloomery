METRIC (
  name carrier_cost_total,
  expression SUM(silver.shipments.carrier_cost)
);

METRIC (
  name parcel_count,
  expression SUM(silver.shipments.parcels)
);

-- Every shipment's cost over every shipment's parcels: the cancelled
-- shipment's charge is carried by the parcels the other two moved.
METRIC (
  name cost_per_parcel_inclusive,
  expression carrier_cost_total / parcel_count
);

METRIC (
  name carrier_cost_of_moved,
  expression SUM(CASE WHEN silver.shipments.parcels > 0 THEN silver.shipments.carrier_cost END)
);

METRIC (
  name parcel_count_of_moved,
  expression SUM(CASE WHEN silver.shipments.parcels > 0 THEN silver.shipments.parcels END)
);

-- The same ratio over the rows that have a denominator, written as SQL in
-- each operand because there is no key for the rows a ratio is over.
METRIC (
  name cost_per_parcel_restricted,
  expression carrier_cost_of_moved / parcel_count_of_moved
);

-- The same restricted ratio written as one expression instead of a derived
-- metric over two. It loads, and what it renders is measured in `observed.txt`.
METRIC (
  name cost_per_parcel_compound,
  expression SUM(CASE WHEN silver.shipments.parcels > 0 THEN silver.shipments.carrier_cost END) / SUM(CASE WHEN silver.shipments.parcels > 0 THEN silver.shipments.parcels END)
);
