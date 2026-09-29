-- Each measure over the model that stores it, at its own grain.
METRIC (
  name shipping_total,
  expression SUM(silver.orders.shipping)
);

METRIC (
  name discount_total,
  expression SUM(silver.order_items.discount)
);
