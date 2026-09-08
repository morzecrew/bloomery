-- A distinct count is computed over the rows at the grain asked for, never
-- rolled up from a finer one.
SELECT COUNT(DISTINCT user_id) AS active_users
FROM bronze.corpus__sessions;
