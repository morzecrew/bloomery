-- The wrong reading: Monday's money added to Tuesday's copy of it.
METRIC (
  name total_balance_naive,
  expression SUM(silver.balances.balance)
);

-- The right one, over the model that already selected the day.
METRIC (
  name total_balance_declared,
  expression SUM(silver.latest_balances.balance)
);
