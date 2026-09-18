-- The wrong reading: an average of a column that is already an average.
METRIC (
  name average_item_price_naive,
  expression AVG(silver.order_summaries.average_item_price)
);

METRIC (
  name unit_price_total,
  expression SUM(silver.order_items.unit_price)
);

METRIC (
  name line_count,
  expression COUNT(silver.order_items.line_no)
);

-- The right one: a ratio rebuilt from operands that each sum.
METRIC (
  name average_item_price_decomposed,
  expression unit_price_total / line_count
);
