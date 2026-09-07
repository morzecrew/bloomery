-- Each measure aggregated at its own grain, joined only afterwards. With no
-- grouping each side is a single row, so the join is a cross product -- which
-- is what bloomery emits for an ungrouped cross-mart request, and what a
-- key-matched join degenerates to when there is no key.
SELECT shipping.shipping_total, discounts.discount_total
FROM (SELECT SUM(shipping) AS shipping_total FROM bronze.corpus__orders) AS shipping
CROSS JOIN (
    SELECT SUM(discount) AS discount_total FROM bronze.corpus__order_items
) AS discounts;
