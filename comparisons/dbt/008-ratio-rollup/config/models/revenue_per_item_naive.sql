-- The project-authored reading of the naive metric: average each order's own
-- rate. dbt Core renders no SQL for a metric, so this model is what produces
-- the number the naive definition describes.
select round(avg(revenue / item_count), 2) as revenue_per_item
from {{ ref('orders') }}
