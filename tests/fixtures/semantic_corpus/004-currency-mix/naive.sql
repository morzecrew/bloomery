-- Both columns are money, both are decimal(12,4), and the addition compiles.
-- Nothing in the types records that one of them is denominated in a different
-- currency, so the total is a number with no unit.
SELECT SUM(amount_eur + fee_usd) AS total_usd
FROM bronze.corpus__payments;
