-- The ratio recomputed per group, which is what non-additive means: the
-- numerator and denominator are summed within the group and divided *after*,
-- never averaged from a stored per-row ratio.
SELECT ordered_month, SUM(amount) / NULLIF(COUNT(order_id), 0) AS average_order_value
FROM gold.mart_orders
GROUP BY ordered_month
