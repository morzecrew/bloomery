-- The per-day distinct count every product dashboard starts from. Each row is
-- a correct number about its day.
select session_day, count(distinct user_id) as daily_users
from {{ ref('sessions') }}
group by session_day
