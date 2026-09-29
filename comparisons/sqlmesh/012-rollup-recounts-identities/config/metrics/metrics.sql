-- Read from the rollup, the way a dashboard reads it. Revenue survives the
-- re-addition; the buyer count does not, and both expressions are one SUM.
METRIC (
  name revenue_rolled,
  expression SUM(silver.daily_sales.daily_revenue)
);

METRIC (
  name buyers_rolled,
  expression SUM(silver.daily_sales.daily_buyers)
);

-- Read from the orders themselves.
METRIC (
  name revenue,
  expression SUM(silver.orders.amount)
);

METRIC (
  name buyers,
  expression COUNT(DISTINCT silver.orders.customer_id)
);
