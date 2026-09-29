-- dbt requires a day-or-finer time spine in any project that declares metrics.
select cast(range as date) as date_day
from range(date '2025-01-01', date '2025-04-01', interval 1 day)
