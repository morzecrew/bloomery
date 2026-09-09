-- A distinct count is computed over the rows of the grain asked for. There is
-- no pre-aggregate it can be summed out of, which is the whole finding.
SELECT COUNT(DISTINCT customer_id) AS buyers
FROM bronze.corpus__orders;
