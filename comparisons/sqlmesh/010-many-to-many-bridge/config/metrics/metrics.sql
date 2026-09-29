-- Revenue summed where it is stored: one row per order.
METRIC (
  name revenue,
  expression SUM(silver.orders.revenue)
);

-- The same sum over the model that walked the bridge.
METRIC (
  name revenue_through_bridge,
  expression SUM(silver.promoted_orders.revenue)
);
