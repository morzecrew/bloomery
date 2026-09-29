-- The per-day distinct counts the naive query adds up, as the relation a
-- project would materialize for a daily-active-users chart. The case creates
-- only the sessions; this is built from them and nothing else.
CREATE VIEW bronze.daily_active_users AS
SELECT session_day, COUNT(DISTINCT user_id) AS daily_users
FROM bronze.corpus__sessions
GROUP BY session_day;
