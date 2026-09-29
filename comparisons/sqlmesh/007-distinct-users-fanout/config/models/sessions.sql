-- One row per session: who had it, and on which day.
MODEL (
  name silver.sessions,
  kind FULL,
  grain session_id,
  references (user_id)
);

SELECT
  session_id::TEXT AS session_id,
  user_id::TEXT AS user_id,
  session_day::DATE AS session_day
FROM bronze.corpus__sessions
