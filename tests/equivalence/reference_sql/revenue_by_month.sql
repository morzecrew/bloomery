-- Hand-written, against the mart directly. Neither engine's SQL is consulted
-- to produce it: that is the whole point of a third leg.
SELECT ordered_month, SUM(unit_price * quantity) AS gross_revenue
FROM gold.mart_order_items
GROUP BY ordered_month
