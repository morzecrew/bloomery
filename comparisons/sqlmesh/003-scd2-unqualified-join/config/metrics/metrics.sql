METRIC (
  name revenue,
  expression SUM(silver.orders.amount)
);

METRIC (
  name revenue_as_of,
  expression SUM(silver.orders_as_of.amount)
);
