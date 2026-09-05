-- A balance is additive across accounts and not across time, so time is
-- selected before the sum, never aggregated by it.
SELECT SUM(balance) AS total_balance
FROM corpus.balances AS b
WHERE b.as_of_day = (SELECT MAX(as_of_day) FROM corpus.balances);
