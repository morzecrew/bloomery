-- February by the wall clock, which is five hours off the instant: o1 was
-- placed at 21:30 on 31 January local and reads as a January order.
METRIC (
  name february_revenue_zoneless,
  expression SUM(CASE WHEN silver.orders.placed_at >= TIMESTAMP '2025-02-01 00:00:00' AND silver.orders.placed_at < TIMESTAMP '2025-03-01 00:00:00' THEN silver.orders.revenue END)
);

-- February by the instant, over the model that already converted.
METRIC (
  name february_revenue_anchored,
  expression SUM(CASE WHEN silver.orders_anchored.placed_at_utc >= TIMESTAMPTZ '2025-02-01 00:00:00+00' AND silver.orders_anchored.placed_at_utc < TIMESTAMPTZ '2025-03-01 00:00:00+00' THEN silver.orders_anchored.revenue END)
);
