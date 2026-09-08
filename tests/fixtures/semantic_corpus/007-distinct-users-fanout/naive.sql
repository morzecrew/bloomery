-- Count distinct users per day, then add the days up. Every step is legal, the
-- daily numbers are each right, and the total counts u1 twice.
SELECT SUM(daily_users) AS active_users
FROM (
    SELECT session_day, COUNT(DISTINCT user_id) AS daily_users
    FROM bronze.corpus__sessions
    GROUP BY session_day
) AS by_day;
