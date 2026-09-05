-- Sum the balance column. Legal, fast, and the number means nothing: it adds
-- Monday's money to Tuesday's copy of the same money.
SELECT SUM(balance) AS total_balance
FROM bronze.corpus__balances;
