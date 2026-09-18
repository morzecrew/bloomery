-- The wrong reading: each order's rate is right, and averaging the rates
-- weights a thirty-line order the same as a ten-line one.
METRIC (
  name revenue_per_item_naive,
  expression AVG(silver.orders.revenue / silver.orders.item_count)
);

METRIC (
  name revenue_total,
  expression SUM(silver.orders.revenue)
);

METRIC (
  name item_total,
  expression SUM(silver.orders.item_count)
);

-- The right one: a ratio rebuilt at the grain asked for, from operands that
-- each sum.
METRIC (
  name revenue_per_item_declared,
  expression revenue_total / item_total
);
