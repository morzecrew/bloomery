-- Each measure aggregated at its own grain, joined only afterwards. With no
-- grouping each side is a single row, so the join is `ON TRUE` -- which is the
-- degenerate case of the null-safe key join, not a different shape.
SELECT shipping.shipping_total, discounts.discount_total
FROM (SELECT SUM(shipping) AS shipping_total FROM bronze.corpus__orders) AS shipping
FULL OUTER JOIN (
    SELECT SUM(discount) AS discount_total FROM bronze.corpus__order_items
) AS discounts ON TRUE;
