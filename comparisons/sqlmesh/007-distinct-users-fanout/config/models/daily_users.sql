-- A daily pre-aggregate, built the way one is built: each day's distinct
-- users, correct for that day. Nothing below says the count is distinct, so
-- nothing says it may not be summed across days.
MODEL (
  name silver.daily_users,
  kind FULL,
  grain session_day
);

SELECT
  session_day,
  COUNT(DISTINCT user_id) AS daily_users
FROM silver.sessions
GROUP BY session_day
