-- The wrong reading: the daily distinct counts added up.
METRIC (
  name active_users_summed,
  expression SUM(silver.daily_users.daily_users)
);

-- The right one: a distinct count over the sessions themselves.
METRIC (
  name active_users,
  expression COUNT(DISTINCT silver.sessions.user_id)
);
