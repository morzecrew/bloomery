-- The project-authored reading of the naive metric: add the days up. dbt Core
-- renders no SQL for a metric, so this model is what produces the number.
select sum(daily_users) as active_users
from {{ ref('daily_active_users') }}
