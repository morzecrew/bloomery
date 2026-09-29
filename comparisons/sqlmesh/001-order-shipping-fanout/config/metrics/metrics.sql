-- Shipping summed where it is stored: one row per order.
METRIC (
  name shipping_total,
  expression SUM(silver.orders.shipping)
);

-- The same sum over the wide model, where each line carries a copy.
METRIC (
  name shipping_total_on_lines,
  expression SUM(silver.order_lines.shipping)
);
