-- Shipping is summed at the grain it originates at, and nowhere else.
SELECT SUM(shipping) AS shipping_total
FROM bronze.corpus__orders;
