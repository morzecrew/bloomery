-- The project-authored reading of the question off the rollup. dbt Core
-- renders no SQL for a metric, so this model is what produces the numbers.
select buyers, revenue
from {{ ref('orders_monthly') }}
where order_month = timestamp '2025-01-01'
